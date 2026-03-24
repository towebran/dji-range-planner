import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import folium_static
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from folium.features import DivIcon

# --- 1. SETTINGS & RF PHYSICS ---
st.set_page_config(layout="wide", page_title="DJI M4TD Strategic Planner")

TX_POWER = 33.0     # DJI O3 Max EIRP (dBm)
REQD_SIGNAL = -88.0 # Cutoff for HD video
FREQ = 2.4          
D_STEP = 800        # Distance between samples (ft) - Adjusted for speed

# Initialize Persistent State
if 'center' not in st.session_state: st.session_state.center = [33.6644, -84.0113]
if 'vault' not in st.session_state: st.session_state.vault = []
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'city_name' not in st.session_state: st.session_state.city_name = "Searching..."

# --- 2. THE ENGINE ROOM ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=2).json()
        return float(res.get('value', 900.0))
    except: return 900.0

def calculate_segment_rf(dist_ft, h_tx, h_rx, obs_msl):
    dist_km = dist_ft / 3280.84
    fspl = 20 * math.log10(max(0.01, dist_km)) + 20 * math.log10(FREQ) + 92.45
    rssi_base = TX_POWER - fspl
    
    mid_dist_m = (dist_ft / 2) * 0.3048
    wavelength = 0.125
    beam_h = h_tx + (h_rx - h_tx) * 0.5
    h_clearance = beam_h - obs_msl
    
    v = -h_clearance * math.sqrt(2 / (wavelength * mid_dist_m))
    loss = 0
    if v > -0.7:
        loss = 6.9 + 20 * math.log10(math.sqrt((v-0.1)**2 + 1) + v - 0.1)
    
    final_rssi = rssi_base - loss
    if final_rssi > -80: return "#00FF00", 4, "Solid"    
    if final_rssi > -88: return "#FFA500", 3, "Degraded" 
    return "#FF0000", 2, "Lost"                        

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.header("1. Site Configuration")
    addr_input = st.text_input("Address", "Crooked Creek, GA")
    ant_h = st.number_input("Antenna AGL (ft)", 35.0)
    drone_h = st.slider("Mission Alt (ft AGL)", 100, 400, 300)
    clutter = st.slider("Tree Canopy (ft)", 0, 100, 60)
    
    st.header("2. Manual Overrides")
    m_dist = st.number_input("Dist (ft)", 2500)
    m_h = st.number_input("Obs Height AGL (ft)", 150.0)
    m_dir = st.selectbox("Direction", ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"])
    
    if st.button("➕ Add Manual Obs"):
        st.session_state.manual_obs.append({"dist": m_dist, "agl": m_h, "dir": m_dir})
        st.toast("Obstacle Added")

    if st.button("🚀 RUN STRATEGIC SCAN"):
        with st.spinner("Executing 16-Direction Multi-Path Scan..."):
            # A. Geocode & City
            g_url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={addr_input}&maxLocations=1"
            res = requests.get(g_url).json()
            if res.get('candidates'):
                loc = res['candidates'][0]['location']
                st.session_state.center = [loc['y'], loc['x']]
                
                try:
                    geolocator = Nominatim(user_agent="m4td_planner_v4")
                    location = geolocator.reverse(f"{loc['y']}, {loc['x']}", timeout=3)
                    st.session_state.city_name = location.raw.get('address', {}).get('city', "Area Found")
                except: st.session_state.city_name = "Area Found"
                
                # B. Origin Setup
                dock_g = get_elev_msl(loc['y'], loc['x'])
                h_tx, h_rx = dock_g + ant_h + 15, dock_g + drone_h
                
                # C. 16 Direction Scan
                bearings = {
                    "N":0, "NNE":22.5, "NE":45, "ENE":67.5, "E":90, "ESE":112.5, "SE":135, "SSE":157.5,
                    "S":180, "SSW":202.5, "SW":225, "WSW":247.5, "W":270, "WNW":292.5, "NW":315, "NNW":337.5
                }
                new_vault = []
                for name, ang in bearings.items():
                    path_segments = []
                    last_coord = st.session_state.center
                    for d in range(D_STEP, 19000, D_STEP):
                        pt = geodesic(feet=d).destination(st.session_state.center, ang)
                        this_coord = [pt.latitude, pt.longitude] # STRICT LIST FORMAT
                        ground = get_elev_msl(pt.latitude, pt.longitude)
                        obs_total = ground + clutter
                        
                        for m_ob in st.session_state.manual_obs:
                            if m_ob['dir'] == name and abs(m_ob['dist'] - d) < (D_STEP/2 + 100):
                                obs_total = max(obs_total, ground + m_ob['agl'])
                        
                        color, weight, status = calculate_segment_rf(d, h_tx, h_rx, obs_total)
                        path_segments.append({"coords": [last_coord, this_coord], "color": color, "weight": weight})
                        last_coord = this_coord
                        if status == "Lost": break 
                    new_vault.append(path_segments)
                st.session_state.vault = new_vault

# --- 4. MAP RENDERING ---
st.subheader(f"Jurisdiction: {st.session_state.city_name}")
m = folium.Map(location=st.session_state.center, zoom_start=14, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

# Home Point & Rings
folium.Marker(st.session_state.center, tooltip="HOME (DOCK)", icon=folium.Icon(color='blue', icon='home')).add_to(m)
for mi in [1, 2, 3]:
    folium.Circle(st.session_state.center, radius=mi*1609.34, color='white', weight=1, opacity=0.3).add_to(m)
    p = geodesic(miles=mi).destination(st.session_state.center, 45)
    folium.Marker([p.latitude, p.longitude], icon=DivIcon(html=f'<div style="color:white; font-size:10px; font-weight:bold;">{mi}mi</div>')).add_to(m)

# Draw Paths
if st.session_state.vault:
    for path in st.session_state.vault:
        for seg in path:
            folium.PolyLine(seg['coords'], color=seg['color'], weight=seg['weight'], opacity=0.8).add_to(m)

# Draw Manual Obs
for o in st.session_state.manual_obs:
    bearings = {"N":0, "NNE":22.5, "NE":45, "ENE":67.5, "E":90, "ESE":112.5, "SE":135, "SSE":157.5,
                "S":180, "SSW":202.5, "SW":225, "WSW":247.5, "W":270, "WNW":292.5, "NW":315, "NNW":337.5}
    p = geodesic(feet=o['dist']).destination(st.session_state.center, bearings[o['dir']])
    folium.Marker([p.latitude, p.longitude], tooltip=f"OBS: {o['agl']}ft AGL", icon=folium.Icon(color='orange', icon='warning')).add_to(m)

folium_static(m, width=1100, height=650)
