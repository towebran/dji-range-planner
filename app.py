import streamlit as st
import folium, requests, random, pandas as pd
from streamlit_folium import st_folium

# --- 1. CORE CONFIG ---
st.set_page_config(layout="wide", page_title="DJI M4TD CloudRF Edition")
API_KEY = "74763-b66b9af71d1b62acb0804e0ba7799450f7f06fbb"

# Ensure all states exist so the map never crashes
if 'center' not in st.session_state: st.session_state.center = [34.0658, -84.6775]
if 'dock_confirmed' not in st.session_state: st.session_state.dock_confirmed = False
if 'overlay_url' not in st.session_state: st.session_state.overlay_url = None
if 'overlay_bounds' not in st.session_state: st.session_state.overlay_bounds = None
if 'map_id' not in st.session_state: st.session_state.map_id = 0

# --- 2. THE STABLE API ENGINE ---
def get_cloudrf_balance():
    """Fetches remaining credits from CloudRF."""
    url = f"https://api.cloudrf.com/balance?key={API_KEY}"
    try:
        res = requests.get(url, timeout=5).json()
        return res.get('balance', 'N/A')
    except: return "Connection Error"

def run_area_scan(lat, lon, h_tx, h_rx):
    """Pings Area API - GPU LiDAR Mode."""
    url = "https://api.cloudrf.com/area"
    payload = {
        "key": API_KEY,
        "transmitter": {"lat": lat, "lon": lon, "alt": h_tx, "frq": 900, "txw": 1.0},
        "receiver": {"alt": h_rx},
        "model": {"pm": 4, "pe": 2}, # ITU-R P.1812 Engine
        "environment": {"clt": "clutter.clt", "elevation": 1},
        "output": {"units": "feet", "rad": 3, "out": 1, "col": "9", "res": 30}
    }
    try:
        res = requests.post(url, json=payload, timeout=30).json()
        return res.get('map'), res.get('bounds'), res.get('kmz')
    except: return None, None, None

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛡️ M4TD Planner v42")
    
    # Restored Balance Check
    bal = get_cloudrf_balance()
    st.metric("CloudRF Credits", bal)
    st.divider()

    if not st.session_state.dock_confirmed:
        st.header("Step 1: Locate Dock")
        query = st.text_input("Address or Lat, Lon", value="Acworth, GA")
        if st.button("📍 Set & Reset Map"):
            if "," in query:
                try:
                    lat, lon = map(float, query.split(","))
                    st.session_state.center = [lat, lon]
                except: st.error("Use format: 34.0, -84.6")
            else:
                res = requests.get(f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={query}&maxLocations=1").json()
                if res['candidates']:
                    loc = res['candidates'][0]['location']
                    st.session_state.center = [loc['y'], loc['x']]
            
            # THE FIX: Increment map_id to force a fresh render on coordinates change
            st.session_state.map_id += 1
            st.rerun()

        h_tx = st.number_input("Antenna Height AGL (ft)", 47.0) # Roof (32) + Mast (15)
        if st.button("✅ Confirm Location"):
            st.session_state.dock_confirmed = True
            st.session_state.h_tx = h_tx
            st.rerun()
    else:
        st.header("Step 2: Analysis")
        drone_agl = st.selectbox("Drone Mission Alt (ft AGL)", [200, 400])
        if st.button("🚀 RUN LIDAR AREA SCAN"):
            with st.spinner("Analyzing Site..."):
                m_url, bnds, k_url = run_area_scan(st.session_state.center[0], st.session_state.center[1], st.session_state.h_tx, drone_agl)
                if m_url:
                    st.session_state.overlay_url, st.session_state.overlay_bounds = m_url, bnds
                    st.session_state.kmz_url = k_url
                else: st.error("Scan Failed.")

        if st.session_state.overlay_url:
            st.link_button("💾 DOWNLOAD KMZ", st.session_state.get('kmz_url', '#'))

        if st.button("🚨 RELOCATE / RESET"):
            st.session_state.dock_confirmed = False
            st.session_state.overlay_url = None
            st.session_state.map_id += 1
            st.rerun()

# --- 4. THE ROBUST MAP ---
# We force the 'center' and 'key' to sync so the map CANNOT stay blank
m = folium.Map(location=st.session_state.center, zoom_start=15, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', 
               attr='Google')

folium.Marker(st.session_state.center, icon=folium.Icon(color='blue')).add_to(m)

if st.session_state.overlay_url and st.session_state.overlay_bounds:
    b = st.session_state.overlay_bounds
    folium.raster_layers.ImageOverlay(
        image=st.session_state.overlay_url,
        bounds=[[b['s'], b['w']], [b['n'], b['e']]],
        opacity=0.6
    ).add_to(m)

# RENDER
st_folium(
    m, 
    center=st.session_state.center,
    key=f"st_map_{st.session_state.map_id}", # Essential for centering logic
    width=1100, height=650
)
