import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from folium.features import DivIcon

# --- 1. SETTINGS & RF PHYSICS ---
st.set_page_config(layout="wide", page_title="DJI M4TD Strategic Planner")

TX_POWER = 33.0     
REQD_SIGNAL = -90.0 
FREQ = 2.4          
D_STEP = 800        

# Initialize Session State
if 'center' not in st.session_state: st.session_state.center = [33.6644, -84.0113]
if 'vault' not in st.session_state: st.session_state.vault = []
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'staged_obs' not in st.session_state: st.session_state.staged_obs = None
if 'map_v' not in st.session_state: st.session_state.map_v = 1
if 'jurisdiction' not in st.session_state: st.session_state.jurisdiction = {"name": "Unknown Area", "poly": None}

# --- 2. ENGINES ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=2).json()
        return float(res.get('value', 900.0))
    except: return 900.0

def calculate_rf(dist_ft, h_tx, h_rx, obs_msl):
    dist_km = dist_ft / 3280.84
    fspl = 20 * math.log10(max(0.01, dist_km)) + 20 * math.log10(FREQ) + 92.45
    rssi_base = 33.0 - fspl
    mid_dist_m = (dist_ft / 2) * 0.3048
    h_clearance = (h_tx + (h_rx - h_tx) * 0.5) - obs_msl
    v = -h_clearance * math.sqrt(2 / (0.125 * mid_dist_m))
    loss = 6.9 + 20 * math.log10(math.sqrt((v-0.1)**2 + 1) + v - 0.1) if v > -0.7 else 0
    return rssi_base - loss

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛰️ Site Loadout")
    query = st.text_input("1. Find Site (Address or Lat, Lon)", "Crooked Creek, GA")
    
    if st.button("📍 Locate & Fetch Boundary"):
        try:
            if "," in query:
                lat, lon = map(float, query.split(","))
                st.session_state.center = [lat, lon]
            else:
                g_url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={query}&maxLocations=1"
                loc = requests.get(g_url).json()['candidates'][0]['location']
                st.session_state.center = [loc['y'], loc['x']]
            
            # Fetch Boundary Polygon & City Name
            geo = Nominatim(user_agent="m4td_v9")
            res = geo.reverse(st.session_state.center, timeout=3)
            osm_id, osm_type = res.raw.get('osm_id'), res.raw.get('osm_type')[0].upper()
            poly_url = f"https://nominatim.openstreetmap.org/details?osmtype={osm_type}&osmid={osm_id}&format=json&polygon_geojson=1"
            p_res = requests.get(poly_url).json()
            
            st.session_state.jurisdiction = {
                "name": res.raw.get('address', {}).get('city', "Area Found"),
                "poly": p_res.get('geometry')
            }
            st.session_state.map_v += 1
            st.rerun()
        except: st.error("Search failed.")

    st.divider()
    st.header("2. Manual Obstacle")
    if st.session_state.staged_obs:
        st.warning(f"Editing: {st.session_state.staged_obs['dir']} @ {int(st.session_state.staged_obs['dist'])}ft")
        verified_msl = st.number_input("Adjust Top MSL (ft)", value=st.session_state.staged_obs['msl'])
        if st.button("✔️ Lock Obstacle"):
            st.session_state.staged_obs['msl'] = verified_msl
            st.session_state.manual_obs.append(st.session_state.staged_obs)
            st.session_state.staged_obs = None
            st.rerun()
        if st.button("❌ Cancel"):
            st.session_state.staged_obs = None
            st.rerun()
    else: st.caption("Click map to select an obstacle.")

    st.divider()
    ant_h = st.number_input("Antenna AGL (ft)", 35.0)
    drone_h = st.slider("Mission Alt (ft AGL)", 100, 400, 300)
    clutter = st.slider("Global Clutter (ft)", 0, 100, 60)
    
    if st.button("🚀 RUN STRATEGIC SCAN"):
        with st.spinner("Executing 16-Path Analysis..."):
            dock_g = get_elev_msl(st.session_state.center[0], st.session_state.center[1])
            h_tx, h_rx = dock_g + ant_h + 15, dock_g + drone_h
            
            bearings = {"N":0, "NNE":22.5, "NE":45, "ENE":67.5, "E":90, "ESE":112.5, "SE":135, "SSE":157.5, "S":180, "SSW":202.5, "SW":225, "WSW":247.5, "W":270, "WNW":292.5, "NW":315, "NNW":337.5}
            new_vault = []
            for name, ang in bearings.items():
                path = []
                last_coord = st.session_state.center
                for d in range(800, 19000, 800):
                    pt = geodesic(feet=d).destination(st.session_state.center, ang)
                    this_coord = [pt.latitude, pt.longitude]
                    obs_msl = get_elev_msl(pt.latitude, pt.longitude) + clutter
                    for m_ob in st.session_state.manual_obs:
                        if m_ob['dir'] == name and abs(m_ob['dist'] - d) < 600:
                            obs_msl = max(obs_msl, m_ob['msl'])
                    rssi = calculate_rf(d, h_tx, h_rx, obs_msl)
                    color = "#00FF00" if rssi > -80 else "#FFA500" if rssi > -88 else "#FF0000"
                    path.append({"coords": [last_coord, this_coord], "color": color})
                    last_coord = this_coord
                    if rssi < -95: break
                new_vault.append(path)
            st.session_state.vault = new_vault
            st.rerun()

