import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DJI M4TD RF Pro Planner")

# --- 1. SESSION STATE ---
if 'vault' not in st.session_state: st.session_state.vault = []
if 'topo_hits' not in st.session_state: st.session_state.topo_hits = {} 
if 'center_coord' not in st.session_state: st.session_state.center_coord = [33.6644, -84.0113]
if 'last_click' not in st.session_state: st.session_state.last_click = {"lat": 0, "lon": 0, "dist": 0}
if 'map_v' not in st.session_state: st.session_state.map_v = 1

# --- 2. RF & ELEVATION ENGINES ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=3).json()
        return float(res.get('value', 0))
    except: return None

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
        st.session_state.vault = []
        st.session_state.topo_hits = {}
    except: st.error("Invalid Entry.")

# --- 3. UI SIDEBAR ---
st.title("📡 DJI M4TD Surgical RF Planner")

with st.sidebar:
    st.header("1. Deployment Location")
    st.text_input("Address or Lat, Lon:", key="search_input", on_change=handle_search)
    dock_g_msl = st.number_input("Dock Ground MSL (ft)", value=900.0)
    b_h = st.number_input("Building Height (ft)", value=20.0)
    # Total origin including 15ft mast
    ant_msl = dock_g_msl + b_h + 15.0
    st.caption(f"Antenna Origin: **{int(ant_msl)} ft MSL**")
    
    st.header("2. Mission Specs")
    d_alt_agl = st.slider("Mission Alt (ft AGL)", 100, 400, 200)
    drone_target_msl = dock_g_msl + d_alt_agl
    st.caption(f"Drone Target: **{int(drone_target_msl)} ft MSL**")
    
    st.header("3. Terrain Scanning")
    if st.button("📡 SCAN TERRAIN (3.5mi Sweep)"):
        with st.spinner("Analyzing Topography..."):
            new_topo = {}
            for angle in [0, 45, 90, 135, 180, 225, 270, 315]:
                limit = 3.5 * 5280
                for dist in range(1500, int(3.5*5280), 1500):
                    pt = geodesic(feet=dist).destination(st.session_state.center_coord, angle)
                    ground = get_elev_msl(pt.latitude, pt.longitude)
                    if ground:
                        req = ant_msl + ((drone_target_msl - ant_msl) * (dist / (3.5*5280)))
                        # RF Logic: Allow 12ft diffraction buffer even on hills
                        if (ground + 50 - 12) > req: 
                            limit = dist
                            break
                new_topo[angle] = limit
            st.session_state.topo_hits = new_topo
            st.success("Topo Scan Complete!")

    st.header("4. Surgical Obstacle")
    st.write(f"**Click Dist:** {int(st.session_state.last_click['dist'])} ft")
    obs_top_msl = st.number_input("Obstacle Top MSL", value=960.0)
    obs_w = st.number_input("Obstacle Width (ft)", value=100)
    
    if st.button("➕ Block This Wedge"):
        lat1, lon1 = st.session_state.center_coord
        lat2, lon2 = st.session_state.last_click['lat'], st.session_state.last_click['lon']
        dLon = math.radians(lon2 - lon1)
        y = math.sin(dLon) * math.cos(math.radians(lat2))
        x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dLon)
        brng = (math.degrees(math.atan2(y, x)) + 360) % 360
        
        # RF Logic Check for this specific obstacle
        dist = st.session_state.last_click['dist']
        req_at_obs = ant_msl + ((drone_target_msl - ant_msl) * (dist / (3.5*5280)))
        
        # If the obstacle is higher than the signal line minus diffraction...
        if (obs_top_msl - 12) > req_at_obs:
            # We calculate the geometric extension of the shadow
            shadow_range = ((drone_target_msl - ant_msl) / (obs_top_msl - 12 - ant_msl)) * dist
            shadow_range = max(shadow_range, dist)
        else:
            shadow_range = 3.5 * 5280 # Signal clears it!
            
        st.session_state.vault.append({
            "dist": dist, "brng": brng, "width": obs_w, 
            "limit": shadow_range, "coords": [lat2, lon2]
        })
        st.success("Obstacle Processed.")

    if st.button("🚨 RESET ALL"):
        st.session_state.vault = []
        st.session_state.topo_hits = {}
        st.rerun()

# --- 4. MAP & RF GEOMETRY ---
m = folium.Map(location=st.session_state.center_coord, zoom_start=18, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

# RINGS
for mi in [1, 2, 3, 3.5]:
    folium.Circle(location=st.session_state.center_coord, radius=mi*5280*0.3048, color='white', weight=1, opacity=0.3).add_to(m)

# DYNAMIC RF POLYGON
poly_pts = []
max_ft = 3.5 * 5280

for angle in range(0, 362, 5):
    d_limit = max_ft
    
    # 1. Topo Scan Influence
    if st.session_state.topo_hits:
        closest_ang = min(st.session_state.topo_hits.keys(), key=lambda x: abs(x - angle))
        d_limit = min(d_limit, st.session_state.topo_hits[closest_ang])

    # 2. Surgical Obstacle Shadow Influence
    for v in st.session_state.vault:
        angular_width = math.degrees(v['width'] / v['dist'])
        if abs(angle - v['brng']) < (angular_width / 2):
            # The polygon "shrinks" to the calculated RF shadow limit
            d_limit = min(d_limit, v['limit'])
            
    p = geodesic(feet=d_limit).destination(st.session_state.center_coord, angle)
    poly_pts.append([p.latitude, p.longitude])

folium.Polygon(locations=poly_pts, color='green', fill=True, fill_color='green', fill_opacity=0.2, weight=2).add_to(m)

# DRAW RED SHADOWS (Where link is truly lost)
for v in st.session_state.vault:
    if v['limit'] < max_ft:
        hw = math.degrees(v['width'] / v['dist']) / 2
        pts = [
            geodesic(feet=v['limit']).destination(st.session_state.center_coord, v['brng'] - hw),
            geodesic(feet=v['limit']).destination(st.session_state.center_coord, v['brng'] + hw),
            geodesic(feet=max_ft).destination(st.session_state.center_coord, v['brng'] + hw),
            geodesic(feet=max_ft).destination(st.session_state.center_coord, v['brng'] - hw)
        ]
        folium.Polygon(locations=[[p.latitude, p.longitude] for p in pts], color='red', fill=True, fill_opacity=0.4).add_to(m)
        folium.Marker([v['coords'][0], v['coords'][1]], icon=folium.Icon(color='orange', icon='tree', prefix='fa')).add_to(m)

folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='blue', icon='house', prefix='fa')).add_to(m)

# OUTPUT
out = st_folium(m, width=1100, height=600, key=f"map_v{st.session_state.map_v}")

if out and out.get("last_clicked"):
    clat, clon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    cdist = geodesic(st.session_state.center_coord, (clat, clon)).feet
    if cdist > 20:
        st.session_state.last_click = {"lat": clat, "lon": clon, "dist": cdist}
        st.rerun()
