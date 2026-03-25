import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon
from fpdf import FPDF
from datetime import datetime

# --- 1. SETTINGS & RF ---
st.set_page_config(layout="wide", page_title="DJI M4TD Tactical Planner")
TX_EIRP = 33.0        
THRESHOLD_LOST = -92.0 
EARTH_K = 1.333        

# Initialize Session State
if 'center' not in st.session_state: st.session_state.center = [33.6644, -84.0113]
if 'dock_confirmed' not in st.session_state: st.session_state.dock_confirmed = False
if 'dock_stack' not in st.session_state: st.session_state.dock_stack = {"b_height": 32.0, "ant_h": 15.0, "total_msl": 0.0, "ground": 0.0}
if 'vault' not in st.session_state: st.session_state.vault = []
if 'poly_coords' not in st.session_state: st.session_state.poly_coords = []
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'map_id' not in st.session_state: st.session_state.map_id = 0 # FORCING MAP RESET

# --- 2. ENGINES ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=3).json()
        return float(res.get('value', 900.0))
    except: return 900.0

def calculate_surgical_link(dist_ft, h_tx, h_rx, terrain_msl, obstacles):
    dist_km = dist_ft / 3280.84
    dist_mi = dist_ft / 5280.0
    fspl = 20 * math.log10(max(0.01, dist_km)) + 20 * math.log10(2.4) + 92.45
    rssi = TX_EIRP + 3.0 - fspl
    curv_drop = (dist_mi**2) / (1.5 * EARTH_K)
    
    for m in obstacles:
        if m['dist'] < dist_ft:
            beam_at_obs = h_tx + (h_rx - h_tx) * (m['dist'] / dist_ft)
            clearance = beam_at_obs - (m['msl'] + curv_drop)
            if clearance < 0:
                rssi -= (12.0 if m['type'] == "Tree" else 35.0)
    
    color = "#00FF00" if rssi > -82 else "#FFA500" if rssi > THRESHOLD_LOST else "#FF0000"
    return color, 4 if color == "#00FF00" else 2

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛡️ M4TD Tactical Planner")
    
    # SEARCH & REFINE
    if not st.session_state.dock_confirmed:
        st.header("Step 1: Locate & Refine Dock")
        query = st.text_input("1. Type Address or Lat, Lon", placeholder="Acworth, GA or 34.0, -84.6")
        
        if st.button("📍 Jump to Location"):
            if "," in query:
                try:
                    lat, lon = map(float, query.split(","))
                    st.session_state.center = [lat, lon]
                except: st.error("Invalid Lat/Lon")
            else:
                url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={query}&maxLocations=1"
                res = requests.get(url).json()
                if res.get('candidates'):
                    loc = res['candidates'][0]['location']
                    st.session_state.center = [loc['y'], loc['x']]
                else:
                    st.error("Address not found.")
            
            # FORCE RE-CENTER BY CHANGING MAP ID
            st.session_state.map_id += 1
            st.rerun()
        
        st.info("2. Now **CLICK** the map to refine the Blue Marker exactly.")
        
        # Heights
        d_ground = get_elev_msl(st.session_state.center[0], st.session_state.center[1])
        b_h = st.number_input("Building Height (ft)", value=st.session_state.dock_stack['b_height'])
        a_h = st.number_input("Antenna Height (ft)", value=st.session_state.dock_stack['ant_h'])
        st.session_state.dock_stack = {"b_height": b_h, "ant_h": a_h, "total_msl": d_ground + b_h + a_h, "ground": d_ground}
        
        if st.button("✅ Confirm Dock Location"):
            st.session_state.dock_confirmed = True
            st.rerun()

    else:
        st.header("Step 2: Survey Obstacles")
        if st.button("🚨 CLEAR ALL DATA"):
            st.session_state.manual_obs = []; st.session_state.vault = []; st.session_state.poly_coords = []
            st.session_state.dock_confirmed = False
            st.rerun()
        
        st.divider()
        drone_agl = st.selectbox("Drone Mission Alt (ft AGL)", [200, 400], index=0)
        clutter = st.slider("Global Clutter (ft)", 0, 100, 80)
        
        if st.button("🚀 RUN STRATEGIC SCAN"):
            with st.spinner("Analyzing Paths..."):
                h_tx = st.session_state.dock_stack['total_msl']
                bearings = [0, 22.5, 45, 67.5, 90, 112.5, 135, 157.5, 180, 202.5, 225, 247.5, 270, 292.5, 315, 337.5]
                st.session_state.vault = []; st.session_state.poly_coords = []
                for ang in bearings:
                    path = []; last_coord = st.session_state.center; max_d = 0
                    for d in range(800, 20000, 800):
                        pt = geodesic(feet=d).destination(st.session_state.center, ang)
                        cur_g = get_elev_msl(pt.latitude, pt.longitude)
                        color, weight = calculate_surgical_link(d, h_tx, cur_g + drone_agl, cur_g + clutter, st.session_state.manual_obs)
                        path.append({"coords": [last_coord, [pt.latitude, pt.longitude]], "color": color, "weight": weight})
                        last_coord = [pt.latitude, pt.longitude]; max_d = d
                        if color == "#FF0000": break
                    st.session_state.vault.append(path)
                    st.session_state.poly_coords.append({"coord": last_coord, "dist": max_d})
                st.rerun()

# --- 4. MAP RENDERING ---
m = folium.Map(location=st.session_state.center, zoom_start=18, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', 
               attr='Google')

folium.Marker(st.session_state.center, icon=folium.Icon(color='blue', icon='home')).add_to(m)

# Distance Polygon
if st.session_state.poly_coords:
    folium.Polygon([p['coord'] for p in st.session_state.poly_coords], color="#00FF00", fill=True, fill_opacity=0.2).add_to(m)
    for p in st.session_state.poly_coords:
        folium.Marker(p['coord'], icon=DivIcon(html=f'<div style="color:white; background:rgba(0,0,0,0.6); padding:2px; font-size:10px;">{round(p["dist"]/5280, 2)}mi</div>')).add_to(m)

# Signal Lines
for path in st.session_state.vault:
    for seg in path:
        folium.PolyLine(seg['coords'], color=seg['color'], weight=seg['weight'], opacity=0.8).add_to(m)

# Obstacle Flags
for ob in st.session_state.manual_obs:
    c = "green" if ob['type'] == "Tree" else "red"
    folium.Marker(ob['coords'], icon=folium.DivIcon(html=f"""<div style="background-color:{c}; border-radius:50%; width:25px; height:25px; display:flex; align-items:center; justify-content:center; color:white; font-weight:bold; border:2px solid white;">{ob['id']}</div>""")).add_to(m)

# HANDLE ALL CLICKS
out = st_folium(m, width=1100, height=650, key=f"map_run_{st.session_state.map_id}")

if out and out.get("last_clicked"):
    lat, lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    if not st.session_state.dock_confirmed:
        # STEP 1 REFINEMENT
        st.session_state.center = [lat, lon]
        st.rerun()
    else:
        # STEP 2 OBSTACLE MARKING
        new_id = len(st.session_state.manual_obs) + 1
        st.session_state.manual_obs.append({
            "id": new_id, "coords": [lat, lon], "msl": get_elev_msl(lat, lon) + 50.0, "type": "Tree", 
            "dist": int(geodesic(st.session_state.center, (lat, lon)).feet)
        })
        st.rerun()
