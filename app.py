import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
import random

# --- 1. SETTINGS ---
st.set_page_config(layout="wide", page_title="DJI M4TD Tactical Planner")
API_KEY = "74763-b66b9af71d1b62acb0804e0ba7799450f7f06fbb"

# State Initialization
for key, val in {
    'center': [34.0658, -84.6775],
    'dock_confirmed': False,
    'overlay_url': None,
    'kmz_url': None,
    'balance': "Unknown",
    'map_key': "v41_map"
}.items():
    if key not in st.session_state: st.session_state[key] = val

# --- 2. CLOUDRF UTILS ---
def check_cloudrf_balance():
    """Checks how many credits you have left."""
    url = "https://api.cloudrf.com/balance"
    headers = {"key": API_KEY}
    try:
        res = requests.get(url, headers=headers).json()
        return res.get('balance', 'Error')
    except: return "Error"

def run_cloud_area_scan(lat, lon, h_tx, h_rx):
    url = "https://api.cloudrf.com/area"
    payload = {
        "transmitter": {
            "lat": lat, "lon": lon, "alt": h_tx, 
            "frq": 900, "txw": 1.0 
        },
        "receiver": { "alt": h_rx },
        "environment": { "clt": "clutter.clt", "elevation": 1 },
        "output": { "units": "feet", "rad": 3.5, "out": 1, "col": "9", "res": 40 } # Lower res = faster/cheaper
    }
    headers = {"key": API_KEY, "Content-Type": "application/json"}
    try:
        res = requests.post(url, json=payload, headers=headers).json()
        # Log balance if provided in the response
        if 'balance' in res: st.session_state.balance = res['balance']
        return res.get('map'), res.get('bounds'), res.get('kmz')
    except: return None, None, None

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛡️ M4TD Tactical Planner")
    
    # CREDIT MONITOR
    if st.button("📊 Check API Balance"):
        st.session_state.balance = check_cloudrf_balance()
    st.write(f"CloudRF Credits: **{st.session_state.balance}**")

    if not st.session_state.dock_confirmed:
        st.header("Step 1: Set Site")
        query = st.text_input("Address or Lat, Lon", value="Acworth, GA")
        if st.button("📍 Jump to Site"):
            # SEARCH LOGIC
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
            
        b_h = st.number_input("Dock Building Height (ft)", 32.0)
        a_h = st.number_input("Antenna Height (ft)", 15.0)
        st.session_state.dock_stack = {"h_tx": b_h + a_h}
        if st.button("✅ Confirm Site"):
            st.session_state.dock_confirmed = True; st.rerun()
    else:
        st.header("Step 2: LiDAR Scan")
        drone_agl = st.selectbox("Drone Mission Alt (ft AGL)", [200, 400])
        
        if st.button("🚀 GENERATE HEATMAP"):
            with st.spinner("Requesting CloudRF Area Scan..."):
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
                    st.success("Heatmap Generated!")
                else:
                    st.error("Scan Failed. Using 'Local Math' fallback instead.")
                    # Fallback trigger could go here

        if st.session_state.kmz_url:
            st.link_button("💾 DOWNLOAD GOOGLE EARTH KMZ", st.session_state.kmz_url)

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
