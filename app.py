import streamlit as st
import folium, requests, random, string, io
import pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DFR Site Assessment")

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

# --- 2. SEARCH ENGINE ---
def perform_search():
    query = st.session_state.search_box
    if not query: return
    # Professional Failover Search (ArcGIS)
    url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={query}&maxLocations=1"
    try:
        res = requests.get(url, timeout=5).json()
        if res.get('candidates'):
            loc = res['candidates'][0]['location']
            st.session_state.center_coord = [loc['y'], loc['x']]
            st.session_state.map_v += 1
            st.toast("📍 Location Updated!")
    except: st.error("Search Service Busy. Try again in a moment.")

# --- 3. UI TOP & INSTRUCTIONS ---
st.title("🛰️ DFR Site Assessment")

with st.expander("📖 HOW TO USE THIS TOOL (Click to Expand)", expanded=True):
    st.markdown("""
    ### 🛠️ Step-by-Step Instructions
    1.  **Locate Site:** Use the **Search Address** box in the sidebar.
    2.  **Set Elevations:** Enter the **Ground MSL** of the dock location and the **Building Height**. 
    3.  **Identify Obstacles:**
        * Find a tree/building on the Map and **Click it**. The distance appears in the sidebar instantly.
        * In Google Earth, find the **Top MSL** (highest point) of that obstacle.
        * Select the **Direction**, enter that MSL, and click **➕ Lock Obstacle**.
    4.  **Repeat:** Add multiple obstacles per direction. The app uses **RF Propagation Logic** (allowing for signal diffraction) to give you a realistic range.
    5.  **Export:** Scroll to the bottom to download a clean **Report** for your records.
    """)

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("📋 Site Information")
    site_name = st.text_input("Site Name", placeholder="e.g. Conyers PD Rooftop")
    st.text_input("Search Address:", key="search_box", on_change=perform_search)
    
    st.header("🏗️ Elevation Specs (MSL)")
    dock_g_msl = st.number_input("Dock Ground MSL (ft)", value=900.0, step=1.0)
    b_h = st.number_input("Building Height (ft)", value=20.0, step=1.0)
    # Total origin including 15ft mast
    total_ant_msl = dock_g_msl + b_h + 15.0
    st.caption(f"Antenna Origin: {int(total_ant_msl)} ft MSL")
    
    st.header("🚀 Mission Specs")
    d_alt_agl = st.slider("Flight Alt (ft AGL)", 100, 400, 200)
    # Drone MSL relative to takeoff ground
    target_drone_msl = dock_g_msl + d_alt_agl
    st.caption(f"Drone Target: {int(target_drone_msl)} ft MSL")
    
    st.divider()
    st.subheader("🌲 Obstruction Data")
    target_dir = st.selectbox("Direction:", dirs)
    
    current_dist = int(st.session_state.last_click_dist)
    st.write(f"**Selected Distance:** {current_dist} ft")
    t_top_msl = st.number_input("Obstacle Top MSL", value=960.0, step=1.0)
    
    if st.button(f"➕ Lock Obstacle to {target_dir}"):
        st.session_state.vault[target_dir].append({"dist": current_dist, "t_msl": t_top_msl})
        st.success(f"Saved to {target_dir}!")

    if st.button("🚨 RESET ENTIRE SURVEY"):
        st.session_state.vault = {d: [] for d in dirs}
        st.rerun()

