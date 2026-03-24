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
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&polygon_geojson=1&zoom=10"
    headers = {'User-Agent': 'DJI_Pro_Planner_Final'}
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
            geolocator = Nominatim(user_agent="dji_pro_planner_search")
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
# Unique map key ensures map resets on move
map_key = f"map_{st.session_state.center_coord[0]}_{st.session_state.center_coord[1]}"

m = folium.Map(location=st.session_state.center_coord, zoom_start=19, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(m)

output = st_folium(m, width=900, height=500, key=map_key)

if output and output.get("last_clicked"):
    new_lat = output["last_clicked"]["lat"]
    new_lon = output["last_clicked"]["lng"]
    new_dist = geodesic(st.session_state.center_coord, (new_lat, new_lon)).feet
    
    if new_dist < 20:
        st.session_state.center_coord = [new_lat, new_lon]
        st.rerun()
    else:
        st.session_state.last_click_dist = new_dist
        st.write(f"**Detected distance:** {int(new_dist)} ft")

# --- 5. CALCULATION & FINAL RANGE MAP ---
st.divider()
st.subheader("Final Range & Jurisdiction Analysis")

rf_points = []
max_ft = 3.5 * 5280
bearings = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}

for d, angle in bearings.items():
    h = st.session_state[f"h_{d}"]
    dist = st.session_state[f"dist_{d}"]
    ant_h = b_h + 15
    calc_d = max_ft if h <= ant_h else ((d_alt - ant_h) * dist) / (h - ant_h)
    final_d = min(max(calc_d, dist), max_ft)
    dest = geodesic(feet=final_d).destination(st.session_state.center_coord, angle)
    rf_points.append({"lat": dest.latitude, "lon": dest.longitude, "name": d, "dist": final_d})

res_map = folium.Map(location=st.session_state.center_coord, zoom_start=13, control_scale=True)

# Add City Limits
city_geo, city_name = get_city_boundary(st.session_state.center_coord[0], st.session_state.center_coord[1])
if city_geo:
    folium.GeoJson(city_geo, name="City Limits",
                   style_function=lambda x: {'color':'red','fill':None,'dashArray':'5,5','weight':3},
                   tooltip=f"{city_name} City Limits").add_to(res_map)

# Add RF Polygon
folium.Polygon([(p['lat'], p['lon']) for p in rf_points], 
               color="blue", weight=2, fill=True, fill_opacity=0.2).add_to(res_map)

# Add Marker & Direction Labels
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(res_map)

for p in rf_points:
    d_mi = p['dist'] / 5280
    label = f"{d_mi:.2f} mi" if d_mi > 0.1 else f"{int(p['dist'])} ft"
    folium.Marker(
        [p['lat'], p['lon']],
        icon=DivIcon(icon_size=(100,20), 
                     html=f'<div style="font-size: 8pt; background: white; border: 1px solid blue; text-align: center; border-radius: 3px; font-weight: bold;">{p["name"]}<br>{label}</div>')
    ).add_to(res_map)

st_folium(res
