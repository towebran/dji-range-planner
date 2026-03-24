import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DJI M4TD Path Surveyor")

# --- 1. STATE INITIALIZATION ---
if 'vault' not in st.session_state: st.session_state.vault = []
if 'center_coord' not in st.session_state: st.session_state.center_coord = [33.6644, -84.0113]
if 'last_click' not in st.session_state: st.session_state.last_click = {"lat": 0, "lon": 0, "dist": 0}
if 'map_v' not in st.session_state: st.session_state.map_v = 1

# --- 2. SEARCH & ELEVATION TOOLS ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=2).json()
        return float(res.get('value', 0))
    except: return 900.0

def handle_search():
    q = st.session_state.search_input
    if not q: return
    try:
        # Check if input is coordinates
        parts = q.split(',')
        if len(parts) == 2:
            st.session_state.center_coord = [float(parts[0]), float(parts[1])]
        else:
            url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={q}&maxLocations=1"
            res = requests.get(url).json()
            loc = res['candidates'][0]['location']
            st.session_state.center_coord = [loc['y'], loc['x']]
        st.session_state.map_v += 1
    except: st.error("Invalid Address or Coordinates.")

# --- 3. UI LAYOUT ---
st.title("📡 DJI M4TD Surgical Path Planner")

with st.sidebar:
    st.header("1. Site Entry")
    st.text_input("Address or Lat, Lon:", key="search_input", on_change=handle_search)
    b_h = st.number_input("Building Height (ft)", value=20.0)
    d_alt = st.slider("Drone Mission Alt (ft AGL)", 100, 400, 200)
    
    st.header("2. Surgical Obstacle")
    st.info(f"Last Click: {int(st.session_state.last_click['dist'])} ft away")
    obs_width = st.number_input("Width of Obstacle (ft)", value=50)
    obs_msl = st.number_input("Top MSL of Obstacle", value=960.0)
    
    if st.button("➕ Add Surgical Block"):
        # Calculate bearing to click
        lat1, lon1 = st.session_state.center_coord
        lat2, lon2 = st.session_state.last_click['lat'], st.session_state.last_click['lon']
        # Simple bearing math
        dLon = math.radians(lon2 - lon1)
        y = math.sin(dLon) * math.cos(math.radians(lat2))
        x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dLon)
        brng = (math.degrees(math.atan2(y, x)) + 360) % 360
        
        st.session_state.vault.append({
            "dist": st.session_state.last_click['dist'], 
            "msl": obs_msl, "brng": brng, "width": obs_width
        })
        st.success("Blocked Area Saved.")

    if st.button("🚨 RESET"):
        st.session_state.vault = []
        st.rerun()

# --- 4. THE SURVEY ENGINE ---
st.write("### Site Survey & Topo-Scan")
m = folium.Map(location=st.session_state.center_coord, zoom_start=18, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(m)

# Survey Logic
base_g_msl = get_elev_msl(st.session_state.center_coord[0], st.session_state.center_coord[1])
ant_msl = base_g_msl + b_h + 15
drone_msl = base_g_msl + d_alt
max_range = 3.5 * 5280

# 8 Main Radial Paths
for angle in [0, 45, 90, 135, 180, 225, 270, 315]:
    path_points = [st.session_state.center_coord]
    # Scan every 500ft
    for step in range(500, int(max_range)+500, 500):
        target = geodesic(feet=step).destination(st.session_state.center_coord, angle)
        
        # Topo Check
        ground = get_elev_msl(target.latitude, target.longitude)
        required = ant_msl + ((drone_msl - ant_msl) * (step/max_range))
        
        # Check if this specific step is inside a Surgical Block
        is_shadowed = False
        for v in st.session_state.vault:
            # Check if angle falls within the 'shadow' of the block width
            angle_width = math.degrees(v['width'] / v['dist'])
            if abs(angle - v['brng']) < (angle_width/2) and step > v['dist']:
                if v['msl'] - 12 > required: is_shadowed = True
        
        if (ground + 50) > required or is_shadowed: # +50 assumes trees
            color, weight = 'red', 2
        else:
            color, weight = 'green', 4
            
        folium.PolyLine([path_points[-1], [target.latitude, target.longitude]], color=color, weight=weight).add_to(m)
        path_points.append([target.latitude, target.longitude])

# Display Map
out = st_folium(m, width=1100, height=600, key=f"map_{st.session_state.map_v}")

# Click Capture
if out and out.get("last_clicked"):
    clat, clon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    cdist = geodesic(st.session_state.center_coord, (clat, clon)).feet
    if cdist > 20:
        st.session_state.last_click = {"lat": clat, "lon": clon, "dist": cdist}
        st.rerun()

# --- 5. SURGICAL BLOCKS (Shadow Wedges) ---
for v in st.session_state.vault:
    # Drawing the "Shadow Wedge" on the map for visual confirmation
    half_w = math.degrees(v['width'] / v['dist']) / 2
    p1 = geodesic(feet=v['dist']).destination(st.session_state.center_coord, v['brng'] - half_w)
    p2 = geodesic(feet=v['dist']).destination(st.session_state.center_coord, v['brng'] + half_w)
    p3 = geodesic(feet=max_range).destination(st.session_state.center_coord, v['brng'] + half_w)
    p4 = geodesic(feet=max_range).destination(st.session_state.center_coord, v['brng'] - half_w)
    folium.Polygon(locations=[[p1.latitude, p1.longitude], [p2.latitude, p2.longitude], 
                             [p3.latitude, p3.longitude], [p4.latitude, p4.longitude]], 
                   color="red", fill=True, opacity=0.3).add_to(m)
