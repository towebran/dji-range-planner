import streamlit as st
import folium, requests, random, string
import pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DJI M4TD Engineering Report")

# --- 1. STATE ---
dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
if 'vault' not in st.session_state:
    st.session_state.vault = {d: [] for d in dirs}
if 'center_coord' not in st.session_state:
    st.session_state.center_coord = [33.6644, -84.0113]
if 'last_click_dist' not in st.session_state:
    st.session_state.last_click_dist = 0.0
if 'map_v' not in st.session_state:
    st.session_state.map_v = 1

# --- 2. SEARCH ---
def perform_search():
    query = st.session_state.search_box
    if not query: return
    url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={query}&maxLocations=1"
    try:
        res = requests.get(url, timeout=5).json()
        if res.get('candidates'):
            loc = res['candidates'][0]['location']
            st.session_state.center_coord = [loc['y'], loc['x']]
            st.session_state.map_v += 1
    except: st.error("Search Service Busy.")

# --- 3. UI ---
st.title("📑 DJI M4TD Site Survey & Range Report")

with st.sidebar:
    st.header("1. Site Location")
    st.text_input("Search Address:", key="search_box", on_change=perform_search)
    
    st.header("2. Base Station Setup")
    dock_g_msl = st.number_input("Dock Ground MSL (ft)", value=900.0, step=1.0)
    b_h = st.number_input("Building Height (ft)", value=20.0, step=1.0)
    total_ant_msl = dock_g_msl + b_h + 15.0
    st.info(f"Antenna Origin: **{int(total_ant_msl)} ft MSL**")
    
    st.header("3. Mission Specs")
    d_alt_agl = st.slider("Flight Altitude (ft AGL)", 100, 400, 200)
    # Drone MSL is relative to the Takeoff Point (Dock Ground MSL)
    target_drone_msl = dock_g_msl + d_alt_agl
    st.info(f"Drone Target: **{int(target_drone_msl)} ft MSL**")
    
    st.divider()
    st.subheader("4. Add Obstacle")
    target_dir = st.selectbox("Direction:", dirs)
    st.write(f"**Dist from Dock:** {int(st.session_state.last_click_dist)} ft")
    t_top_msl = st.number_input("Obstacle Top MSL (from Google Earth)", value=960.0, step=1.0)
    
    if st.button(f"➕ Add Obstacle to {target_dir}"):
        obs = {"dist": round(st.session_state.last_click_dist, 1), "t_msl": t_top_msl}
        st.session_state.vault[target_dir].append(obs)
        st.success(f"Added to {target_dir}!")

    if st.button("🚨 RESET ENTIRE SURVEY"):
        st.session_state.vault = {d: [] for d in dirs}
        st.rerun()

# --- 4. SATELLITE SURVEY ---
m_k = f"sat_v{st.session_state.map_v}"
m = folium.Map(location=st.session_state.center_coord, zoom_start=19, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red', tooltip="DOCK")).add_to(m)

out = st_folium(m, width=900, height=450, key=m_k)

if out and out.get("last_clicked"):
    nl, no = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    nd = geodesic(st.session_state.center_coord, (nl, no)).feet
    if nd < 25:
        st.session_state.center_coord = [nl, no]
        st.session_state.map_v += 1
        st.rerun()
    else:
        st.session_state.last_click_dist = nd

# --- 5. TOPOGRAPHIC LOS CALCULATION ---
rf_pts = []
table_data = []
max_ft = 3.5 * 5280

for d, ang in {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}.items():
    limits = [max_ft]
    limiting_factor = "Clear (3.5mi)"
    
    for obs in st.session_state.vault[d]:
        dist = obs["dist"]
        obs_top_msl = obs["t_msl"]
        
        # If the obstacle top is higher than our antenna origin...
        if obs_top_msl > total_ant_msl:
            # GEOMETRIC SLOPE: Ratio of height gain to distance
            ratio = (target_drone_msl - total_ant_msl) / (obs_top_msl - total_ant_msl)
            limit = ratio * dist
            # Range cannot be less than the distance to the tree itself
            limit = max(limit, dist)
        else:
            limit = max_ft
            
        limits.append(limit)
        if limit < max_ft:
            limiting_factor = f"Obj at {int(dist)}ft / {int(obs_top_msl)}ft MSL"
    
    final_d = min(limits)
    dest = geodesic(feet=final_d).destination(st.session_state.center_coord, ang)
    rf_pts.append({"lat": dest.latitude, "lon": dest.longitude, "name": d, "dist": final_d})
    table_data.append([d, limiting_factor, f"{(final_d/5280):.2f} miles"])

# --- 6. DISPLAY RESULTS ---
st.divider()
st.subheader("Final RF Range Analysis")

res_map = folium.Map(location=st.session_state.center_coord, zoom_start=13)
folium.Polygon([(p['lat'], p['lon']) for p in rf_pts], color="blue", fill=True, opacity=0.2).add_to(res_map)
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(res_map)

for p in rf_pts:
    lbl = f"{(p['dist']/5280):.2f} mi"
    folium.Marker([p['lat'], p['lon']], icon=DivIcon(icon_size=(100,40), icon_anchor=(50,20),
        html=f'<div style="background:white; border:2px solid blue; border-radius:5px; color:black; font-weight:bold; font-size:10px; text-align:center; width:70px; padding:2px;">{p["name"]}<br>{lbl}</div>')).add_to(res_map)

st_folium(res_map, width=1100, height=550, key=f"res_{st.session_state.map_v}")

# --- 7. SUMMARY TABLE ---
st.subheader("Site Survey Summary Table")
df = pd.DataFrame(table_data, columns=["Direction", "Limiting Obstacle / MSL", "Calculated Range"])
st.table(df)

st.write("---")
st.write("🖨️ **Print Instructions:** Press **Ctrl + P** (or Cmd+P) to save this page as a PDF Report.")
