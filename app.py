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

# Directions setup
directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
for d in directions:
    if f"dist_{d}" not in st.session_state:
        st.session_state[f"dist_{d}"] = 150.0
    if f"h_{d}" not in st.session_state:
        st.session_state[f"h_{d}"] = 60.0

# --- 2. ADDRESS SEARCH LOGIC (FIXED) ---
def search_address():
    if st.session_state.addr_input:
        try:
            geolocator = Nominatim(user_agent="dji_planner_final")
            location = geolocator.geocode(st.session_state.addr_input)
            if location:
                st.session_state.center_coord = [location.latitude, location.longitude]
                # Clear the search box after success
                st.toast(f"Flying to: {location.address}")
            else:
                st.error("Address not found.")
        except:
            st.error("Search service temporarily unavailable.")

st.title("🛰️ DJI Dock 3 / M4TD Precision Planner")

# Address search with 'on_change' or manual button
st.text_input("Search Address", key="addr_input", on_change=search_address)
st.button("Fly to Location", on_click=search_address)

# --- 3. SIDEBAR CONTROLS ---
with st.sidebar:
    st.header("Site Specs")
    b_h = st.number_input("Building Height (ft)", value=20)
    d_alt = st.slider("Drone Mission Altitude (ft AGL)", 100, 400, 200)
    
    st.divider()
    st.subheader("Obstruction Targeting")
    target_dir = st.selectbox("Select Direction:", directions)
    
    if st.button(f"📌 Save Click to {target_dir}"):
        st.session_state[f"dist_{target_dir}"] = round(st.session_state.last_click_dist, 1)
        st.rerun()

    st.divider()
    for d in directions:
        st.write(f"**Direction: {d}**")
        cols = st.columns(2)
        cols[0].number_input("Height", value=60.0, key=f"h_{d}")
        cols[1].number_input("Dist", key=f"dist_{d}")

# --- 4. INTERACTIVE SATELLITE MAP ---
st.info(f"Targeting: **{target_dir}** | Click a tree on the map, then hit 'Save' in the sidebar.")

# Unique key using center coords ensures the map actually moves when the address changes
map_key = f"map_{st.session_state.center_coord[0]}_{st.session_state.center_coord[1]}"

m = folium.Map(
    location=st.session_state.center_coord, 
    zoom_start=19, 
    tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', 
    attr='Google'
)
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(m)

output = st_folium(m, width=900, height=500, key=map_key)

if output.get("last_clicked"):
    click_lat = output["last_clicked"]["lat"]
    click_lon = output["last_clicked"]["lng"]
    new_dist = geodesic(st.session_state.center_coord, (click_lat, click_lon)).feet
    
    if new_dist < 20: 
        st.session_state.center_coord = [click_lat, click_lon]
        st.rerun()
    else:
        st.session_state.last_click_dist = new_dist
        st.write(f"**Detected distance:** {int(new_dist)} ft. Click 'Save' in sidebar.")

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

st.subheader("Final 3.5-Mile LOS Range")
res_map = folium.Map(location=st.session_state.center_coord, zoom_start=13, control_scale=True)
folium.Polygon(rf_points, color="blue", fill=True, opacity=0.3).add_to(res_map)
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(res_map)
st_folium(res_map, width=900, height=400, key="range_result")
