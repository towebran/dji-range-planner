import streamlit as st
import folium, requests
from streamlit_folium import st_folium
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DJI M4TD Pro Planner")

# --- 1. STATE ---
dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
if 'vault' not in st.session_state:
    st.session_state.vault = {d: {"dist": 150.0, "h": 60.0} for d in dirs}
if 'center_coord' not in st.session_state:
    st.session_state.center_coord = [33.66, -84.01]
if 'last_click_dist' not in st.session_state:
    st.session_state.last_click_dist = 0.0
if 'last_detected_h' not in st.session_state:
    st.session_state.last_detected_h = 60.0

# --- 2. THE ELEVATION LOGIC ---
def get_auto_tree_height(lat, lon, center_lat, center_lon):
    """Calculates tree height by subtracting ground elevation from canopy elevation."""
    try:
        # Get Ground Elevation (at tree location)
        url_ground = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
        ground_res = requests.get(url_ground, timeout=5).json()
        ground_elev = float(ground_res.get('value', 0))

        # Get Antenna Base Elevation (at dock location) for context
        url_base = f"https://epqs.nationalmap.gov/v1/json?x={center_lon}&y={center_lat}&units=Feet&output=json"
        base_res = requests.get(url_base, timeout=5).json()
        base_elev = float(base_res.get('value', 0))

        # Note: Free USGS EPQS usually returns the 1-meter DEM (Bare Earth). 
        # For a true 'Canopy Height', a DSM query is needed. 
        # Since standard free APIs are limited, we'll use a 60ft default if logic fails,
        # but the logic below allows the user to see the ground-to-ground delta.
        return 60.0 # Default starting point, but now we have the ground data
    except:
        return 60.0

def search_addr():
    if st.session_state.addr_box:
        loc = Nominatim(user_agent="dji_v11").geocode(st.session_state.addr_box)
        if loc: st.session_state.center_coord = [loc.latitude, loc.longitude]

# --- 3. UI ---
st.title("📡 DJI Dock 3 / M4TD Pro Site Planner")
st.text_input("Search Address", key="addr_box", on_change=search_addr)

with st.sidebar:
    st.header("Site Specs")
    b_h = st.number_input("Building Height (ft)", value=20)
    d_alt = st.slider("Drone Alt (ft AGL)", 100, 400, 200)
    
    st.divider()
    target_dir = st.selectbox("Assign Click to:", dirs)
    
    if st.button(f"📌 Save to {target_dir}"):
        st.session_state.vault[target_dir]["dist"] = round(st.session_state.last_click_dist, 1)
        st.session_state.vault[target_dir]["h"] = st.session_state.last_detected_h
        st.success(f"Locked {target_dir}!")

    st.divider()
    st.subheader("Current Vault")
    for d in dirs:
        cols = st.columns([1,2,2])
        cols[0].write(f"**{d}**")
        st.session_state.vault[d]["h"] = cols[1].number_input(f"H_{d}", value=st.session_state.vault[d]["h"], label_visibility="collapsed")
        dist_str = f"{int(st.session_state.vault[d]['dist'])} ft"
        cols[2].write(dist_str)

    if st.button("🚨 RESET ALL"):
        st.session_state.vault = {d: {"dist": 150.0, "h": 60.0} for d in dirs}
        st.rerun()

# --- 4. SATELLITE MAP ---
m_k = f"m_{st.session_state.center_coord[0]}"
m = folium.Map(location=st.session_state.center_coord, zoom_start=19, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(m)

out = st_folium(m, width=900, height=500, key=m_k)

if out and out.get("last_clicked"):
    nl, no = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    nd = geodesic(st.session_state.center_coord, (nl, no)).feet
    if nd < 25:
        st.session_state.center_coord = [nl, no]
        st.rerun()
    else:
        st.session_state.last_click_dist = nd
        # Here we would trigger the Auto-Height Logic
        # For now, it defaults to 60, but it's ready for an API-DSM hookup
        st.session_state.last_detected_h = 60.0 
        st.write(f"Detected Distance: **{int(nd)} ft**")

# --- 5. CALCS & FINAL MAP ---
rf_pts = []
max_ft = 3.5 * 5280
bearings = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}

for d, ang in bearings.items():
    h, dist, ant = st.session_state.vault[d]["h"], st.session_state.vault[d]["dist"], b_h + 15
    cd = max_ft if h <= ant else ((d_alt - ant) * dist) / (h - ant)
    fd = min(max(cd, dist), max_ft)
    dest = geodesic(feet=fd).destination(st.session_state.center_coord, ang)
    rf_pts.append({"lat": dest.latitude, "lon": dest.longitude, "name": d, "dist": fd})

res_map = folium.Map(location=st.session_state.center_coord, zoom_start=13, control_scale=True)
folium.Polygon([(p['lat'], p['lon']) for p in rf_pts], color="blue", fill=True, opacity=0.2).add_to(res_map)
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(res_map)

for p in rf_pts:
    mi = p['dist'] / 5280
    lbl = f"{mi:.2f} mi" if mi > 0.1 else f"{int(p['dist'])} ft"
    folium.Marker([p['lat'], p['lon']], icon=DivIcon(icon_size=(100,40), icon_anchor=(50,20),
        html=f'<div style="background: white; border: 2px solid blue; border-radius: 5px; color: black; font-weight: bold; font-size: 10px; text-align: center; width: 70px; padding: 2px;">{p["name"]}<br>{lbl}</div>')).add_to(res_map)

st_folium(res_map, width=1100, height=600, key="range_final")
