import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from folium.features import DivIcon

# --- 1. SETTINGS ---
st.set_page_config(layout="wide", page_title="DJI M4TD Interactive Planner")

TX_POWER = 33.0     
REQD_SIGNAL = -90.0 
FREQ = 2.4          
D_STEP = 800        

# Initialize State
if 'center' not in st.session_state: st.session_state.center = [33.6644, -84.0113]
if 'vault' not in st.session_state: st.session_state.vault = []
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'last_clicked' not in st.session_state: st.session_state.last_clicked = None
if 'map_v' not in st.session_state: st.session_state.map_v = 1

# --- 2. ENGINES ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=2).json()
        return float(res.get('value', 900.0))
    except: return 900.0

def calculate_rf(dist_ft, h_tx, h_rx, obs_msl):
    dist_km = dist_ft / 3280.84
    fspl = 20 * math.log10(max(0.01, dist_km)) + 20 * math.log10(FREQ) + 92.45
    rssi_base = TX_POWER - fspl
    mid_dist_m = (dist_ft / 2) * 0.3048
    h_clearance = (h_tx + (h_rx - h_tx) * 0.5) - obs_msl
    v = -h_clearance * math.sqrt(2 / (0.125 * mid_dist_m))
    loss = 6.9 + 20 * math.log10(math.sqrt((v-0.1)**2 + 1) + v - 0.1) if v > -0.7 else 0
    final_rssi = rssi_base - loss
    if final_rssi > -80: return "#00FF00", 5, "Solid"    
    if final_rssi > -90: return "#FFA500", 3, "Degraded" 
    return "#FF0000", 2, "Lost"

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛰️ Site Loadout")
    addr = st.text_input("1. Dock Address", "Crooked Creek, GA")
    if st.button("📍 Locate Dock"):
        g_url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={addr}&maxLocations=1"
        res = requests.get(g_url).json()
        if res.get('candidates'):
            loc = res['candidates'][0]['location']
            st.session_state.center = [loc['y'], loc['x']]
            st.session_state.map_v += 1
            st.rerun()

    st.divider()
    st.header("2. Manual Obstacles")
    if st.session_state.last_clicked:
        c_lat, c_lon = st.session_state.last_clicked
        dist = geodesic(st.session_state.center, (c_lat, c_lon)).feet
        
        # Calculate bearing and snap to 16 directions
        dL = math.radians(c_lon - st.session_state.center[1])
        y = math.sin(dL) * math.cos(math.radians(c_lat))
        x = math.cos(math.radians(st.session_state.center[0])) * math.sin(math.radians(c_lat)) - \
            math.sin(math.radians(st.session_state.center[0])) * math.cos(math.radians(c_lat)) * math.cos(dL)
        brng = (math.degrees(math.atan2(y, x)) + 360) % 360
        
        directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        snap_dir = directions[int((brng + 11.25) / 22.5) % 16]
        
        st.write(f"**Target:** {snap_dir} @ {int(dist)}ft")
        obs_msl = st.number_input("Obstacle Top MSL (ft)", value=980.0)
        
        if st.button("➕ Add Obstacle"):
            st.session_state.manual_obs.append({"dist": dist, "msl": obs_msl, "dir": snap_dir, "coords": [c_lat, c_lon]})
            st.session_state.last_clicked = None
            st.success("Added to Loadout")
            st.rerun()

    if st.session_state.manual_obs:
        st.dataframe(pd.DataFrame(st.session_state.manual_obs)[['dir', 'dist', 'msl']], hide_index=True)
        if st.button("🚨 Clear All"):
            st.session_state.manual_obs = []
            st.session_state.vault = []
            st.rerun()

    st.divider()
    ant_h = st.number_input("Antenna AGL (ft)", 35.0)
    drone_h = st.slider("Mission Alt (ft AGL)", 100, 400, 300)
    clutter = st.slider("Global Clutter (ft)", 0, 100, 60)
    
    if st.button("🚀 RUN STRATEGIC SCAN"):
        with st.spinner("Calculating Multi-Path Loss..."):
            dock_g = get_elev_msl(st.session_state.center[0], st.session_state.center[1])
            h_tx, h_rx = dock_g + ant_h + 15, dock_g + drone_h
            
            bearings = {"N":0, "NNE":22.5, "NE":45, "ENE":67.5, "E":90, "ESE":112.5, "SE":135, "SSE":157.5, "S":180, "SSW":202.5, "SW":225, "WSW":247.5, "W":270, "WNW":292.5, "NW":315, "NNW":337.5}
            new_vault = []
            for name, ang in bearings.items():
                path = []
                last_coord = st.session_state.center
                for d in range(D_STEP, 19000, D_STEP):
                    pt = geodesic(feet=d).destination(st.session_state.center, ang)
                    this_coord = [pt.latitude, pt.longitude]
                    obs = get_elev_msl(pt.latitude, pt.longitude) + clutter
                    
                    # Apply Manual MSL Overrides
                    for m in st.session_state.manual_obs:
                        if m['dir'] == name and abs(m['dist'] - d) < (D_STEP/2 + 300):
                            obs = max(obs, m['msl'])
                    
                    color, weight, status = calculate_rf(d, h_tx, h_rx, obs)
                    path.append({"coords": [last_coord, this_coord], "color": color, "weight": weight})
                    last_coord = this_coord
                    if status == "Lost": break
                new_vault.append(path)
            st.session_state.vault = new_vault
            st.rerun()

# --- 4. MAP RENDERING ---
m = folium.Map(location=st.session_state.center, zoom_start=15, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

# Home Point
folium.Marker(st.session_state.center, tooltip="DOCK", icon=folium.Icon(color='blue', icon='home')).add_to(m)

# Draw Scan Results
for path in st.session_state.vault:
    for seg in path:
        folium.PolyLine(seg['coords'], color=seg['color'], weight=seg['weight'], opacity=0.8).add_to(m)

# Draw Manual Markers
for o in st.session_state.manual_obs:
    folium.Marker(o['coords'], tooltip=f"{o['msl']}ft MSL", icon=folium.Icon(color='orange', icon='warning')).add_to(m)

# Handle Map Interaction
out = st_folium(m, width=1100, height=650, key=f"map_v{st.session_state.map_v}")

if out and out.get("last_clicked"):
    st.session_state.last_clicked = [out["last_clicked"]["lat"], out["last_clicked"]["lng"]]
    st.rerun()
