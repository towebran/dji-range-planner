import streamlit as st
import folium
from streamlit_folium import st_folium
from geopy.distance import geodesic
from geopy.geocoders import Nominatim

st.set_page_config(layout="wide", page_title="DJI M4TD Precision Planner")

# --- 1. INITIALIZE SESSION STATE ---
if 'center_coord' not in st.session_state:
    st.session_state.center_coord = [33.66, -84.01] # Conyers default
if 'last_click_dist' not in st.session_state:
    st.session_state.last_click_dist = 0.0

# Initialize distances and heights if not present
directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
for d in directions:
    if f"dist_{d}" not in st.session_state:
        st.session_state[f"dist_{d}"] = 150.0
    if f"h_{d}" not in st.session_state:
        st.session_state[f"h_{d}"] = 60.0

# --- 2. ADDRESS SEARCH ---
st.title("🛰️ DJI Dock 3 / M4TD Precision Planner")
# Updated search label per your request
search_query = st.text_input("Search Address", "")
if st.button("Fly to Location"):
    try:
        geolocator = Nominatim(user_agent="dji_installer_pro")
        location = geolocator.geocode(search_query)
        if location:
            st.session_state.center_coord = [location.latitude, location.longitude]
            st.rerun()
    except:
        st.error("Address not found.")

# --- 3. SIDEBAR CONTROLS ---
with st.sidebar:
    st.header("Site Specs")
    b_h = st.number_input("Building Height (ft)", value=20)
    d_alt = st.slider("Drone Mission Altitude (ft AGL)", 100, 400, 200)
    
    st.divider()
    st.subheader("Obstruction Targeting")
    target_dir = st.selectbox("Select Direction:", directions)
    
    # This button now explicitly forces the session state to update
    if st.button(f"📌 Save Click to {target_dir}"):
        st.session_state[f"dist_{target_dir}"] = round(st.session_state.last_click_dist, 1)
        st.success(f"Updated {target_dir} Distance!")
        st.rerun() # Force UI refresh to show the new number

    st.divider()
    # The 'key' parameter here is what makes the auto-update work
    for d in directions:
        st.write(f"**Direction: {d}**")
        cols = st.columns(2)
        cols[0].number_input("Height", value=60.0, key=f"h_{d}")
        cols[1].number_input("Dist", key=f"dist_{d}")

# --- 4. INTERACTIVE SATELLITE MAP ---
st.write(f"Targeting: **{target_dir}** | Click a tree on the map, then hit the green 'Save' button.")

m = folium.Map(
    location=st.session_state.center_coord, 
    zoom_start=19, 
    tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', 
    attr='Google'
)
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(m)

# Capture clicks - unique key ensures state persistence
output = st_folium(m, width=900, height=500, key="survey_map")

if output.get("last_clicked"):
    click_lat = output["last_clicked"]["lat"]
    click_lon = output["last_clicked"]["lng"]
    new_dist = geodesic(st.session_state.center_coord, (click_lat, click_lon)).feet
    
    if new_dist < 25: # Click near dock moves the center
        st.session_state.center_coord = [click_lat, click_lon]
        st.rerun()
    else:
        st.session_state.last_click_dist = new_dist
        st.info(f"Last Click: {int(new_dist)} ft. Use 'Save' button in sidebar to assign this to {target_dir}.")

# --- 5. CALCULATION & RANGE MAP ---
rf_points = []
max_ft = 3.5 * 5280
bearings = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}

for d, angle in bearings.items():
    h = st.session_state[f"h_{d}"]
    dist = st.session_state[f"dist_{d}"]
    ant_h = b_h + 15
    
    if h <= ant_h:
        calc_d = max_ft
    else:
        calc_d = ((d_alt - ant_h) * dist) / (h - ant_h)
    
    final = min(max(calc_d, dist), max_ft)
    dest = geodesic(feet=final).destination(st.session_state.center_coord, angle)
    rf_points.append((dest.latitude, dest.longitude))

st.subheader("Final LOS Range")
res_map = folium.Map(location=st.session_state.center_coord, zoom_start=13, control_scale=True)
folium.Polygon(rf_points, color="blue", fill=True, opacity=0.3).add_to(res_map)
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(res_map)
st_folium(res_map, width=900, height=400, key="range_result_map")
