import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

# --- 1. ENGINES (ENHANCED FOR GEORGIA/USGS 2026) ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=3).json()
        val = res.get('value')
        # Filter out USGS null values (-10000)
        return float(val) if val and val > -1000 else 900.0
    except: return 900.0

def run_pro_scan(lat, lon, ant_msl, drone_msl):
    results = []
    max_range = 3.5 * 5280
    # Increase samples to every 800ft for better accuracy
    for brng in [0, 45, 90, 135, 180, 225, 270, 315]:
        limit = max_range
        consecutive_blocks = 0 
        
        for dist in range(800, int(max_range), 800):
            pt = geodesic(feet=dist).destination((lat, lon), brng)
            ground = get_elev_msl(pt.latitude, pt.longitude)
            
            # RF PHYSICS: Standard DJI O3/O4 can 'punch through' minor canopy
            # We assume a 60ft tree, but give it a 25ft 'diffraction/transparency' grace
            effective_obs_msl = ground + 60.0 - 25.0
            
            # Required MSL at this point for 60% Fresnel Clearance
            # (Simplifying the Fresnel calc for speed)
            fresnel_buffer = 15.0 # Required clear air around the beam
            req_msl = ant_msl + ((drone_msl - ant_msl) * (dist / max_range)) + fresnel_buffer
            
            if effective_obs_msl > req_msl:
                consecutive_blocks += 1
                # If we hit 2 points in a row of heavy blockage, the link fails
                if consecutive_blocks >= 2:
                    limit = dist
                    break
            else:
                consecutive_blocks = 0
                
        results.append({"brng": brng, "limit": limit})
    return results

# --- 2. UI & MAP (PRO SYNC) ---
st.title("🛰️ DJI M4TD High-Accuracy Range Planner")

if 'vault' not in st.session_state: st.session_state.vault = []
if 'center_coord' not in st.session_state: st.session_state.center_coord = [33.6644, -84.0113]
if 'map_v' not in st.session_state: st.session_state.map_v = 1

with st.sidebar:
    addr = st.text_input("Site Address:", "Crooked Creek, GA")
    b_h = st.number_input("Building Height (ft)", 20.0)
    d_alt = st.slider("Flight Alt (ft AGL)", 100, 400, 300)
    
    if st.button("🚀 RUN ACCURACY SCAN"):
        with st.spinner("Pinging USGS Lidar Baselines..."):
            g_url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={addr}&maxLocations=1"
            loc = requests.get(g_url).json()['candidates'][0]['location']
            st.session_state.center_coord = [loc['y'], loc['x']]
            
            base_g = get_elev_msl(loc['y'], loc['x'])
            st.session_state.vault = run_pro_scan(loc['y'], loc['x'], base_g+b_h+15, base_g+d_alt)
            st.session_state.map_v += 1

# --- 3. RENDERING ---
m = folium.Map(location=st.session_state.center_coord, zoom_start=14, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

# Accurate Distance Rings
for mi in [1, 2, 3, 3.5]:
    folium.Circle(st.session_state.center_coord, radius=mi*1609.34, color='white', weight=1, opacity=0.4).add_to(m)

# The 'Smart' Safe Fan
if st.session_state.vault:
    poly_pts = []
    for a in range(0, 362, 5):
        closest = min(st.session_state.vault, key=lambda x: abs(x['brng'] - a))
        p = geodesic(feet=closest['limit']).destination(st.session_state.center_coord, a)
        poly_pts.append([p.latitude, p.longitude])
    folium.Polygon(poly_pts, color='#00FF00', fill=True, fill_opacity=0.25).add_to(m)

st_folium(m, width=1100, height=650, key=f"v{st.session_state.map_v}")
