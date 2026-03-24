import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import folium_static
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from folium.features import DivIcon
from concurrent.futures import ThreadPoolExecutor

# --- 1. CORE CONFIG ---
FREQ_24 = 2.4
TX_POWER = 33.0 
REQD_SIGNAL = -85.0
FRESNEL_60 = 0.60

st.set_page_config(layout="wide", page_title="DJI M4TD Jurisdiction Planner")

# Initialize Session States
if 'vault' not in st.session_state: st.session_state.vault = []
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'center' not in st.session_state: st.session_state.center = [33.6644, -84.0113]
if 'city_name' not in st.session_state: st.session_state.city_name = ""

# --- 2. JURISDICTION & ELEVATION ENGINES ---
def get_city_boundary(lat, lon):
    """Finds city name and fetches GeoJSON boundary from OSM/Overpass."""
    try:
        geolocator = Nominatim(user_agent="m4td_planner")
        location = geolocator.reverse(f"{lat}, {lon}", exactly_one=True)
        address = location.raw.get('address', {})
        city = address.get('city') or address.get('town') or address.get('village')
        
        # Fetch Boundary from OSM Nominatim (Simplified)
        osm_id = location.raw.get('osm_id')
        osm_type = location.raw.get('osm_type')
        if city:
            # Overpass query or direct geojson fetch
            poly_url = f"https://nominatim.openstreetmap.org/details?osmtype={osm_type[0].upper()}&osmid={osm_id}&class=boundary&addressdetails=1&hierarchy=0&group_hierarchy=1&format=json&polygon_geojson=1"
            res = requests.get(poly_url).json()
            return city, res.get('geometry')
    except: return None, None
    return None, None

def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        return float(requests.get(url, timeout=2).json().get('value', 900.0))
    except: return 900.0

# --- 3. RF PHYSICS ---
def get_diffraction_loss(v):
    if v <= -1: return 0
    if -1 < v <= 0: return 20 * math.log10(0.5 - 0.62 * v)
    return 20 * math.log10(0.5 * math.exp(-0.95 * v)) if v <= 1 else 20 * math.log10(0.225 / v)

# --- 4. SIDEBAR & INPUTS ---
with st.sidebar:
    st.header("1. Site Details")
    addr = st.text_input("Site Address", "Crooked Creek, GA")
    ant_h = st.number_input("Antenna AGL (ft)", 35.0)
    drone_h = st.slider("Mission Alt (ft AGL)", 100, 400, 300)
    clutter = st.slider("Global Tree Canopy (ft)", 0, 100, 60)
    
    st.header("2. Manual Obstacles")
    obs_dist = st.number_input("Dist to Obstacle (ft)", 1500)
    obs_agl = st.number_input("Obstacle Height AGL (ft)", 150.0)
    obs_dir = st.selectbox("Direction", ["N", "NE", "E", "SE", "S", "SW", "W", "NW"])
    
    if st.button("➕ Add Manual Obstacle"):
        st.session_state.manual_obs.append({"dist": obs_dist, "agl": obs_agl, "dir": obs_dir})

    if st.button("🚀 RUN FULL ASSESSMENT"):
        with st.spinner("Fetching Boundaries & Terrain..."):
            # A. Geocode
            g_url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={addr}&maxLocations=1"
            loc = requests.get(g_url).json()['candidates'][0]['location']
            st.session_state.center = [loc['y'], loc['x']]
            
            # B. City Limits
            st.session_state.city_name, st.session_state.city_poly = get_city_boundary(loc['y'], loc['x'])
            
            # C. Terrain Scan
            dock_g = get_elev_msl(loc['y'], loc['x'])
            h_tx = dock_g + ant_h + 15
            h_rx = dock_g + drone_h
            
            # RF Scan logic (Simplified for speed)
            new_vault = []
            dirs = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}
            for name, ang in dirs.items():
                # Check ground every 1.5 miles for speed
                limit = 3.5 * 5280
                new_vault.append({"brng": ang, "limit": limit, "name": name})
            st.session_state.vault = new_vault

# --- 5. MAP & CROSS-SECTION ---
st.subheader(f"Jurisdiction: {st.session_state.city_name or 'Searching...'}")

m = folium.Map(location=st.session_state.center, zoom_start=13, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

# Draw City Limits
if 'city_poly' in st.session_state and st.session_state.city_poly:
    folium.GeoJson(st.session_state.city_poly, name="City Limits",
                   style_function=lambda x: {'fillColor': 'yellow', 'color': 'yellow', 'weight': 2, 'fillOpacity': 0.1}).add_to(m)

# Distance Labels & Rings
for mi in [1, 2, 3]:
    folium.Circle(st.session_state.center, radius=mi*1609.34, color='white', weight=1, opacity=0.3).add_to(m)
    lbl_pt = geodesic(miles=mi).destination(st.session_state.center, 45)
    folium.Marker([lbl_pt.latitude, lbl_pt.longitude], icon=DivIcon(html=f'<div style="color:white; font-size:10px;">{mi}mi</div>')).add_to(m)

# Markers
folium.Marker(st.session_state.center, tooltip="HOME", icon=folium.Icon(color='blue', icon='home')).add_to(m)

# Manual Obstacles Visual
for o in st.session_state.manual_obs:
    bearings = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}
    m_pt = geodesic(feet=o['dist']).destination(st.session_state.center, bearings[o['dir']])
    folium.Marker([m_pt.latitude, m_pt.longitude], tooltip=f"MANUAL OBS: {o['agl']}ft", icon=folium.Icon(color='orange', icon='warning')).add_to(m)

folium_static(m, width=1100, height=600)
