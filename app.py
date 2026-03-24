import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DJI M4TD Auto-Planner")

# --- 1. SESSION STATE ---
if 'vault' not in st.session_state: st.session_state.vault = []
if 'center_coord' not in st.session_state: st.session_state.center_coord = [33.6644, -84.0113]
if 'map_v' not in st.session_state: st.session_state.map_v = 1 # The 'Force Refresh' Key

# --- 2. ENGINES ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=3).json()
        val = res.get('value')
        if val and val > -1000: return float(val)
    except: pass
    return 900.0

def run_auto_scan(lat, lon, ant_msl, drone_msl):
    scan_results = []
    max_ft = 3.5 * 5280
    bearings = [0, 45, 90, 135, 180, 225, 270, 315]
    
    for brng in bearings:
        limit = max_ft
        # 1500ft steps for reliable government API speed
        for dist in range(1500, int(max_ft), 1500):
            pt = geodesic(feet=dist).destination((lat, lon), brng)
            ground = get_elev_msl(pt.latitude, pt.longitude)
            # Tree Logic: Ground + 65ft Canopy Buffer
            tree_top_msl = ground + 65.0
            req_msl = ant_msl + ((drone_msl - ant_msl) * (dist / max_ft))
            if (tree_top_msl - 12) > req_msl:
                limit = dist
                break
        scan_results.append({"brng": brng, "limit": limit})
    return scan_results

# --- 3. UI SIDEBAR ---
st.title("🤖 DJI M4TD Full-Auto RF Planner")

with st.sidebar:
    st.header("1. Site Address")
    addr = st.text_input("Address or Lat, Lon:", placeholder="e.g. 123 Main St, Atlanta, GA")
    b_h = st.number_input("Building Height (ft)", value=20.0)
    d_alt = st.slider("Mission Altitude (ft AGL)", 100, 400, 200)
    
    if st.button("🚀 GENERATE 3.5mi AUTO-SURVEY"):
        with st.spinner("Executing Lidar-Topography & Canopy Scan..."):
            g_url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={addr}&maxLocations=1"
            res = requests.get(g_url).json()
            if res.get('candidates'):
                loc = res['candidates'][0]['location']
                clat, clon = loc['y'], loc['x']
                st.session_state.center_coord = [clat, clon]
                
                # Elevations
                base_g = get_elev_msl(clat, clon)
                ant_origin = base_g + b_h + 15.0
                drone_target = base_g + d_alt
                
                # The Scan
                st.session_state.vault = run_auto_scan(clat, clon, ant_origin, drone_target)
                # CRITICAL: Increment the key to force the map to redraw
                st.session_state.map_v += 1 
                st.success("Auto-Survey Complete!")

# --- 4. MAP RENDERING ---
# Using the session_state.map_v in the key ensures the color shows up every time
m = folium.Map(location=st.session_state.center_coord, zoom_start=14, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

# Distance Rings
for mi in [1.0, 2.0, 3.0, 3.5]:
    folium.Circle(location=st.session_state.center_coord, radius=mi*5280*0.3048, 
                  color='white', weight=1, fill=False, opacity=0.4).add_to(m)

# The Green Safe-Zone (Only if a scan has been run)
if st.session_state.vault:
    poly_pts = []
    # Smooth the polygon
    for angle in range(0, 362, 5):
        closest = min(st.session_state.vault, key=lambda x: abs(x['brng'] - angle))
        d_limit = closest['limit']
        p = geodesic(feet=d_limit).destination(st.session_state.center_coord, angle)
        poly_pts.append([p.latitude, p.longitude])
    
    # Force 'add_to(m)' inside the conditional
    folium.Polygon(poly_pts, color='green', fill=True, fill_color='green', fill_opacity=0.3, weight=2).add_to(m)

folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red', icon='tower-broadcast', prefix='fa')).add_to(m)

# Render with the Dynamic Key
st_folium(m, width=1100, height=650, key=f"auto_map_v{st.session_state.map_v}")

# --- 5. DATA TABLE ---
if st.session_state.vault:
    st.write("### 📋 Automated Range Summary")
    df = pd.DataFrame(st.session_state.vault)
    df['Range (miles)'] = df['limit'] / 5280
    st.table(df[['brng', 'limit', 'Range (miles)']])