# --- 4. MAP RENDERING ---
st.subheader(f"Jurisdiction: {st.session_state.jurisdiction['name']}")
m = folium.Map(location=st.session_state.center, zoom_start=15, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

# Home Point & Scan Lines
folium.Marker(st.session_state.center, icon=folium.Icon(color='blue', icon='home')).add_to(m)
for path in st.session_state.vault:
    for seg in path:
        folium.PolyLine(seg['coords'], color=seg['color'], weight=4, opacity=0.8).add_to(m)

# 📡 Distance Rings & Labels
for mi in [1, 2, 3]:
    folium.Circle(st.session_state.center, radius=mi*1609.34, color='white', weight=2, fill=False, opacity=0.5).add_to(m)
    p = geodesic(miles=mi).destination(st.session_state.center, 0)
    folium.Marker([p.latitude, p.longitude], icon=DivIcon(html=f'<div style="color:white; font-size:11px; font-weight:bold; background:rgba(0,0,0,0.5); padding:2px; border-radius:3px;">{mi} MILE</div>')).add_to(m)

# 🔴 Jurisdiction Boundary (RED)
if st.session_state.jurisdiction['poly']:
    folium.GeoJson(st.session_state.jurisdiction['poly'], name="City Boundary",
                   style_function=lambda x: {'color': 'red', 'fillColor': 'red', 'weight': 3, 'fillOpacity': 0.1}).add_to(m)

# Locked Obstacles
for o in st.session_state.manual_obs:
    folium.Marker(o['coords'], tooltip=f"VERIFIED: {o['msl']}ft", icon=folium.Icon(color='orange', icon='tree', prefix='fa')).add_to(m)

# INTERACTION
out = st_folium(m, width=1100, height=650, key=f"map_v{st.session_state.map_v}")

if out and out.get("last_clicked"):
    c_lat, c_lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    dist = geodesic(st.session_state.center, (c_lat, c_lon)).feet
    
    # Calc Bearing & Snap
    dL = math.radians(c_lon - st.session_state.center[1])
    y = math.sin(dL) * math.cos(math.radians(c_lat))
    x = math.cos(math.radians(st.session_state.center[0])) * math.sin(math.radians(c_lat)) - \
        math.sin(math.radians(st.session_state.center[0])) * math.cos(math.radians(c_lat)) * math.cos(dL)
    brng = (math.degrees(math.atan2(y, x)) + 360) % 360
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    snap_dir = dirs[int((brng + 11.25) / 22.5) % 16]
    
    st.session_state.staged_obs = {
        "dist": dist, "msl": get_elev_msl(c_lat, c_lon), "dir": snap_dir, "coords": [c_lat, c_lon]
    }
    st.rerun()
