import streamlit as st
import folium, requests, random, string, io
import pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DJI M4TD Engineering Report")

# --- 1. SESSION STATE ---
dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
if 'vault' not in st.session_state:
    st.session_state.vault = {d: [] for d in dirs}
if 'center_coord' not in st.session_state:
    st.session_state.center_coord = [33.6644, -84.0113]
if 'last_click_dist' not in st.session_state:
    st.session_state.last_click_dist = 0.0
if 'map_v' not in st.session_state:
    st.session_state.map_v = 1

# --- 2. IMPROVED SEARCH ---
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
            st.toast("Location Updated!")
    except: st.error("Search Service Busy.")

# --- 3. UI TOP ---
st.title("🛰️ DJI M4TD Site Survey & Range Planner")

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("📋 Site Information")
    site_name = st.text_input("Site Name", placeholder="e.g. Conyers Hub")
    st.text_input("Search Address:", key="search_box", on_change=perform_search)
    
    st.header("🏗️ Elevation Specs")
    dock_g_msl = st.number_input("Dock Ground MSL (ft)", value=900.0)
    b_h = st.number_input("Building Height (ft)", value=20.0)
    total_ant_msl = dock_g_msl + b_h + 15.0
    
    d_alt_agl = st.slider("Flight Alt (ft AGL)", 100, 400, 200)
    target_drone_msl = dock_g_msl + d_alt_agl
    
    st.divider()
    st.subheader("🌲 Obstruction Data")
    target_dir = st.selectbox("Direction:", dirs)
    
    # CLICK FIX: Explicitly showing what we are about to save
    current_dist = int(st.session_state.last_click_dist)
    st.write(f"**Current Selection:** {current_dist} ft")
    t_top_msl = st.number_input("Top MSL (Google Earth)", value=960.0)
    
    if st.button(f"➕ Lock Obstacle to {target_dir}"):
        st.session_state.vault[target_dir].append({"dist": current_dist, "t_msl": t_top_msl})
        st.success(f"Saved {current_dist}ft to {target_dir}")

    if st.button("🚨 RESET"):
        st.session_state.vault = {d: [] for d in dirs}
        st.rerun()

# --- 5. SURVEY MAP (ONE-CLICK FIX) ---
st.info("💡 CLICK MAP to detect distance, then click 'Lock Obstacle' in sidebar.")
m_k = f"sat_v{st.session_state.map_v}"
m = folium.Map(location=st.session_state.center_coord, zoom_start=19, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(m)

# st_folium update logic
out = st_folium(m, width=900, height=450, key=m_k, returned_objects=["last_clicked"])

if out and out.get("last_clicked"):
    nl, no = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    new_d = geodesic(st.session_state.center_coord, (nl, no)).feet
    
    # If the distance has actually changed, update state immediately
    if abs(new_d - st.session_state.last_click_dist) > 1:
        st.session_state.last_click_dist = new_d
        st.rerun() # Forces the sidebar to show the NEW distance immediately

# --- 6. CALCULATIONS ---
rf_pts = []
table_data = []
max_ft = 3.5 * 5280

for d, ang in {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}.items():
    limits = [max_ft]
    reason = "Clear"
    for obs in st.session_state.vault[d]:
        dist, omsl = obs["dist"], obs["t_msl"]
        if omsl > total_ant_msl:
            limit = ((target_drone_msl - total_ant_msl) / (omsl - total_ant_msl)) * dist
            limits.append(max(limit, dist))
            reason = f"Obj @ {int(dist)}ft"
    
    final_d = min(limits)
    dest = geodesic(feet=final_d).destination(st.session_state.center_coord, ang)
    rf_pts.append({"lat": dest.latitude, "lon": dest.longitude, "name": d, "dist": final_d})
    table_data.append([d, reason, f"{(final_d/5280):.2f} mi"])

# --- 7. FINAL ANALYSIS ---
st.subheader("📊 Range Analysis Report")
res_map = folium.Map(location=st.session_state.center_coord, zoom_start=13)
folium.Polygon([(p['lat'], p['lon']) for p in rf_pts], color="blue", fill=True, opacity=0.2).add_to(res_map)
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(res_map)

for p in rf_pts:
    lbl = f"{(p['dist']/5280):.2f} mi"
    folium.Marker([p['lat'], p['lon']], icon=DivIcon(icon_size=(100,40), icon_anchor=(50,20),
        html=f'<div style="background:white; border:2px solid blue; border-radius:5px; color:black; font-weight:bold; font-size:10px; text-align:center; width:70px; padding:2px;">{p["name"]}<br>{lbl}</div>')).add_to(res_map)

st_folium(res_map, width=1100, height=550, key=f"res_{st.session_state.map_v}")

# Summary Table
df = pd.DataFrame(table_data, columns=["Direction", "Limiting Obstacle", "Max Range"])
st.table(df)

# --- 8. EXPORT REPORT ---
st.divider()
st.subheader("💾 Export Report")

# Create a standalone HTML file that can be saved/printed
report_html = res_map._repr_html_()
full_html = f"<h1>Site Report: {site_name}</h1>{report_html}<h3>Data Table</h3>{df.to_html()}"

st.download_button(
    label="📩 Download Clean Report (HTML)",
    data=full_html,
    file_name=f"DJI_Report_{site_name}.html",
    mime="text/html",
    help="Download this file, open it in your browser, and press Ctrl+P to save as a professional PDF."
)
