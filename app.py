import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon
from fpdf import FPDF # Requires fpdf2 in requirements.txt

# --- 1. RF PHYSICS (O4 ENTERPRISE CALIBRATION) ---
st.set_page_config(layout="wide", page_title="DJI Dock 3 Strategic Planner")

TX_EIRP = 33.0        
RX_SENSITIVITY = -95.0 
FADE_MARGIN = 12.0     
THRESHOLD = RX_SENSITIVITY + FADE_MARGIN 
EARTH_K = 1.333        

# Initialize Session State
if 'center' not in st.session_state: st.session_state.center = [34.065, -84.677]
if 'dock_confirmed' not in st.session_state: st.session_state.dock_confirmed = False
if 'dock_stack' not in st.session_state: st.session_state.dock_stack = {"b_height": 0.0, "ant_h": 15.0, "total_msl": 0.0}
if 'vault' not in st.session_state: st.session_state.vault = []
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'staged_obs' not in st.session_state: st.session_state.staged_obs = None
if 'map_v' not in st.session_state: st.session_state.map_v = 1

# --- 2. ENGINES ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=3).json()
        return float(res.get('value', 900.0))
    except: return 900.0

def calculate_link(dist_ft, h_tx, h_rx, obs_msl, freq_ghz):
    dist_km = dist_ft / 3280.84
    dist_mi = dist_ft / 5280.0
    fspl = 20 * math.log10(max(0.01, dist_km)) + 20 * math.log10(freq_ghz) + 92.45
    rssi = TX_EIRP + 3.0 - fspl # +3dB for Dock 3 Antenna Array
    
    curv_drop = (dist_mi**2) / (1.5 * EARTH_K)
    fresnel_r = 72.1 * math.sqrt(((dist_mi/2)**2) / (freq_ghz * dist_mi))
    fresnel_60 = fresnel_r * 0.60
    
    beam_h = h_tx + (h_rx - h_tx) * (dist_ft / max(dist_ft, 19000)) # Simple slope
    is_viable = (rssi >= THRESHOLD) and (beam_h > (obs_msl + curv_drop + fresnel_60))
    
    color = "#00FF00" if is_viable else "#FF0000"
    return is_viable, rssi, color

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛡️ Dock 3 Site Survey")
    
    if not st.session_state.dock_confirmed:
        st.header("Phase 1: Dock Setup")
        query = st.text_input("Find Site", "4415 Center Street, Acworth, GA")
        if st.button("📍 Locate & Zero Dock"):
            arc_url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={query}&maxLocations=1"
            res = requests.get(arc_url).json()
            if res.get('candidates'):
                loc = res['candidates'][0]['location']
                st.session_state.center = [loc['y'], loc['x']]
                st.session_state.map_v += 1
                st.rerun()
        
        d_ground = get_elev_msl(st.session_state.center[0], st.session_state.center[1])
        d_bldg = st.number_input("Dock Building Height (ft AGL)", 0.0)
        d_ant = st.number_input("Antenna Mast Height (ft)", 15.0)
        st.session_state.dock_stack['total_msl'] = d_ground + d_bldg + d_ant
        
        if st.button("✅ Confirm Dock"):
            st.session_state.dock_confirmed = True
            st.rerun()
    else:
        st.header("Phase 2: Survey")
        # DUAL BAND TOGGLE
        freq = st.radio("Frequency Band", [2.4, 5.8], help="5.8GHz has a smaller Fresnel zone but less range.")
        drone_h = st.slider("Drone Alt (ft AGL)", 100, 400, 200)
        clutter = st.slider("Global Clutter (ft)", 0, 100, 50)
        
        if st.session_state.staged_obs:
            st.info("Edit Obstacle MSL")
            new_msl = st.number_input("Top MSL", value=st.session_state.staged_obs['ground']+50)
            if st.button("✔️ Lock"):
                st.session_state.staged_obs['msl'] = new_msl
                st.session_state.manual_obs.append(st.session_state.staged_obs)
                st.session_state.staged_obs = None
                st.rerun()

        if st.button("🚀 RUN ACCURACY SCAN"):
            h_tx = st.session_state.dock_stack['total_msl']
            h_rx = (h_tx - d_bldg - d_ant) + drone_h
            bearings = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}
            new_vault = []
            for name, ang in bearings.items():
                path = []
                last_coord = st.session_state.center
                for d in range(800, 25000, 800):
                    pt = geodesic(feet=d).destination(st.session_state.center, ang)
                    ground = get_elev_msl(pt.latitude, pt.longitude)
                    obs = ground + clutter
                    for m_ob in st.session_state.manual_obs:
                        if m_ob['dir'] == name and abs(m_ob['dist'] - d) < 600:
                            obs = m_ob['msl']
                    
                    viable, rssi, color = calculate_link(d, h_tx, h_rx, obs, freq)
                    path.append({"coords": [last_coord, [pt.latitude, pt.longitude]], "color": color})
                    last_coord = [pt.latitude, pt.longitude]
                    if not viable: break
                new_vault.append(path)
            st.session_state.vault = new_vault
            st.rerun()

# --- 4. MAP ---
m = folium.Map(location=st.session_state.center, zoom_start=18, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center, icon=folium.Icon(color='blue', icon='home')).add_to(m)

for path in st.session_state.vault:
    for seg in path:
        folium.PolyLine(seg['coords'], color=seg['color'], weight=4).add_to(m)

out = st_folium(m, width=1100, height=600, key=f"v{st.session_state.map_v}")

if out and out.get("last_clicked") and st.session_state.dock_confirmed:
    lat, lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    st.session_state.staged_obs = {"ground": get_elev_msl(lat, lon), "dist": geodesic(st.session_state.center, (lat, lon)).feet, "dir": "N", "coords": [lat, lon]}
    st.rerun()
