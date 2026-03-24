import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import folium_static
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from folium.features import DivIcon
from concurrent.futures import ThreadPoolExecutor

# --- 1. SETTINGS & RF DEFAULTS ---
st.set_page_config(layout="wide", page_title="DJI M4TD Strategic Planner")

# DJI O3 Enterprise / RC Plus 2 Calibration
TX_POWER = 33.0
REQD_SIGNAL = -88.0  # Conservative cutoff for HD video
FREQ = 2.4

# Initialize Persistent State
if 'center' not in st.session_state: st.session_state.center = [33.6644, -84.0113]
if 'vault' not in st.session_state: st.session_state.vault = []
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'city_info' not in st.session_state: st.session_state.city_info = {"name": "None", "poly": None}

# --- 2. THE ENGINE ROOM ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=2).json()
        return float(res.get('value', 900.0))
    except: return 900.0

def get_jurisdiction(lat, lon):
    """Fetches city name and boundary GeoJSON."""
    try:
        geolocator = Nominatim(user_agent="m4td_planner_v2")
        location = geolocator.reverse(f"{lat}, {lon}", exactly_one=True, timeout=5)
        addr = location.raw.get('address', {})
        city = addr.get('city') or addr.get('town') or addr.get('village') or "Unknown"
        
        # Get boundary polygon from Nominatim
        osm_id = location.raw.get('osm_id')
        osm_type = location.raw.get('osm_type')[0].upper()
        poly_url = f"https://nominatim.openstreetmap.org/details?osmtype={osm_type}&osmid={osm_id}&format=json&polygon_geojson=1"
        poly_data = requests.get(poly_url, timeout=5).json()
        return city, poly_data.get('geometry')
    except: return "Area Found", None

def calculate_rssi(dist_ft, h_tx, h_rx, obs_msl):
    """Knife-edge diffraction logic."""
    dist_km = dist_ft / 3280.84
    fspl = 20 * math.log10(max(0.01, dist_km)) + 20 * math.log10(FREQ) + 92.45
    rssi_base = TX_POWER - fspl
    
    # Diffraction Parameter (v)
    mid_dist_m = (dist_ft / 2) * 0.3048
    wavelength = 0.125
    beam_h = h_tx + (h_rx - h_tx) * 0.5
    h_clearance = beam_h - obs_msl
    
    v = -h_clearance * math.sqrt(2 / (wavelength * mid_dist_m))
    # Approximation of Lee's Model
    loss = 0
    if v > -0.7:
        loss = 6.9 + 20 * math.log10(math.sqrt((v-0.1)**2 + 1) + v - 0.1)
        
    return rssi_base - loss

# --- 3. UI ---
with st.sidebar:
    st.header("1. Site Config")
    addr_input = st.text_input("Address / Coordinates", "Crooked Creek, GA")
    ant_h = st.number_input("Antenna AGL (ft)", 35.0)
    drone_h = st.slider("Mission Alt (ft AGL)", 100, 400, 300)
    clutter = st.slider("Tree Canopy Buffer (ft)", 0, 100, 60)
    
    st.header("2. Manual Obstructions")
    m_dist = st.number_input("Dist (ft)", 2000)
    m_h = st.number_input("Obstacle AGL (ft)", 150.0)
    m_dir = st.selectbox("Direction", ["N", "NE", "E", "SE", "S", "SW", "W", "NW"])
    
    if st.button("➕ Add Obstacle"):
        st.session_state.manual_obs.append({"dist": m_dist, "agl": m_h, "dir": m_dir})
        st.toast("Obstacle Added")

    if st.button("🚀 RUN FULL ASSESSMENT"):
        with st.spinner("Analyzing Site..."):
            # A. Geocode
            g_url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={addr_input}&maxLocations=1"
            res = requests.get(g_url).json()
            if res.get('candidates'):
                loc = res['candidates'][0]['location']
                st.session_state.center = [loc['y'], loc['x']]
                
                # B. Jurisdiction
                name, poly = get_jurisdiction(loc['y'], loc['x'])
                st.session_state.city_info = {"name": name, "poly": poly}
                
                # C. RF Scan
                dock_g = get_elev_msl(loc['y'], loc['x'])
                h_tx = dock_g + ant_h + 15
                h_rx = dock_g + drone_h
                
                new_vault = []
                bearings = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}
                for b_name, ang in bearings.items():
                    # Scan every 1,500ft
                    limit = 18480
                    for d in range(1500, 18501, 1500):
                        pt = geodesic(feet=d).destination(st.session_state.center, ang)
                        ground = get_elev_msl(pt.latitude, pt.longitude)
                        obs_total = ground + clutter
                        
                        # Apply Manual Overrides
                        for m_ob in st.session_state.manual_obs:
                            if m_ob['dir'] == b_name and abs(m_ob['dist'] - d) < 750:
                                obs_total = max(obs_total, ground + m_ob['agl'])
                        
                        rssi = calculate_rssi(d, h_tx, h_rx, obs_total)
                        if rssi < REQD_SIGNAL:
                            limit = d
                            break
                    new_vault.append({"brng": ang, "limit": limit, "name": b_name})
                st.session_state.vault = new_vault
                st.success("Scan Complete")

    if st.button("🚨 RESET"):
        st.session_state.vault = []
        st.session_state.manual_obs = []
        st.rerun()

# --- 4. THE MAP ---
st.subheader(f"Jurisdiction: {st.session_state.city_info['name']}")

m = folium.Map(location=st.session_state.center, zoom_start=13, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

# City Limits
if st.session_state.city_info['poly']:
    folium.GeoJson(st.session_state.city_info['poly'], 
                   style_function=lambda x: {'color': 'yellow', 'fillColor': 'yellow', 'fillOpacity': 0.1}).add_to(m)

# Rings & Labels
for mi in [1, 2, 3]:
    folium.Circle(st.session_state.center, radius=mi*1609.34, color='white', weight=1, opacity=0.3).add_to(m)
    folium.Marker(geodesic(miles=mi).destination(st.session_state.center, 45),
                  icon=DivIcon(html=f'<div style="color:white; font-size:10px;">{mi}mi</div>')).add_to(m)

# Home Marker
folium.Marker(st.session_state.center, icon=folium.Icon(color='blue', icon='home')).add_to(m)

# Safe Zone
if st.session_state.vault:
    poly_pts = []
    for a in range(0, 361, 10):
        closest = min(st.session_state.vault, key=lambda x: abs(x['brng'] - a))
        p = geodesic(feet=closest['limit']).destination(st.session_state.center, a)
        poly_pts.append([p.latitude, p.longitude])
    folium.Polygon(poly_pts, color='#00FF00', fill=True, fill_opacity=0.2).add_to(m)

# Manual Obstacles
for o in st.session_state.manual_obs:
    ang = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}[o['dir']]
    p = geodesic(feet=o['dist']).destination(st.session_state.center, ang)
    folium.Marker([p.latitude, p.longitude], icon=folium.Icon(color='orange', icon='warning')).add_to(m)

folium_static(m, width=1100, height=600)
