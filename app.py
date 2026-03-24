import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import folium_static
from geopy.distance import geodesic
from folium.features import DivIcon
from concurrent.futures import ThreadPoolExecutor

# --- 1. RF PHYSICS ENGINE (Knife-Edge Diffraction) ---
def get_diffraction_loss(v):
    """Lee's Piecewise Diffraction Model for Knife-Edge Obstacles."""
    if v <= -1: return 0
    if -1 < v <= 0: return 20 * math.log10(0.5 - 0.62 * v)
    if 0 < v <= 1: return 20 * math.log10(0.5 * math.exp(-0.95 * v))
    if 1 < v <= 2.4: return 20 * math.log10(0.4 - math.sqrt(0.1184 - (0.38 - 0.1 * v)**2))
    return 20 * math.log10(0.225 / v)

def calculate_rf_health(dist_ft, h_tx, h_rx, obs_msl):
    """Calculates Path Loss + Diffraction + Earth Curvature."""
    dist_km = dist_ft / 3280.84
    f_ghz = 2.4 # Standard DJI Control/Video Frequency
    
    # 1. Free Space Path Loss (FSPL)
    fspl = 20 * math.log10(max(0.01, dist_km)) + 20 * math.log10(f_ghz) + 92.45
    rssi_base = 33.0 - fspl # 33dBm is DJI FCC Max Power
    
    # 2. Fresnel & Diffraction Parameter (v)
    # v = h * sqrt( (2/lambda) * (1/d1 + 1/d2) )
    mid_dist_km = dist_km / 2
    wavelength = 0.125 # 2.4GHz in meters
    fresnel_r = 17.32 * math.sqrt((mid_dist_km**2)/(f_ghz * dist_km))
    
    # Clearance Height (h)
    beam_h = h_tx + (h_rx - h_tx) * 0.5
    h_clearance = beam_h - obs_msl
    v = -h_clearance * math.sqrt(2 / (wavelength * (mid_dist_km * 1000)))
    
    diff_loss = abs(get_diffraction_loss(v))
    final_rssi = rssi_base - diff_loss
    
    # Status Logic
    if final_rssi > -80: return "Solid", "#00FF00" # Green
    if final_rssi > -92: return "Degraded", "#FFA500" # Orange
    return "Lost", "#FF0000" # Red

# --- 2. DATA FETCHING (Parallel) ---
@st.cache_data(ttl=3600)
def get_elev_bulk(coords):
    def fetch(p):
        try:
            url = f"https://epqs.nationalmap.gov/v1/json?x={p[1]}&y={p[0]}&units=Feet&output=json"
            return float(requests.get(url, timeout=2).json().get('value', 900))
        except: return 900.0
    with ThreadPoolExecutor(max_workers=10) as ex:
        return list(ex.map(fetch, coords))

# --- 3. APP UI ---
st.set_page_config(layout="wide")
st.title("🛡️ DJI M4TD Strategic RF Survey")

with st.sidebar:
    addr = st.text_input("Site Address", "Crooked Creek, GA")
    ant_h = st.number_input("Dock Antenna AGL (ft)", 35.0)
    drone_h = st.slider("Mission Alt (ft AGL)", 100, 400, 300)
    clutter = st.slider("Tree Canopy (ft)", 0, 100, 60)
    
    run = st.button("🚀 RUN STRATEGIC SCAN")

# --- 4. SCAN & MAP ---
if 'center' not in st.session_state: st.session_state.center = [33.66, -84.01]
if run:
    g_url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={addr}&maxLocations=1"
    loc = requests.get(g_url).json()['candidates'][0]['location']
    st.session_state.center = [loc['y'], loc['x']]
    
    dock_g = get_elev_bulk([st.session_state.center])[0]
    h_tx = dock_g + ant_h + 15 # 15ft mast
    h_rx = dock_g + drone_h
    
    bearings = {"N":0, "E":90, "S":180, "W":270, "NE":45, "SE":135, "SW":225, "NW":315}
    results = []
    
    m = folium.Map(location=st.session_state.center, zoom_start=13, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
    
    # Label Home Point
    folium.Marker(st.session_state.center, popup="DOCK ORIGIN", icon=folium.Icon(color='blue', icon='home')).add_to(m)

    for name, ang in bearings.items():
        line_pts = [st.session_state.center]
        for d_ft in range(2500, 19000, 2500): # Label points every ~0.5 mi
            pt = geodesic(feet=d_ft).destination(st.session_state.center, ang)
            ground = get_elev_bulk([(pt.latitude, pt.longitude)])[0]
            status, color = calculate_rf_health(d_ft, h_tx, h_rx, ground + clutter)
            
            line_pts.append([pt.latitude, pt.longitude])
            folium.PolyLine(line_pts, color=color, weight=4, opacity=0.8).add_to(m)
            line_pts = [[pt.latitude, pt.longitude]] # Reset for next segment
            
            # Distance Markers
            if ang in [0, 90, 180, 270]: # Only label cardinals to keep map clean
                folium.Marker([pt.latitude, pt.longitude], icon=DivIcon(icon_size=(40,20),
                    html=f'<div style="font-size: 8pt; color: white; background: black; padding: 2px;">{round(d_ft/5280,1)}mi</div>')).add_to(m)

    folium_static(m, width=1100, height=650)
