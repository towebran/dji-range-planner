import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

# --- 1. SETTINGS & RF PHYSICS ---
st.set_page_config(layout="wide", page_title="DJI M4TD Tactical Planner")

TX_POWER = 33.0     
REQD_SIGNAL = -90.0 
FREQ = 2.4          
D_STEP = 800        

# Initialize Session State
if 'center' not in st.session_state: st.session_state.center = [34.065, -84.677]
if 'dock_confirmed' not in st.session_state: st.session_state.dock_confirmed = False
if 'dock_stack' not in st.session_state: st.session_state.dock_stack = {"b_height": 0.0, "ant_h": 15.0, "total_msl": 0.0}
if 'vault' not in st.session_state: st.session_state.vault = []
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'staged_obs' not in st.session_state: st.session_state.staged_obs = None
if 'map_v' not in st.session_state: st.session_state.map_v = 1

# --- 2. ENGINES ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=3).json()
        return float(res.get('value', 900.0))
    except: return 900.0

def calculate_rf(dist_ft, h_tx_msl, h_rx_msl, obs_msl):
    dist_km = dist_ft / 3280.84
    fspl = 20 * math.log10(max(0.01, dist_km)) + 20 * math.log10(FREQ) + 92.45
    rssi_base = 33.0 - fspl
    mid_dist_m = (dist_ft / 2) * 0.3048
    wavelength = 0.125
    beam_h = h_tx_msl + (h_rx_msl - h_tx_msl) * 0.5
    h_clearance = beam_h - obs_msl
    v = -h_clearance * math.sqrt(2 / (wavelength * mid_dist_m))
    loss = 6.9 + 20 * math.log10(math.sqrt((v-0.1)**2 + 1) + v - 0.1) if v > -0.7 else 0
    return rssi_base - loss

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛡️ M4TD Tactical Planner")
    
    # PHASE 1: SEARCH & DOCK PLACEMENT
    if not st.session_state.dock_confirmed:
        st.header("Step 1: Set & Verify Dock")
        query = st.text_input("Find Site (Address or Lat/Lon)", placeholder="e.g. 34.0, -84.6")
        if st.button("📍 Search"):
            if "," in query:
                try:
                    lat, lon = map(float, query.split(","))
                    st.session_state.center = [lat, lon]
                except: st.error("Invalid Lat/Lon")
            else:
                arc_url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={query}&maxLocations=1"
                res = requests.get(arc_url).json()
                if res.get('candidates'):
                    loc = res['candidates'][0]['location']
                    st.session_state.center = [loc['y'], loc['x']]
            st.session_state.map_v += 1
            st.rerun()
        
        st.info("1. Click map to move BLUE marker.\n2. Enter Dock heights below.")
        
        # DOCK VERTICAL STACK INPUT
        d_ground = get_elev_msl(st.session_state.center[0], st.session_state.center[1])
        d_bldg = st.number_input("Dock Building Height AGL (ft)", value=0.0)
        d_ant = st.number_input("Dock Antenna Height above Building (ft)", value=15.0)
        
        total_dock_msl = d_ground + d_bldg + d_ant
        st.success(f"**Dock TX MSL: {total_dock_msl} ft**")

        if st.button("✅ Confirm Dock & Heights"):
            st.session_state.dock_stack = {"b_height": d_bldg, "ant_h": d_ant, "total_msl": total_dock_msl}
            st.session_state.dock_confirmed = True
            st.rerun()
            
    # PHASE 2: OBSTACLE SURVEY
    else:
        st.header("Step 2: Survey Obstacles")
        st.write(f"🏠 **Dock MSL:** {st.session_state.dock_stack['total_msl']} ft")
        if st.button("⬅️ Change Dock Location/Height"):
            st.session_state.dock_confirmed = False
            st.session_state.vault = []
            st.rerun()
        
        st.divider()
        if st.session_state.staged_obs:
            st.warning(f"Obstacle: {st.session_state.staged_obs['dir']} @ {int(st.session_state.staged_obs['dist'])}ft")
            # User manually enters the Top MSL of the obstacle (tree/building)
            obs_msl_input = st.number_input("Obstacle Top MSL (ft)", value=st.session_state.staged_obs['ground'] + 50.0)
            
            if st.button("✔️ Lock Obstacle"):
                st.session_state.staged_obs['msl'] = obs_msl_input
                st.session_state.manual_obs.append(st.session_state.staged_obs)
                st.session_state.staged_obs = None
                st.rerun()
            if st.button("❌ Cancel"):
                st.session_state.staged_obs = None
                st.rerun()
        else:
            st.caption("Click map to define an obstacle MSL.")

        st.divider()
        drone_h = st.slider("Drone Mission Alt (ft AGL)", 100, 400, 300)
        clutter = st.slider("Global Tree Buffer (ft)", 0, 100, 60)
        
        if st.button("🚀 RUN STRATEGIC SCAN"):
            with st.spinner("Analyzing Paths..."):
                h_tx_msl = st.session_state.dock_stack['total_msl']
                # h_rx_msl needs ground at dock + mission alt
                dock_ground = h_tx_msl - st.session_state.dock_stack['b_height'] - st.session_state.dock_stack['ant_h']
                h_rx_msl = dock_ground + drone_h
                
                bearings = {"N":0, "NNE":22.5, "NE":45, "ENE":67.5, "E":90, "ESE":112.5, "SE":135, "SSE":157.5, "S":180, "SSW":202.5, "SW":225, "WSW":247.5, "W":270, "WNW":292.5, "NW":315, "NNW":337.5}
                new_vault = []
                for name, ang in bearings.items():
                    path = []
                    last_coord = st.session_state.center
                    for d in range(800, 19000, 800):
                        pt = geodesic(feet=d).destination(st.session_state.center, ang)
                        this_coord = [pt.latitude, pt.longitude]
                        obs_msl = get_elev_msl(pt.latitude, pt.longitude) + clutter
                        for m in st.session_state.manual_obs:
                            if m['dir'] == name and abs(m['dist'] - d) < 600:
                                obs_msl = max(obs_msl, m['msl'])
                        rssi = calculate_rf(d, h_tx_msl, h_rx_msl, obs_msl)
                        color = "#00FF00" if rssi > -80 else "#FFA500" if rssi > -88 else "#FF0000"
                        path.append({"coords": [last_coord, this_coord], "color": color})
                        last_coord = this_coord
                        if rssi < -95: break
                    new_vault.append(path)
                st.session_state.vault = new_vault
                st.rerun()