# --- 5. SURVEY MAP (ONE-CLICK) ---
st.subheader(f"Satellite Survey: {site_name if site_name else 'Active Site'}")
m_k = f"sat_v{st.session_state.map_v}"
m = folium.Map(location=st.session_state.center_coord, zoom_start=19, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red', icon='tower-broadcast', prefix='fa')).add_to(m)

out = st_folium(m, width=900, height=450, key=m_k, returned_objects=["last_clicked"])

if out and out.get("last_clicked"):
    nl, no = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    new_d = geodesic(st.session_state.center_coord, (nl, no)).feet
    if abs(new_d - st.session_state.last_click_dist) > 0.5:
        st.session_state.last_click_dist = new_d
        st.rerun()

# --- 6. RF CALCULATIONS (DIFFRACTION-AWARE) ---
rf_pts = []
table_data = []
max_ft = 3.5 * 5280

for d, ang in {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}.items():
    limits = [max_ft]
    reason = "Clear (3.5mi)"
    
    for obs in st.session_state.vault[d]:
        dist, omsl = obs["dist"], obs["t_msl"]
        
        # RF DIFFRACTION LOGIC: Radio waves bend over obstacles.
        # We allow a 12ft 'Grazing Buffer' before the signal is considered lost.
        effective_omsl = omsl - 12.0
        
        if effective_omsl > total_ant_msl:
            # Calculate range based on the slope between Antenna and Drone MSL
            limit = ((target_drone_msl - total_ant_msl) / (effective_omsl - total_ant_msl)) * dist
            # Real-world Floor: O3/O4 will almost always reach 1500ft in standard suburban LOS
            limit = max(limit, 1500.0)
            limits.append(limit)
            reason = f"Obj @ {int(dist)}ft"
    
    final_d = min(limits)
    dest = geodesic(feet=final_d).destination(st.session_state.center_coord, ang)
    rf_pts.append({"lat": dest.latitude, "lon": dest.longitude, "name": d, "dist": final_d})
    
    # Color Coding
    mi = final_d / 5280
    if mi >= 2.5: status = "🟢 Excellent"
    elif mi >= 1.0: status = "🟡 Good"
    else: status = "🔴 Marginal"
    
    table_data.append([d, reason, f"{mi:.2f} miles", status])

# --- 7. FINAL ANALYSIS REPORT ---
st.divider()
st.subheader("📊 Final Range Analysis Report")
res_map = folium.Map(location=st.session_state.center_coord, zoom_start=13)

# Add Range Polygon
folium.Polygon([(p['lat'], p['lon']) for p in rf_pts], color="blue", fill=True, opacity=0.2).add_to(res_map)
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(res_map)

for p in rf_pts:
    lbl = f"{(p['dist']/5280):.2f} mi"
    folium.Marker([p['lat'], p['lon']], icon=DivIcon(icon_size=(100,40), icon_anchor=(50,20),
        html=f'<div style="background:white; border:2px solid blue; border-radius:5px; color:black; font-weight:bold; font-size:10px; text-align:center; width:70px; padding:2px;">{p["name"]}<br>{lbl}</div>')).add_to(res_map)

st_folium(res_map, width=1100, height=550, key=f"res_{st.session_state.map_v}")

st.subheader("📋 Engineering Summary Table")
df = pd.DataFrame(table_data, columns=["Direction", "Limiting Obstacle", "Range", "Link Quality"])
st.table(df)

# --- 8. EXPORT REPORT ---
st.divider()
st.subheader("💾 Export Site Report")
report_html = res_map._repr_html_()
full_html = f"""
<div style="font-family: sans-serif; padding: 20px;">
    <h1>DJI M4TD Site Survey: {site_name if site_name else 'Untitled Site'}</h1>
    <hr>
    <p><b>Antenna Height:</b> {int(total_ant_msl)} ft MSL | <b>Target Mission Altitude:</b> {int(target_drone_msl)} ft MSL</p>
    <div style="margin-top: 20px;">{report_html}</div>
    <h2 style="margin-top: 40px;">Survey Data</h2>
    {df.to_html(index=False)}
    <p style="margin-top: 50px; font-size: 10px; color: grey;">Generated by DJI M4TD Engineering Planner. Range estimates are based on geometric Line-of-Sight and standard RF diffraction models.</p>
</div>
"""
st.download_button(
    label="📩 Download Report (HTML)",
    data=full_html,
    file_name=f"DJI_Report_{site_name.replace(' ', '_')}.html",
    mime="text/html"
)
