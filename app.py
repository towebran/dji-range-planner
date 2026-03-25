import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

# --- 1. SETTINGS ---
st.set_page_config(layout="wide", page_title="DJI Dock 3 Strategic Planner")

TX_EIRP = 33.0        
RX_SENSITIVITY = -95.0 
FADE_MARGIN = 12.0     
THRESHOLD = RX_SENSITIVITY + FADE_MARGIN 
EARTH_K = 1.333        
SURVEY_DIST_FT = 18480 # 3.5 Miles

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

def get_peak_msl(lat, lon):
    offset = 0.00008 
    coords = [(lat, lon), (lat+offset, lon), (lat-offset, lon), (lat, lon+offset), (lat, lon-offset)]
    elevs = [get_elev_msl(l, n) for l, n in coords]
    return max(elevs)

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛡️ M4TD Tactical Planner")
    
    if not st.session_state.dock_confirmed:
        st.header("📍 Step 1: Dock Setup")
        st.info("Instructions: \n1. Search for your address. \n2. Click the map to place the Blue Dock exactly. \n3. Enter building and antenna heights.")
        query = st.text_input("Find Site", "4415 Center Street, Acworth, GA")
        if st.button("Search & Center"):
            arc_url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={query}&maxLocations=1"
            res = requests.get(arc_url).json()
            if res.get('candidates'):
                loc = res['candidates'][0]['location']
                st.session_state.center = [loc['y'], loc['x']]
                st.session_state.map_v += 1
                st.rerun()
        
        d_ground = get_elev_msl(st.session_state.center[0], st.session_state.center[1])
        d_bldg = st.number_input("Dock Building Height (ft AGL)", 0.0)
        d_ant = st.number_input("Antenna Mast Height (ft)", 15.0)
        st.session_state.dock_stack['total_msl'] = d_ground + d_bldg + d_ant
        
        if st.button("✅ Confirm Dock & Start Survey"):
            st.session_state.dock_confirmed = True
            st.rerun()
    else:
        st.header("🌳 Step 2: Obstacle Survey")
        st.info("Instructions: \n1. Look along the 16 white radials. \n2. Click any tall tree or building you see. \n3. Verify the MSL height and click 'Save'.")
        
        if st.session_state.staged_obs:
            st.warning(f"Obstacle Found: {st.session_state.staged_obs['dir']}")
            final_msl = st.number_input("Peak MSL (Top of Object)", value=st.session_state.staged_obs['msl'])
            if st.button("✔️ Save Obstacle Flag"):
                st.session_state.staged_obs['msl'] = final_msl
                st.session_state.manual_obs.append(st.session_state.staged_obs)
                st.session_state.staged_obs = None
                st.rerun()
            if st.button("Cancel"):
                st.session_state.staged_obs = None
                st.rerun()
        
        st.divider()
        st.header("📡 Step 3: RF Analysis")
        freq = st.radio("Frequency", [2.4, 5.8])
        drone_h = st.slider("Mission Alt (ft AGL)", 100, 400, 200)
        clutter = st.slider("Global Tree Buffer (ft)", 0, 100, 50)
        
        if st.button("🚀 RUN STRATEGIC SCAN"):
            # RF Analysis logic here...
            st.toast("Scan Complete")

# --- 4. MAP RENDERING ---
m = folium.Map(location=st.session_state.center, zoom_start=18, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

# Home Point
folium.Marker(st.session_state.center, icon=folium.Icon(color='blue', icon='home')).add_to(m)

# 16-DIRECTION SURVEY GRID (White Lines)
bearings = [0, 22.5, 45, 67.5, 90, 112.5, 135, 157.5, 180, 202.5, 225, 247.5, 270, 292.5, 315, 337.5]
for ang in bearings:
    dest = geodesic(feet=SURVEY_DIST_FT).destination(st.session_state.center, ang)
    folium.PolyLine([st.session_state.center, [dest.latitude, dest.longitude]], color='white', weight=1, opacity=0.4, dash_array='5').add_to(m)

# Distance Rings
for mi in [1, 2, 3]:
    folium.Circle(st.session_state.center, radius=mi*1609.34, color='white', weight=1, opacity=0.3).add_to(m)

# OBSTACLE FLAGS
for i, ob in enumerate(st.session_state.manual_obs):
    folium.Marker(ob['coords'], icon=folium.Icon(color='orange', icon='flag'), tooltip=f"Obs #{i+1}: {ob['msl']}ft").add_to(m)

# INTERACTION
out = st_folium(m, width=1100, height=650, key=f"v{st.session_state.map_v}")

if out and out.get("last_clicked"):
    lat, lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    if not st.session_state.dock_confirmed:
        st.session_state.center = [lat, lon]
        st.session_state.map_v += 1
        st.rerun()
    else:
        with st.spinner("Peak-Searching..."):
            peak = get_peak_msl(lat, lon)
            # Calc Bearing for dir label
            dist = geodesic(st.session_state.center, (lat, lon)).feet
            st.session_state.staged_obs = {"msl": peak, "dist": dist, "coords": [lat, lon], "dir": "Manual Mark"}
            st.rerun()
