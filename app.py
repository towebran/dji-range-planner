import streamlit as st
import folium
import requests
from streamlit_folium import st_folium
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DJI M4TD Pro Planner")

# --- 1. INITIALIZE SESSION STATE ---
if 'center_coord' not in st.session_state:
    st.session_state.center_coord = [33.66, -84.01] # Conyers default
if 'last_click_dist' not in st.session_state:
    st.session_state.last_click_dist = 0.0

directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
for d in directions:
    if f"dist_{d}" not in st.session_state:
        st.session_state[f"dist_{d}"] = 150.0
    if f"h_{d}" not in st.session_state:
        st.session_state[f"h_{d}"] = 60.0

# --- 2. UTILITY FUNCTIONS ---
def get_city_boundary(lat, lon):
    """Fetches the city boundary polygon based on the current center coordinates."""
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&polygon_geojson=1&zoom=10"
    headers = {'User-Agent': 'DJI_Pro_Planner_v8'}
    try:
        res = requests.get(url, headers=headers).json()
        if 'geojson' in res:
            return res['geojson'], res.get('address', {}).get('city', 'Jurisdiction')
    except:
        return None, None
    return None, None

def search_address():
    if st.session_state.addr_input:
        try:
            geolocator = Nominatim(user_agent="dji_pro_planner")
            location = geolocator.geocode(st.session_state.addr_input)
            if location:
                st.session_state.center_coord = [location.latitude, location.longitude]
                st.toast(f"Flying to: {location.address}")
        except:
            st.error("Search failed.")

# --- 3. UI LAYOUT ---
st.title("📡 DJI Dock 3 / M4TD Pro Site Planner")
st.text_input("Search Address", key="addr_input", on_change=search_address)

with st.sidebar:
    st.header("Site Specs")
    b_h = st.number_input("Building Height (ft)", value=20)
    d_alt = st.slider("Drone Altitude (ft AGL)", 100, 400, 200)
    
    st.divider()
    target_dir = st.selectbox("Assign Click to Direction:", directions)
    if st.button(f"📌 Save Click to {target_dir}"):
        st.session_state[f"dist_{target_dir}"] = round(st.session_state.last_click_dist, 1)
        st.rerun()

    st.divider()
    for d in directions:
        st.write(f"**{d}**")
        cols = st.columns(2)
        cols[0].number_input("H", value=60.0, key=f"h_{d}")
        cols[1].number_input("Dist", key=f"dist_{d}")

# --- 4. INTERACTIVE SATELLITE MAP ---
st.info(f"Targeting: **{target_dir}** | Click tree, then hit 'Save'. Click near center to move Dock.")
map_key = f"map_{st.session_state.center_coord[0]}_{st.session_state.center_coord[1]}"

m = folium.Map(location=st.session_state.center_coord, zoom_start=19, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(m)

output = st_folium(m, width=900, height=500, key=map_key)

if output.get("last_
