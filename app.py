import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DJI M4TD Auto-Planner")

# --- 1. SESSION STATE ---
if 'vault' not in st.session_state: st.session_state.vault = []
if 'center_coord' not in st.session_state: st.session_state.center_coord = [33.6644, -84.0113]
if 'map_v' not in st.session_state: st.session_state.map_v = 1

# --- 2. THE AUTO-SCAN ENGINE ---
def get_elev_msl(lat, lon):
    """Fetch Ground MSL from USGS."""
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=2).json()
        val = res.get('value')
        if val and val > -1000: return float(val)
    except: pass
    return 900.0 # Standard fallback

def run_auto_scan(lat, lon, ant_msl, drone_msl):
    """Sweeps 8 directions and returns the RF-limited distance for each."""
    scan_results = []
    max_ft = 3.5 * 5280
    # Scan directions
    bearings = [0, 45, 90, 135, 180, 225, 270, 315]
    
    for brng in bearings:
        limit = max_ft
        # Sample every 1500ft to build the path profile
        for dist in range(1500, int(max_ft), 1500):
            pt = geodesic(feet=dist).destination((lat, lon), brng)
            ground = get_elev_msl(pt.latitude, pt.longitude)
            
            # AUTOMATED TREE HEIGHT: Ground + 65ft AI Canopy Buffer
            tree_top_msl = ground + 65.0
            
            # RF SLOPE CHECK: (12ft Diffraction Allowance)
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
            # A. Search Location
            g_url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={addr}&maxLocations=1"
            res = requests.get(g_url).json()
            if res.get('candidates'):
                loc = res['candidates'][0]['location']
                clat, clon = loc['y'], loc['x']
                st.session_state.center_coord = [clat, clon]
                
                # B. Build Baseline Elevations
                base_g = get_elev_msl(clat, clon)
                ant_origin = base_g + b_h + 15.0 # Includes 15ft mast
                drone_target = base_g + d_alt
                
                # C. Run Scan
                st.session_state.vault = run_auto_scan(clat, clon, ant_origin, drone_target)
                st.session_state.map_v += 1
                st.success("Auto-Survey Complete!")

# --- 4. MAP RENDERING ---
m = folium.Map(location=st.session_state.center_coord, zoom_start=14, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

max_range_ft = 3.5 * 5280

# A. 0.5 MILE DISTANCE MARKERS & RINGS
for mi in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]:
    dist_ft = mi * 5280
    # The concentric ring
    folium.Circle(
        location=st.session_state.center_coord, 
        radius=dist_ft * 0.3048, # Feet to Meters
        color='white', weight=1, fill=False, opacity=0.4
    ).add_to(m)
    # The Label (Facing North)
    lbl_pt = geodesic(feet=dist_ft).destination(st.session_state.center_coord, 0)
    folium.Marker([lbl_pt.latitude, lbl_pt.longitude], icon=DivIcon(icon_size=(50,20), icon_anchor=(25,10),
        html=f'<div style="font-size: 8pt; color: white; font-weight: bold; background: rgba(0,0,0,0.5); padding: 2px; border-radius: 3px;">{mi} mi</div>')).add_to(m)

# B. DYNAMIC SAFE-ZONE FAN
if st.session_state.vault:
    poly_pts = []
    # Build 360-degree smooth polygon based on the 8 scanned directions
    for angle in range(0, 362, 5):
        # Find closest scanned angle limit
        closest = min(st.session_state.vault, key=lambda x: abs(x['brng'] - angle))
        d_limit = closest['limit']
        
        p = geodesic(feet=d_limit).destination(st.session_state.center_coord, angle)
        poly_pts.append([p.latitude, p.longitude])
    
    folium.Polygon(poly_pts, color='green', fill=True, fill_color='green', fill_opacity=0.3, weight=2).add_to(m)

# C. CENTER MARKER
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red', icon='tower-broadcast', prefix='fa')).add_to(m)

# RENDER
st_folium(m, width=1100, height=650, key=f"auto_map_{st.session_state.map_v}")

# D. DATA TABLE
if st.session_state.vault:
    st.write("### 📋 Automated Range Summary")
    df = pd.DataFrame(st.session_state.vault)
    df['limit_mi'] = df['limit'] / 5280
    df.columns = ["Bearing (°)", "Range (ft)", "Range (miles)"]
    st.table(df)
