import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DJI M4TD Topo-Master")

# --- 1. SESSION STATE ---
if 'vault' not in st.session_state: 
    st.session_state.vault = []
if 'topo_hits' not in st.session_state: 
    st.session_state.topo_hits = {} # Stores scanned hill points
if 'center_coord' not in st.session_state: 
    st.session_state.center_coord = [33.6644, -84.0113]
if 'last_click' not in st.session_state: 
    st.session_state.last_click = {"lat": 0, "lon": 0, "dist": 0}
if 'map_v' not in st.session_state: 
    st.session_state.map_v = 1

# --- 2. ENGINES ---
def get_elev_msl(lat, lon):
    """Queries USGS for ground MSL at specific coordinates."""
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=3).json()
        return float(res.get('value', 0))
    except: 
        return None

def handle_search():
    """Handles address search or raw coordinate entry."""
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
        st.session_state.topo_hits = {} # Clear old topo data on new location
        st.session_state.vault = []      # Clear old obstacles on new location
    except: 
        st.error("Search failed. Try 'Lat, Lon' or a full Address.")

# --- 3. UI SIDEBAR ---
st.title("🛰️ DJI M4TD Topo-Scan Pro")

with st.sidebar:
    st.header("1. Site Entry")
    st.text_input("Address or Lat, Lon:", key="search_input", on_change=handle_search)
    b_h = st.number_input("Building Height (ft)", value=20.0)
    d_alt = st.slider("Mission Alt (ft AGL)", 100, 400, 200)
    
    st.header("2. Terrain Tools")
    if st.button("📡 SCAN TERRAIN (3.5mi Sweep)"):
        with st.spinner("Pinging USGS Topography Database... This takes ~15 seconds."):
            base_g = get_elev_msl(st.session_state.center_coord[0], st.session_state.center_coord[1]) or 900.0
            ant_msl = base_g + b_h + 15
            drone_msl = base_g + d_alt
            
            new_topo = {}
            # Scan 8 directions, every 1500ft out to 3.5mi (Higher speed sample)
            for angle in [0, 45, 90, 135, 180, 225, 270, 315]:
                limit = 3.5 * 5280
                for dist in range(1500, int(3.5*5280), 1500):
                    pt = geodesic(feet=dist).destination(st.session_state.center_coord, angle)
                    ground = get_elev_msl(pt.latitude, pt.longitude)
                    if ground:
                        # Required MSL to maintain signal path at this distance
                        req = ant_msl + ((drone_msl - ant_msl) * (dist / (3.5*5280)))
                        # Assumes a 50ft tree canopy on top of ground MSL
                        if (ground + 50) > req: 
                            limit = dist
                            break
                new_topo[angle] = limit
            st.session_state.topo_hits = new_topo
            st.success("Topo Scan Complete!")

    st.header("3. Surgical Block")
    st.write(f"**Click Dist:** {int(st.session_state.last_click['dist'])} ft")
    obs_w = st.number_input("Obstacle Width (ft)", value=100)
    
    if st.button("➕ Block Wedge"):
        lat1, lon1 = st.session_state.center_coord
        lat2, lon2 = st.session_state.last_click['lat'], st.session_state.last_click['lon']
        
        # Bearing Calculation
        dLon = math.radians(lon2 - lon1)
        y = math.sin(dLon) * math.cos(math.radians(lat2))
        x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dLon)
        brng = (math.degrees(math.atan2(y, x)) + 360) % 360
        
        st.session_state.vault.append({
            "dist": st.session_state.last_click['dist'], 
            "brng": brng, 
            "width": obs_w,
            "coords": [lat2, lon2]
        })
        st.success(f"Wedge Saved at {int(brng)}°")

    if st.button("🚨 RESET ALL"):
        st.session_state.vault = []
        st.session_state.topo_hits = {}
        st.rerun()

# --- 4. MAP GENERATION ---
m = folium.Map(location=st.session_state.center_coord, zoom_start=18, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

# A. DISTANCE RINGS
for mi in [1, 2, 3, 3.5]:
    folium.Circle(
        location=st.session_state.center_coord, 
        radius=mi*5280*0.3048, 
        color='white', weight=1, fill=False, opacity=0.3
    ).add_to(m)
    lbl_pt = geodesic(feet=mi*5280).destination(st.session_state.center_coord, 0)
    folium.Marker([lbl_pt.latitude, lbl_pt.longitude], icon=DivIcon(icon_size=(50,20), icon_anchor=(25,10),
        html=f'<div style="font-size: 8pt; color: white; font-weight: bold;">{mi} mi</div>')).add_to(m)

# B. DYNAMIC POLYGON (Topo + Surgical Wedge Integration)
poly_pts = []
max_ft = 3.5 * 5280

# 5-degree increments for a smooth visual polygon
for angle in range(0, 362, 5):
    d_limit = max_ft
    
    # 1. Apply Topo Scan Reductions
    if st.session_state.topo_hits:
        # Snap current angle to nearest scanned bearing (0, 45, 90...)
        closest_ang = min(st.session_state.topo_hits.keys(), key=lambda x: abs(x - angle))
        d_limit = min(d_limit, st.session_state.topo_hits[closest_ang])

    # 2. Apply Surgical Blocks (Wedges)
    for v in st.session_state.vault:
        # Calculate angular width of the obstacle from dock origin
        angular_width = math.degrees(v['width'] / v['dist'])
        if abs(angle - v['brng']) < (angular_width / 2):
            d_limit = min(d_limit, v['dist'])
            break
            
    p = geodesic(feet=d_limit).destination(st.session_state.center_coord, angle)
    poly_pts.append([p.latitude, p.longitude])

# Render the Green Safe Zone
folium.Polygon(
    locations=poly_pts, 
    color='green', fill=True, fill_color='green', fill_opacity=0.2, weight=2
).add_to(m)

# C. RED SHADOW WEDGES (Visual Shadows behind blocks)
for v in st.session_state.vault:
    hw = math.degrees(v['width'] / v['dist']) / 2
    pts = [
        geodesic(feet=v['dist']).destination(st.session_state.center_coord, v['brng'] - hw),
        geodesic(feet=v['dist']).destination(st.session_state.center_coord, v['brng'] + hw),
        geodesic(feet=max_ft).destination(st.session_state.center_coord, v['brng'] + hw),
        geodesic(feet=max_ft).destination(st.session_state.center_coord, v['brng'] - hw)
    ]
    folium.Polygon(
        locations=[[p.latitude, p.longitude] for p in pts], 
        color='red', fill=True, fill_color='red', fill_opacity=0.3, weight=1
    ).add_to(m)
    # Mark the specific obstacle location
    folium.Marker([v['coords'][0], v['coords'][1]], icon=folium.Icon(color='orange', icon='tree', prefix='fa')).add_to(m)

# Dock Marker
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='blue', icon='house', prefix='fa')).add_to(m)

# --- 5. OUTPUT ---
out = st_folium(m, width=1100, height=600, key=f"map_v{st.session_state.map_v}")

if out and out.get("last_clicked"):
    clat, clon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    cdist = geodesic(st.session_state.center_coord, (clat, clon)).feet
    if cdist > 20:
        st.session_state.last_click = {"lat": clat, "lon": clon, "dist": cdist}
        st.rerun()

st.info("💡 **Instructions:** 1. Search Address. 2. Click 'Scan Terrain' to auto-detect hills. 3. Click a tree on map and click 'Block Wedge' to surgically remove dead zones.")
