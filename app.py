import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DJI M4TD RF Pro Planner")

# --- 1. SESSION STATE (The 'Brain' of the app) ---
if 'vault' not in st.session_state: 
    st.session_state.vault = [] # This MUST be a list to hold MULTIPLE obstacles
if 'center_coord' not in st.session_state: 
    st.session_state.center_coord = [33.6644, -84.0113]
if 'last_click' not in st.session_state: 
    st.session_state.last_click = {"lat": 0, "lon": 0, "dist": 0, "g_msl": 900.0}
if 'map_v' not in st.session_state: 
    st.session_state.map_v = 1

# --- 2. ENGINES ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=2).json()
        val = res.get('value')
        if val and val > -1000: return float(val)
    except: pass
    return None

def handle_search():
    q = st.session_state.search_input
    if not q: return
    try:
        if "," in q:
            lat, lon = map(float, q.split(","))
            st.session_state.center_coord = [lat, lon]
        else:
            url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={q}&maxLocations=1"
            res = requests.get(url, timeout=5).json()
            if res.get('candidates'):
                loc = res['candidates'][0]['location']
                st.session_state.center_coord = [loc['y'], loc['x']]
        st.session_state.map_v += 1
        st.session_state.vault = [] # Clear only on NEW location search
    except: st.error("Search Failed.")

# --- 3. UI SIDEBAR ---
st.title("📡 DJI M4TD Surgical RF Planner")

with st.sidebar:
    st.header("1. Deployment Location")
    st.text_input("Address or Lat, Lon:", key="search_input", on_change=handle_search)
    
    dock_g_msl = st.number_input("Dock Ground MSL (ft)", value=900.0)
    b_h = st.number_input("Building Height (ft)", value=20.0)
    ant_msl = dock_g_msl + b_h + 15.0
    st.caption(f"Antenna Origin: **{int(ant_msl)} ft MSL**")
    
    st.header("2. Mission Specs")
    d_alt_agl = st.slider("Mission Alt (ft AGL)", 100, 400, 200)
    drone_target_msl = dock_g_msl + d_alt_agl
    
    st.header("3. Obstacle Entry")
    click_info = st.session_state.last_click
    st.write(f"**Click Dist:** {int(click_info['dist'])} ft")
    
    # Auto-MSL logic
    default_top = (click_info['g_msl'] + 40.0) if click_info['g_msl'] else 940.0
    obs_top_msl = st.number_input("Obstacle Top MSL", value=default_top)
    obs_w = st.number_input("Obstacle Width (ft)", value=100)
    
    if st.button("➕ Block This Wedge"):
        # RF Engineering Math
        dist = click_info['dist']
        max_range = 3.5 * 5280
        req_at_obs = ant_msl + ((drone_target_msl - ant_msl) * (dist / max_range))
        
        # Shadow projection (12ft Diffraction Buffer)
        # If obstacle blocks signal, calculate where shadow ends
        if (obs_top_msl - 12) > req_at_obs:
            # Similar triangles for shadow touchdown
            shadow_touchdown = ((drone_target_msl - ant_msl) / (obs_top_msl - 12 - ant_msl)) * dist
            shadow_limit = max(shadow_touchdown, dist)
        else:
            shadow_limit = max_range # Signal clears it
            
        # Bearing calc
        l1, n1 = st.session_state.center_coord
        l2, n2 = click_info['lat'], click_info['lon']
        dL = math.radians(n2 - n1)
        y = math.sin(dL) * math.cos(math.radians(l2))
        x = math.cos(math.radians(l1)) * math.sin(math.radians(l2)) - math.sin(math.radians(l1)) * math.cos(math.radians(l2)) * math.cos(dL)
        brng = (math.degrees(math.atan2(y, x)) + 360) % 360
        
        # APPEND to vault list
        st.session_state.vault.append({
            "dist": dist, "brng": brng, "width": obs_w, 
            "limit": shadow_limit, "coords": [l2, n2]
        })
        st.success(f"Obstacle #{len(st.session_state.vault)} Added!")
        st.rerun() # Force map to redraw with new data

    if st.button("🚨 RESET ALL"):
        st.session_state.vault = []
        st.rerun()

# --- 4. MAP & POLYGON RENDERING ---
m = folium.Map(location=st.session_state.center_coord, zoom_start=18, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

# Safe Zone Construction (360 degrees)
poly_pts = []
max_ft = 3.5 * 5280
for angle in range(0, 362, 5):
    d_limit = max_ft
    # Check every obstacle in the vault for this specific angle
    for v in st.session_state.vault:
        aw = math.degrees(v['width'] / v['dist'])
        if abs(angle - v['brng']) < (aw / 2):
            d_limit = min(d_limit, v['limit'])
    
    p = geodesic(feet=d_limit).destination(st.session_state.center_coord, angle)
    poly_pts.append([p.latitude, p.longitude])

# Draw the Green Safe Zone
folium.Polygon(poly_pts, color='green', fill=True, fill_opacity=0.2, weight=2).add_to(m)

# Draw Red Shadows and Markers for ALL obstacles in vault
for v in st.session_state.vault:
    if v['limit'] < max_ft:
        hw = math.degrees(v['width'] / v['dist']) / 2
        pts = [
            geodesic(feet=v['limit']).destination(st.session_state.center_coord, v['brng']-hw),
            geodesic(feet=v['limit']).destination(st.session_state.center_coord, v['brng']+hw),
            geodesic(feet=max_ft).destination(st.session_state.center_coord, v['brng']+hw),
            geodesic(feet=max_ft).destination(st.session_state.center_coord, v['brng']-hw)
        ]
        folium.Polygon([[p.latitude, p.longitude] for p in pts], color='red', fill=True, fill_opacity=0.4).add_to(m)
    # Add a marker for the object itself
    folium.Marker(v['coords'], icon=folium.Icon(color='orange', icon='tree', prefix='fa')).add_to(m)

folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='blue', icon='house', prefix='fa')).add_to(m)

# --- 5. OUTPUT & INTERACTION ---
out = st_folium(m, width=1100, height=600, key=f"map_v{st.session_state.map_v}")

if out and out.get("last_clicked"):
    clat, clon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    cdist = geodesic(st.session_state.center_coord, (clat, clon)).feet
    det_msl = get_elev_msl(clat, clon)
    st.session_state.last_click = {"lat": clat, "lon": clon, "dist": cdist, "g_msl": det_msl}
    st.rerun()

# List the obstacles for clarity
if st.session_state.vault:
    with st.expander("📝 Current Obstacles"):
        st.table(pd.DataFrame(st.session_state.vault)[['dist', 'brng', 'width', 'limit']])
