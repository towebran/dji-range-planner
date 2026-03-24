import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DJI M4TD Path Surveyor")

# --- 1. STATE ---
if 'vault' not in st.session_state: st.session_state.vault = []
if 'center_coord' not in st.session_state: st.session_state.center_coord = [33.6644, -84.0113]
if 'last_click' not in st.session_state: st.session_state.last_click = {"lat": 0, "lon": 0, "dist": 0}
if 'map_v' not in st.session_state: st.session_state.map_v = 1

# --- 2. SEARCH & ELEVATION TOOLS ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=3).json()
        return float(res.get('value', 0))
    except: return 900.0

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
    except: st.error("Search failed. Use 'Lat, Lon' or a full Address.")

# --- 3. UI ---
st.title("📡 DJI M4TD Surgical Path Planner")

with st.sidebar:
    st.header("1. Site Entry")
    st.text_input("Address or Lat, Lon:", key="search_input", on_change=handle_search)
    b_h = st.number_input("Building Height (ft)", value=20.0)
    d_alt = st.slider("Drone Mission Alt (ft AGL)", 100, 400, 200)
    
    st.header("2. Block a Path")
    st.write(f"**Click Dist:** {int(st.session_state.last_click['dist'])} ft")
    obs_width = st.number_input("Shadow Width (ft)", value=100)
    obs_msl = st.number_input("Top MSL of Obstacle", value=960.0)
    
    if st.button("➕ Create Block Wedge"):
        lat1, lon1 = st.session_state.center_coord
        lat2, lon2 = st.session_state.last_click['lat'], st.session_state.last_click['lon']
        # Calculation for bearing
        dLon = math.radians(lon2 - lon1)
        y = math.sin(dLon) * math.cos(math.radians(lat2))
        x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dLon)
        brng = (math.degrees(math.atan2(y, x)) + 360) % 360
        
        st.session_state.vault.append({
            "dist": st.session_state.last_click['dist'], 
            "msl": obs_msl, "brng": brng, "width": obs_width,
            "coords": [lat2, lon2]
        })
        st.success("Blocked Area Saved.")

    if st.button("🚨 RESET"):
        st.session_state.vault = []
        st.rerun()

# --- 4. MAP ENGINE ---
m = folium.Map(location=st.session_state.center_coord, zoom_start=18, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red', tooltip="Dock")).add_to(m)

# Logic Setup
base_msl = 900.0 # Standard fallback
ant_msl = base_msl + b_h + 15
drone_msl = base_msl + d_alt
max_ft = 3.5 * 5280

# Draw Radial Paths
for angle in [0, 45, 90, 135, 180, 225, 270, 315]:
    dest = geodesic(feet=max_ft).destination(st.session_state.center_coord, angle)
    line_color = 'green'
    
    # Check if this line is cut by a Wedge
    for v in st.session_state.vault:
        angle_w = math.degrees(v['width'] / v['dist'])
        if abs(angle - v['brng']) < (angle_w / 2):
            # Line is in the shadow of an obstacle.
            # We draw it as green UNTIL the obstacle, then RED after.
            obs_pt = geodesic(feet=v['dist']).destination(st.session_state.center_coord, angle)
            folium.PolyLine([st.session_state.center_coord, [obs_pt.latitude, obs_pt.longitude]], color='green', weight=4).add_to(m)
            folium.PolyLine([[obs_pt.latitude, obs_pt.longitude], [dest.latitude, dest.longitude]], color='red', weight=2, dash_array='5, 5').add_to(m)
            line_color = None # Already drawn
            break
            
    if line_color:
        folium.PolyLine([st.session_state.center_coord, [dest.latitude, dest.longitude]], color=line_color, weight=4).add_to(m)

# Draw Surgical Wedges (Visual Shadows)
for v in st.session_state.vault:
    hw = math.degrees(v['width'] / v['dist']) / 2
    p1 = geodesic(feet=v['dist']).destination(st.session_state.center_coord, v['brng'] - hw)
    p2 = geodesic(feet=v['dist']).destination(st.session_state.center_coord, v['brng'] + hw)
    p3 = geodesic(feet=max_ft).destination(st.session_state.center_coord, v['brng'] + hw)
    p4 = geodesic(feet=max_ft).destination(st.session_state.center_coord, v['brng'] - hw)
    folium.Polygon(locations=[[p1.latitude, p1.longitude], [p2.latitude, p2.longitude], 
                             [p3.latitude, p3.longitude], [p4.latitude, p4.longitude]], 
                   color="red", fill=True, opacity=0.2, tooltip="Shadow Zone").add_to(m)
    folium.Marker([v['coords'][0], v['coords'][1]], icon=folium.Icon(color='orange', icon='tree', prefix='fa')).add_to(m)

# Map Interaction
out = st_folium(m, width=1100, height=600, key=f"map_v{st.session_state.map_v}")

if out and out.get("last_clicked"):
    clat, clon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    cdist = geodesic(st.session_state.center_coord, (clat, clon)).feet
    if cdist > 20:
        st.session_state.last_click = {"lat": clat, "lon": clon, "dist": cdist}
        st.rerun()

st.info("💡 **Instructions:** Search Address -> Click Tree/Bldg -> Enter MSL & Width -> Click 'Create Block Wedge'. Red dashed lines show areas blocked by that specific object.")
