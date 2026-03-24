import streamlit as st
import folium
from streamlit_folium import st_folium
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import requests

st.set_page_config(layout="wide", page_title="DJI M4TD Site Planner")

# --- INITIALIZE STATE ---
if 'center' not in st.session_state:
    st.session_state.center = [33.66, -84.01] # Default Conyers
if 'obs_data' not in st.session_state:
    st.session_state.obs_data = {d: {"dist": 150.0, "h": 60.0} for d in ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]}

# --- HEADER & SEARCH ---
st.title("🛰️ DJI Dock 3 / M4TD Installation Planner")

search_query = st.text_input("Search Address", placeholder="e.g. 1300 Dogwood Dr SW, Conyers, GA")
if st.button("Fly to Address"):
    geolocator = Nominatim(user_agent="dji_planner")
    location = geolocator.geocode(search_query)
    if location:
        st.session_state.center = [location.latitude, location.longitude]
        st.success(f"Found: {location.address}")
    else:
        st.error("Address not found. Please be more specific.")

# --- SIDEBAR: DIMENSIONS & DATA ---
with st.sidebar:
    st.header("Site Specs")
    b_h = st.number_input("Building Height (ft)", value=20)
    d_alt = st.slider("Flight Altitude (ft AGL)", 100, 400, 200)
    target_dir = st.selectbox("Select Direction to Map Click", list(st.session_state.obs_data.keys()))
    
    st.divider()
    st.subheader("Obstruction Data")
    for d in st.session_state.obs_data:
        col1, col2 = st.columns(2)
        st.session_state.obs_data[d]["dist"] = col1.number_input(f"{d} Dist", value=st.session_state.obs_data[d]["dist"], key=f"dist_{d}")
        st.session_state.obs_data[d]["h"] = col2.number_input(f"{d} H", value=st.session_state.obs_data[d]["h"], key=f"h_{d}")

# --- INTERACTIVE MAP ---
st.info(f"Currently Mapping: **{target_dir}**. Click a tree/building on the map to set its distance.")

# Satellite Map Setup
m = folium.Map(
    location=st.session_state.center, 
    zoom_start=19, 
    tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', 
    attr='Google Satellite'
)

# Current Dock Marker
folium.Marker(st.session_state.center, tooltip="DJI DOCK 3", icon=folium.Icon(color='red', icon='tower-broadcast', prefix='fa')).add_to(m)

# Process Clicks
map_output = st_folium(m, width="100%", height=500)

if map_output.get("last_clicked"):
    click = map_output["last_clicked"]
    click_coord = (click["lat"], click["lng"])
    
    # Calculate distance from center
    new_dist = geodesic(st.session_state.center, click_coord).feet
    
    if new_dist < 30: # If click is right on top of dock, move the dock center
        st.session_state.center = [click["lat"], click["lng"]]
        st.rerun()
    else:
        # Assign clicked distance to the selected direction
        st.session_state.obs_data[target_dir]["dist"] = round(new_dist, 1)
        st.rerun()

# --- CALCULATE FINAL LOS ---
rf_points = []
max_ft = 3.5 * 5280
bearings = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}

for d, angle in bearings.items():
    h = st.session_state.obs_data[d]["h"]
    dist = st.session_state.obs_data[d]["dist"]
    ant_total = b_h + 15
    
    if h <= ant_total:
        calc_dist = max_ft
    else:
        calc_dist = ((d_alt - ant_total) * dist) / (h - ant_total)
    
    final = min(max(calc_dist, dist), max_ft)
    dest = geodesic(feet=final).destination(st.session_state.center, angle)
    rf_points.append((dest.latitude, dest.longitude))

# --- FINAL COVERAGE DISPLAY ---
st.subheader("Predicted 3.5-Mile LOS Coverage")
res_map = folium.Map(location=st.session_state.center, zoom_start=13, control_scale=True)
folium.Polygon(rf_points, color="blue", fill=True, opacity=0.3, tooltip="Safe Flight Zone").add_to(res_map)
folium.Marker(st.session_state.center, icon=folium.Icon(color='red')).add_to(res_map)
st_folium(res_map, width="100%", height=400)
