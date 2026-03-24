import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DJI M4TD Radial Master")

# --- 1. STATE ---
if 'vault' not in st.session_state: st.session_state.vault = []
if 'center_coord' not in st.session_state: st.session_state.center_coord = [33.6644, -84.0113]
if 'last_click' not in st.session_state: st.session_state.last_click = {"lat": 0, "lon": 0, "dist": 0}
if 'map_v' not in st.session_state: st.session_state.map_v = 1

# --- 2. SEARCH ---
def handle_search():
    q = st.session_state.search_input
    if not q: return
    try:
        if "," in q:
            lat, lon = map(float, q.split(","))
            st.session_state.center_coord = [lat, lon]
        else:
            url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={q}&maxLocations=1"
            res = requests.get(url).json()
            loc = res['candidates'][0]['location']
            st.session_state.center_coord = [loc['y'], loc['x']]
        st.session_state.map_v += 1
    except: st.error("Invalid Entry.")

# --- 3. UI ---
st.title("🛰️ DJI M4TD Radial Master Planner")

with st.sidebar:
    st.header("1. Site Entry")
    st.text_input("Address or Lat, Lon:", key="search_input", on_change=handle_search)
    b_h = st.number_input("Building Height (ft)", value=20.0)
    
    st.header("2. Surgical Block")
    st.write(f"**Click Dist:** {int(st.session_state.last_click['dist'])} ft")
    obs_width = st.number_input("Obstacle Width (ft)", value=100)
    
    if st.button("➕ Block This Wedge"):
        lat1, lon1 = st.session_state.center_coord
        lat2, lon2 = st.session_state.last_click['lat'], st.session_state.last_click['lon']
        # Bearing Math
        dLon = math.radians(lon2 - lon1)
        y = math.sin(dLon) * math.cos(math.radians(lat2))
        x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dLon)
        brng = (math.degrees(math.atan2(y, x)) + 360) % 360
        
        st.session_state.vault.append({"dist": st.session_state.last_click['dist'], "brng": brng, "width": obs_width})
        st.success("Wedge Blocked.")

    if st.button("🚨 RESET ALL"):
        st.session_state.vault = []
        st.rerun()

# --- 4. MAP GENERATION ---
m = folium.Map(location=st.session_state.center_coord, zoom_start=18, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

max_range_ft = 3.5 * 5280

# A. DRAW DISTANCE RINGS & MARKERS
for mi in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]:
    dist_ft = mi * 5280
    # The Circle
    folium.Circle(location=st.session_state.center_coord, radius=dist_ft * 0.3048, # Convert ft to meters
                  color='white', weight=1, fill=False, opacity=0.4).add_to(m)
    # The Label (North-facing)
    lbl_pt = geodesic(feet=dist_ft).destination(st.session_state.center_coord, 0)
    folium.Marker([lbl_pt.latitude, lbl_pt.longitude], icon=DivIcon(icon_size=(50,20), icon_anchor=(25,10),
        html=f'<div style="font-size: 8pt; color: white; font-weight: bold;">{mi} mi</div>')).add_to(m)

# B. GENERATE RADIAL SAFE ZONE (GREEN POLYGON)
poly_points = []
# Scan 360 degrees in 2-degree increments for a smooth circle
for angle in range(0, 362, 2):
    current_dist = max_range_ft
    
    # Check if this angle is blocked by a wedge
    for v in st.session_state.vault:
        # Calculate angular width of the obstacle from the dock's perspective
        angle_w = math.degrees(v['width'] / v['dist'])
        if abs(angle - v['brng']) < (angle_w / 2):
            current_dist = v['dist'] # Cut the polygon back to the obstacle
            break
            
    p = geodesic(feet=current_dist).destination(st.session_state.center_coord, angle)
    poly_points.append([p.latitude, p.longitude])

# Close the polygon back to center for wedges to work visually
# To make it look like a 'fan', we actually draw the outer edge 
folium.Polygon(locations=poly_points, color='green', fill=True, fill_color='green', fill_opacity=0.2, weight=2).add_to(m)

# C. DRAW RED SHADOWS
for v in st.session_state.vault:
    hw = math.degrees(v['width'] / v['dist']) / 2
    pts = [
        geodesic(feet=v['dist']).destination(st.session_state.center_coord, v['brng'] - hw),
        geodesic(feet=v['dist']).destination(st.session_state.center_coord, v['brng'] + hw),
        geodesic(feet=max_range_ft).destination(st.session_state.center_coord, v['brng'] + hw),
        geodesic(feet=max_range_ft).destination(st.session_state.center_coord, v['brng'] - hw)
    ]
    folium.Polygon(locations=[[p.latitude, p.longitude] for p in pts], color='red', fill=True, fill_opacity=0.4).add_to(m)

# D. CENTER MARKER
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='blue', icon='house', prefix='fa')).add_to(m)

# --- 5. STREAMLIT OUTPUT ---
out = st_folium(m, width=1100, height=600, key=f"map_v{st.session_state.map_v}")

if out and out.get("last_clicked"):
    clat, clon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    cdist = geodesic(st.session_state.center_coord, (clat, clon)).feet
    if cdist > 20:
        st.session_state.last_click = {"lat": clat, "lon": clon, "dist": cdist}
        st.rerun()

st.info("💡 **How to block:** Click a tree on the map -> Sidebar updates with distance -> Click 'Block This Wedge'. The green safe-zone will pull back, and a red shadow will appear behind the obstacle.")
