import streamlit as st
import folium, requests, pandas as pd
from streamlit_folium import st_folium
import random

# --- 1. SETTINGS ---
st.set_page_config(layout="wide", page_title="DJI M4TD CloudRF Edition")

# YOUR KEY IS NOW INJECTED DIRECTLY INTO THE DATA PAYLOAD
API_KEY = "74763-b66b9af71d1b62acb0804e0ba7799450f7f06fbb"

if 'center' not in st.session_state: st.session_state.center = [34.0658, -84.6775]
if 'dock_confirmed' not in st.session_state: st.session_state.dock_confirmed = False
if 'overlay_url' not in st.session_state: st.session_state.overlay_url = None
if 'overlay_bounds' not in st.session_state: st.session_state.overlay_bounds = None
if 'map_key' not in st.session_state: st.session_state.map_key = "cloud_v41"

# --- 2. THE UPDATED API ENGINE ---
def run_cloud_area_scan(lat, lon, h_tx, h_rx):
    """
    Simplified API call to ensure Free Tier compliance.
    """
    url = "https://api.cloudrf.com/area"
    
    # We pass the 'key' inside the JSON data itself
    payload = {
        "key": API_KEY,
        "transmitter": {
            "lat": lat, 
            "lon": lon, 
            "alt": h_tx, 
            "frq": 900,  # REQUIRED for Free Tier
            "txw": 1.0, 
            "nam": "DJI_Dock_3"
        },
        "receiver": { 
            "alt": h_rx 
        },
        "environment": {
            "clt": "clutter.clt", 
            "elevation": 1 
        },
        "output": {
            "units": "feet",
            "rad": 3.0,   # Reduced to 3 miles to stay safe on credits
            "out": 1,     # PNG Overlay
            "col": "9",   # dBm palette
            "res": 30     # Fixed 30m resolution for Free Tier
        }
    }
    
    try:
        # No special headers needed except Content-Type
        response = requests.post(url, json=payload, timeout=20)
        res = response.json()
        
        # Check if the API actually gave us a map
        if 'map' in res:
            return res.get('map'), res.get('bounds'), res.get('kmz')
        else:
            # Print the error to Streamlit so we can see why it's failing
            st.sidebar.error(f"CloudRF Says: {res.get('error', 'Unknown Error')}")
            return None, None, None
    except Exception as e:
        st.sidebar.error(f"Connection Error: {e}")
        return None, None, None

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛡️ M4TD CloudRF Planner")
    
    if not st.session_state.dock_confirmed:
        st.header("Step 1: Setup")
        query = st.text_input("Site Search", value="Acworth, GA")
        if st.button("📍 Jump to Site"):
            # Simple Geocode
            res = requests.get(f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={query}&maxLocations=1").json()
            if res['candidates']:
                loc = res['candidates'][0]['location']
                st.session_state.center = [loc['y'], loc['x']]
                st.session_state.map_key = f"map_{random.randint(0,999)}"
                st.rerun()
        
        b_h = st.number_input("Building Height (ft)", 32.0)
        a_h = st.number_input("Antenna Height (ft)", 15.0)
        st.session_state.h_tx = b_h + a_h
        
        if st.button("✅ Confirm Site"):
            st.session_state.dock_confirmed = True
            st.rerun()
    else:
        st.header("Step 2: LiDAR Area Scan")
        drone_agl = st.selectbox("Drone Alt (ft AGL)", [200, 400])
        
        if st.button("🚀 RUN 360° LIDAR SCAN"):
            with st.spinner("Crunching LiDAR (1 Credit)..."):
                m_url, bnds, k_url = run_cloud_area_scan(
                    st.session_state.center[0], 
                    st.session_state.center[1], 
                    st.session_state.h_tx, 
                    drone_agl
                )
                if m_url:
                    st.session_state.overlay_url = m_url
                    st.session_state.overlay_bounds = bnds
                    st.session_state.kmz_url = k_url
                    st.success("Success!")
        
        if st.session_state.overlay_url:
            st.link_button("💾 DOWNLOAD KMZ", st.session_state.get('kmz_url', '#'))

        if st.button("🚨 RESET"):
            st.session_state.dock_confirmed = False
            st.session_state.overlay_url = None
            st.rerun()

# --- 4. MAP ---
m = folium.Map(location=st.session_state.center, zoom_start=15, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center, icon=folium.Icon(color='blue')).add_to(m)

if st.session_state.overlay_url and st.session_state.overlay_bounds:
    b = st.session_state.overlay_bounds
    folium.raster_layers.ImageOverlay(
        image=st.session_state.overlay_url,
        bounds=[[b['s'], b['w']], [b['n'], b['e']]],
        opacity=0.6
    ).add_to(m)

st_folium(m, center=st.session_state.center, key=st.session_state.map_key, width=1100, height=650)
