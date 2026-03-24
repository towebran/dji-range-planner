import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

# --- 1. SETTINGS & RF PHYSICS ---
st.set_page_config(layout="wide", page_title="DJI M4TD Tactical Survey")

TX_POWER = 33.0     
REQD_SIGNAL = -90.0 
FREQ = 2.4          
D_STEP = 800        

# Initialize Session State
if 'center' not in st.session_state: st.session_state.center = [34.065, -84.677]
if 'dock_confirmed' not in st.session_state: st.session_state.dock_confirmed = False
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

def calculate_rf(dist_ft, h_tx, h_rx, obs_msl):
    dist_km = dist_ft / 3280.84
    fspl = 20 * math.log10(max(0.01, dist_km)) + 20 * math.log10(FREQ) + 92.45
    rssi_base = 33.0 - fspl
    mid_dist_m = (dist_ft / 2) * 0.3048
    wavelength = 0.125
    beam_h = h_tx + (h_rx - h_tx) * 0.5
    h_clearance = beam_h - obs_msl
    v = -h_clearance * math.sqrt(2 / (wavelength * mid_dist_m))
    loss = 6.9 + 20 * math.log10(math.sqrt((v-0.1)**2 + 1) + v - 0.1) if v > -0.7 else 0
    return rssi_base - loss

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛡️ M4TD Tactical Planner")
    
    # PHASE 1: SEARCH & DOCK PLACEMENT
    if not st.session_state.dock_confirmed:
        st.header("Phase 1: Set Dock")
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
        
        st.info("Click the map to move the BLUE marker to the exact dock spot.")
        if st.button("✅ Confirm Dock Location"):
            st.session_state.dock_confirmed = True
            st.rerun()
            
    # PHASE 2: OBSTACLE SURVEY
    else:
        st.header("Phase 2: Survey Obstacles")
        if st.button("⬅️ Relocate Dock"):
            st.session_state.dock_confirmed = False
            st.session_state.vault = []
            st.rerun()
        
        st.divider()
        if st.session_state.staged_obs:
            st.warning(f"Target: {st.session_state.staged_obs['dir']} @ {int(st.session_state.staged_obs['dist'])}ft")
            g_msl = st.number_input("Ground MSL (Auto)", value=st.session_state.staged_obs['ground'])
            b_msl = st.number_input("Structure Top MSL (from GE)", value=g_msl + 40.0)
            ant_ext = st.number_input("Antenna Height Above Structure (ft)", value=0.0)
            
            final_tip_msl = b_msl + ant_ext
            st.success(f"**Calculated Tip: {final_tip_msl} ft MSL**")
            
            if st.button("✔️ Lock Obstacle"):
                st.session_state.staged_obs['msl'] = final_tip_msl
                st.session_state.manual_obs.append(st.session_state.staged_obs)
                st.session_state.staged_obs = None
                st.rerun()
            if st.button("❌ Cancel"):
                st.session_state.staged_obs = None
                st.rerun()
        else:
            st.caption("Click map to define a building or tree.")

        st.divider()
        ant_h = st.number_input("Dock Antenna Height AGL (ft)", 35.0)
        drone_h = st.slider("Drone Alt (ft AGL)", 100, 400, 300)
        clutter = st.slider("Global Clutter (ft)", 0, 100, 60)
        
        if st.button("🚀 RUN STRATEGIC SCAN"):
            with st.spinner("Analyzing Paths..."):
                dock_g = get_elev_msl(st.session_state.center[0], st.session_state.center[1])
                h_tx, h_rx = dock_g + ant_h + 15, dock_g + drone_h
                
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
                        rssi = calculate_rf(d, h_tx, h_rx, obs_msl)
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

# Visual Assets
folium.Marker(st.session_state.center, tooltip="DOCK ORIGIN", icon=folium.Icon(color='blue', icon='home')).add_to(m)

# Only show Rings/Paths after dock is confirmed
if st.session_state.dock_confirmed:
    for mi in [1, 2, 3]:
        folium.Circle(st.session_state.center, radius=mi*1609.34, color='white', weight=2, fill=False, opacity=0.5).add_to(m)
        p = geodesic(miles=mi).destination(st.session_state.center, 0)
        folium.Marker([p.latitude, p.longitude], icon=DivIcon(html=f'<div style="color:white; font-size:11px; font-weight:bold; background:rgba(0,0,0,0.6); padding:2px; border-radius:3px;">{mi} MILE</div>')).add_to(m)

    for path in st.session_state.vault:
        for seg in path:
            folium.PolyLine(seg['coords'], color=seg['color'], weight=4, opacity=0.8).add_to(m)

    for o in st.session_state.manual_obs:
        folium.Marker(o['coords'], tooltip=f"TIP: {o['msl']}ft", icon=folium.Icon(color='orange', icon='tree', prefix='fa')).add_to(m)

# Click Capture
out = st_folium(m, width=1100, height=650, key=f"map_v{st.session_state.map_v}")

if out and out.get("last_clicked"):
    c_lat, c_lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    
    if not st.session_state.dock_confirmed:
        # Move Dock
        st.session_state.center = [c_lat, c_lon]
        st.session_state.map_v += 1
        st.rerun()
    else:
        # Stage Obstacle
        dist = geodesic(st.session_state.center, (c_lat, c_lon)).feet
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
