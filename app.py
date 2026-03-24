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

# --- 3. UI TOP SECTION ---
st.title("🛰️ DJI M4TD Site Survey & Range Planner")

# --- INSTRUCTIONS BOX ---
with st.expander("📖 HOW TO USE THIS TOOL (Click to Expand)", expanded=True):
    st.markdown("""
    ### 🛠️ Step-by-Step Instructions
    1.  **Locate Site:** Use the **Search Address** box in the sidebar to find your installation site.
    2.  **Set Dock Elevation:** Enter the **Ground MSL** of the building and the **Building Height**. The app adds 15' for the antenna mast automatically.
    3.  **Identify Obstacles:** * Find a tree or building on the Satellite Map. 
        * **Click it.** The distance from the Dock will appear in the sidebar.
        * Use Google Earth to find the **Top MSL** of that obstacle.
        * Select the **Direction** (e.g., North), enter the MSL, and click **➕ Add Obstacle**.
    4.  **Repeat:** You can add multiple obstacles in every direction. The app always calculates range based on the *worst-case* obstruction.
    5.  **Generate Report:** Review the Range Map and Summary Table at the bottom. Press **Ctrl+P** to save as a PDF.
    """)

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("📋 1. Site Information")
    site_name = st.text_input("Customer / Site Name", placeholder="e.g. Conyers Logistics Hub")
    site_id = st.text_input("Site ID / Project #", placeholder="e.g. Proj-2024-001")
    
    st.header("📍 2. Location Search")
    st.text_input("Search Address:", key="search_box", on_change=perform_search)
    
    st.header("🏗️ 3. Base Station Setup")
    dock_g_msl = st.number_input("Dock Ground MSL (ft)", value=900.0, step=1.0)
    b_h = st.number_input("Building Height (ft)", value=20.0, step=1.0)
    total_ant_msl = dock_g_msl + b_h + 15.0
    st.caption(f"Antenna Origin: {int(total_ant_msl)} ft MSL")
    
    st.header("🚀 4. Mission Specs")
    d_alt_agl = st.slider("Flight Altitude (ft AGL)", 100, 400, 200)
    target_drone_msl = dock_g_msl + d_alt_agl
    st.caption(f"Drone Target: {int(target_drone_msl)} ft MSL")
    
    st.divider()
    st.subheader("🌲 5. Add Obstacle")
    target_dir = st.selectbox("Assign to Direction:", dirs)
    st.write(f"**Selected Dist:** {int(st.session_state.last_click_dist)} ft")
    t_top_msl = st.number_input("Obstacle Top MSL", value=960.0, step=1.0)
    
    if st.button(f"➕ Add to {target_dir}"):
        obs = {"dist": round(st.session_state.last_click_dist, 1), "t_msl": t_top_msl}
        st.session_state.vault[target_dir].append(obs)
        st.success(f"Added to {target_dir}!")

    if st.button("🚨 RESET ENTIRE SURVEY"):
        st.session_state.vault = {d: [] for d in dirs}
        st.rerun()

# --- 5. SATELLITE SURVEY MAP ---
st.subheader(f"Satellite Survey: {site_name if site_name else 'Active Site'}")
m_k = f"sat_v{st.session_state.map_v}"
m = folium.Map(location=st.session_state.center_coord, zoom_start=19, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red', icon='tower-broadcast', prefix='fa')).add_to(m)

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

# --- 6. CALCULATIONS ---
rf_pts = []
table_data = []
max_ft = 3.5 * 5280

for d, ang in {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}.items():
    limits = [max_ft]
    limiting_factor = "Clear (3.5mi)"
    
    for obs in st.session_state.vault[d]:
        dist, obs_top_msl = obs["dist"], obs["t_msl"]
        if obs_top_msl > total_ant_msl:
            ratio = (target_drone_msl - total_ant_msl) / (obs_top_msl - total_ant_msl)
            limit = ratio * dist
            limit = max(limit, dist)
        else:
            limit = max_ft
        limits.append(limit)
        if limit < max_ft:
            limiting_factor = f"Obj @ {int(dist)}ft ({int(obs_top_msl)}' MSL)"
    
    final_d = min(limits)
    dest = geodesic(feet=final_d).destination(st.session_state.center_coord, ang)
    rf_pts.append({"lat": dest.latitude, "lon": dest.longitude, "name": d, "dist": final_d})
    table_data.append([d, limiting_factor, f"{(final_d/5280):.2f} miles"])

# --- 7. FINAL ANALYSIS & TABLE ---
st.divider()
st.subheader("📊 Range Analysis Report")
if site_id: st.caption(f"Project ID: {site_id}")

res_map = folium.Map(location=st.session_state.center_coord, zoom_start=13)
folium.Polygon([(p['lat'], p['lon']) for p in rf_pts], color="blue", fill=True, opacity=0.2).add_to(res_map)
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(res_map)

for p in rf_pts:
    lbl = f"{(p['dist']/5280):.2f} mi"
    folium.Marker([p['lat'], p['lon']], icon=DivIcon(icon_size=(100,40), icon_anchor=(50,20),
        html=f'<div style="background:white; border:2px solid blue; border-radius:5px; color:black; font-weight:bold; font-size:10px; text-align:center; width:70px; padding:2px;">{p["name"]}<br>{lbl}</div>')).add_to(res_map)

st_folium(res_map, width=1100, height=550, key=f"res_{st.session_state.map_v}")

st.subheader("📋 Engineering Summary Table")
df = pd.DataFrame(table_data, columns=["Direction", "Worst-Case Obstacle", "Calculated Range"])
st.table(df)

st.write("---")
st.info("💡 **Print Instructions:** Press **Ctrl + P** to save this survey as a PDF. Ensure 'Background Graphics' is checked in your browser print settings.")
