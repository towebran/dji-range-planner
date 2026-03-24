import streamlit as st
import folium
from streamlit_folium import st_folium
from geopy.distance import geodesic
from geopy.geocoders import Nominatim

st.set_page_config(layout="wide", page_title="DJI M4TD Precision Planner")

# --- 1. SESSION STATE (The App's Memory) ---
if 'center_coord' not in st.session_state:
    st.session_state.center_coord = [33.66, -84.01] # Conyers default
if 'obs_data' not in st.session_state:
    # Initialize 8 directions with default 150ft distance and 60ft height
    st.session_state.obs_data = {d: {"dist": 150.0, "h": 60.0} for d in ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]}
if 'last_click_dist' not in st.session_state:
    st.session_state.last_click_dist = 0.0

# --- 2. ADDRESS SEARCH ---
st.title("🛰️ DJI Dock 3 / M4TD Precision Planner")
search_query = st.text_input("Search Address or Hotel Name", "")
if st.button("Fly to Location"):
    try:
        geolocator = Nominatim(user_agent="dji_tool_v7")
        location = geolocator.geocode(search_query)
        if location:
            st.session_state.center_coord = [location.latitude, location.longitude]
            st.rerun()
    except:
        st.error("Search failed. Try a more specific address.")

# --- 3. SIDEBAR (The Controls) ---
with st.sidebar:
    st.header("Site Specs")
    b_h = st.number_input("Building Height (ft)", value=20)
    d_alt = st.slider("Drone Mission Altitude (ft AGL)", 100, 400, 200)
    
    st.divider()
    st.subheader("Obstruction Targeting")
    target_dir = st.selectbox("Assign Clicked Distance To:", list(st.session_state.obs_data.keys()))
    
    if st.button("📌 Save Last Click to " + target_dir):
        st.session_state.obs_data[target_dir]["dist"] = st.session_state.last_click_dist
        st.success(f"Updated {target_dir} to {int(st.session_state.last_click_dist)}ft")

    st.divider()
    # Let user manually tweak heights/distances if needed
    for d in st.session_state.obs_data:
        cols = st.columns([1,1])
        st.session_state.obs_data[d]["h"] = cols[0].number_input(f"{d} Height", value=st.session_state.obs_data[d]["h"], key=f"h_{d}")
        st.session_state.obs_data[d]["dist"] = cols[1].number_input(f"{d} Dist", value=st.session_state.obs_data[d]["dist"], key=f"d_{d}")

# --- 4. THE INTERACTIVE MAP ---
st.write(f"**Step 1:** Click to move the Dock. **Step 2:** Click a tree and hit 'Save' in the sidebar.")

# Satellite Map
m = folium.Map(
    location=st.session_state.center_coord, 
    zoom_start=19, 
    tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', 
    attr='Google'
)
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(m)

# Capture Clicks
output = st_folium(m, width=900, height=500, key="main_map")

if output.get("last_clicked"):
    click_lat = output["last_clicked"]["lat"]
    click_lon = output["last_clicked"]["lng"]
    new_dist = geodesic(st.session_state.center_coord, (click_lat, click_lon)).feet
    
    if new_dist < 20: # If click is right on the red marker
        st.session_state.center_coord = [click_lat, click_lon]
        st.rerun()
    else:
        st.session_state.last_click_dist = new_dist
        st.info(f"Detected distance: {int(new_dist)} ft. Click the 'Save' button in the sidebar to assign this to {target_dir}.")

# --- 5. CALCULATE & DRAW POLYGON ---
rf_points = []
max_ft = 3.5 * 5280
bearings = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}

for d, angle in bearings.items():
    h = st.session_state.obs_data[d]["h"]
    dist = st.session_state.obs_data[d]["dist"]
    ant_h = b_h + 15
    
    if h <= ant_h:
        calc_d = max_ft
    else:
        calc_d = ((d_alt - ant_h) * dist) / (h - ant_h)
    
    final = min(max(calc_d, dist), max_ft)
    dest = geodesic(feet=final).destination(st.session_state.center_coord, angle)
    rf_points.append((dest.latitude, dest.longitude))

# Small display map of the results
st.subheader("Calculated Range")
res_map = folium.Map(location=st.session_state.center_coord, zoom_start=13)
folium.Polygon(rf_points, color="blue", fill=True, opacity=0.3).add_to(res_map)
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(res_map)
st_folium(res_map, width=900, height=400, key="result_map")