# --- 4. MAP RENDERING ---
m = folium.Map(location=st.session_state.center, zoom_start=18, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

# Home Point
folium.Marker(st.session_state.center, icon=folium.Icon(color='blue', icon='home')).add_to(m)

if st.session_state.dock_confirmed:
    # 📡 Distance Rings (Every 1 Mile)
    for mi in [1, 2, 3]:
        folium.Circle(st.session_state.center, radius=mi*1609.34, color='white', weight=2, fill=False, opacity=0.5).add_to(m)
        p = geodesic(miles=mi).destination(st.session_state.center, 0)
        folium.Marker([p.latitude, p.longitude], icon=DivIcon(html=f'<div style="color:white; font-size:11px; font-weight:bold; background:rgba(0,0,0,0.6); padding:2px; border-radius:3px;">{mi} MILE</div>')).add_to(m)

    # Scan Paths
    for path in st.session_state.vault:
        for seg in path:
            folium.PolyLine(seg['coords'], color=seg['color'], weight=4, opacity=0.8).add_to(m)

    # Manual Obstacle Markers
    for o in st.session_state.manual_obs:
        folium.Marker(o['coords'], tooltip=f"TIP: {o['msl']}ft", icon=folium.Icon(color='orange', icon='tree', prefix='fa')).add_to(m)

# Click Capture
out = st_folium(m, width=1100, height=650, key=f"map_v{st.session_state.map_v}")

if out and out.get("last_clicked"):
    c_lat, c_lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    
    if not st.session_state.dock_confirmed:
        st.session_state.center = [c_lat, c_lon]
        st.session_state.map_v += 1
        st.rerun()
    else:
        dist = geodesic(st.session_state.center, (c_lat, c_lon)).feet
        # Snap to 16 directions
        dL = math.radians(c_lon - st.session_state.center[1])
        y = math.sin(dL) * math.cos(math.radians(c_lat))
        x = math.cos(math.radians(st.session_state.center[0])) * math.sin(math.radians(c_lat)) - \
            math.sin(math.radians(st.session_state.center[0])) * math.cos(math.radians(c_lat)) * math.cos(dL)
        brng = (math.degrees(math.atan2(y, x)) + 360) % 360
        dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        snap_dir = dirs[int((brng + 11.25) / 22.5) % 16]
        
        st.session_state.staged_obs = {
            "dist": dist, "ground": get_elev_msl(c_lat, c_lon), "dir": snap_dir, "coords": [c_lat, c_lon]
        }
        st.rerun()
