import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from datetime import datetime
import random

# --- 1. SETTINGS ---
st.set_page_config(layout="wide", page_title="DJI M4TD CloudRF Edition")
API_KEY = "74763-b66b9af71d1b62acb0804e0ba7799450f7f06fbb"

# State Initialization
for key, val in {
    'center': [34.0658, -84.6775],
    'dock_confirmed': False,
    'dock_stack': {"b_height": 32.0, "ant_h": 15.0},
    'overlay_url': None,
    'kmz_url': None,
    'overlay_bounds': None,
    'map_key': "cloud_v40"
}.items():
    if key not in st.session_state: st.session_state[key] = val

# --- 2. ENGINES ---
def run_cloud_area_scan(lat, lon, h_tx, h_rx):
    """
    Pings CloudRF Area API. One Credit = Full 360-degree LiDAR Scan.
    """
    url = "https://api.cloudrf.com/area"
    payload = {
        "transmitter": {
            "lat": lat, "lon": lon, "alt": h_tx, 
            "frq": 900, "txw": 1.0 # 900MHz for Free Tier
        },
        "receiver": { "alt": h_rx },
        "environment": { "clt": "clutter.clt", "elevation": 1 },
        "output": {
            "units": "feet", "rad": 3.5, "out": 1, "col": "9", "res": 30
        }
    }
    headers = {"key": API_KEY, "Content-Type": "application/json"}
    
    try:
        res = requests.post(url, json=payload, headers=headers).json()
        # Returns KMZ for download and PNG for map overlay
        return res.get('map'), res.get('bounds'), res.get('kmz')
    except:
        return None, None, None

def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=3).json()
        return float(res.get('value', 900.0))
    except: return 900.0

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛡️ M4TD CloudRF Planner")
    
    if not st.session_state.dock_confirmed:
        st.header("Step 1: Set Site")
        query = st.text_input("Address or Lat, Lon", value="Acworth, GA")
        if st.button("📍 Search"):
            if "," in query:
                lat, lon = map(float, query.split(","))
                st.session_state.center = [lat, lon]
            else:
                res = requests.get(f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={query}&maxLocations=1").json()
                if res['candidates']:
                    loc = res['candidates'][0]['location']
                    st.session_state.center = [loc['y'], loc['x']]
            st.session_state.map_key = f"map_{random.randint(0,999)}"
            st.rerun()
            
        b_h = st.number_input("Building Height (ft)", 32.0)
        a_h = st.number_input("Antenna Mast Height (ft)", 15.0)
        st.session_state.dock_stack = {"h_tx": b_h + a_h}
        if st.button("✅ Confirm Site"):
            st.session_state.dock_confirmed = True; st.rerun()
    else:
        st.header("Step 2: LiDAR Scan")
        drone_agl = st.selectbox("Drone Mission Alt (ft AGL)", [200, 400])
        
        if st.button("🚀 GENERATE HEATMAP"):
            with st.spinner("Processing LiDAR via CloudRF..."):
                map_url, bounds, kmz_url = run_cloud_area_scan(
                    st.session_state.center[0], 
                    st.session_state.center[1], 
                    st.session_state.dock_stack['h_tx'], 
                    drone_agl
                )
                if map_url:
                    st.session_state.overlay_url = map_url
                    st.session_state.overlay_bounds = bounds
                    st.session_state.kmz_url = kmz_url
                else:
                    st.error("Scan Failed. Check API Credits.")

        # --- DOWNLOAD KMZ BUTTON ---
        if st.session_state.kmz_url:
            st.success("Analysis Complete!")
            st.link_button("💾 DOWNLOAD KMZ FOR GOOGLE EARTH", st.session_state.kmz_url)
            st.info("The KMZ includes 3D signal data for your flight team.")

        if st.button("🚨 RESET SITE"):
            st.session_state.dock_confirmed = False
            st.session_state.overlay_url = None
            st.session_state.kmz_url = None
            st.rerun()

# --- 4. MAP RENDERING ---
m = folium.Map(location=st.session_state.center, zoom_start=15, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center, icon=folium.Icon(color='blue', icon='home')).add_to(m)

if st.session_state.overlay_url and st.session_state.overlay_bounds:
    b = st.session_state.overlay_bounds
    folium.raster_layers.ImageOverlay(
        image=st.session_state.overlay_url,
        bounds=[[b['s'], b['w']], [b['n'], b['e']]],
        opacity=0.6,
        zindex=1
    ).add_to(m)

st_folium(m, center=st.session_state.center, key=st.session_state.map_key, width=1100, height=650)
