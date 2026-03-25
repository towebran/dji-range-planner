import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon
import random

# --- 1. SETTINGS & RF PHYSICS ---
st.set_page_config(layout="wide", page_title="DJI M4TD Tactical Planner")
TX_EIRP = 33.0        
MARGIN_HD = -82.0      
MARGIN_DEGRADED = -90.0 
EARTH_K = 1.333        

# Ensure persistent state
if 'center' not in st.session_state: st.session_state.center = [33.6644, -84.0113]
if 'dock_confirmed' not in st.session_state: st.session_state.dock_confirmed = False
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'vault' not in st.session_state: st.session_state.vault = []
if 'map_key' not in st.session_state: st.session_state.map_key = "init"
if 'dock_msl' not in st.session_state: st.session_state.dock_msl = 950.0

# --- 2. ENGINES ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=2).json()
        return float(res.get('value', 900.0))
    except: return 900.0

def get_signal_color(dist_ft, h_tx, h_rx, obs_msl, manual_hits):
    dist_mi = dist_ft / 5280.0
    dist_km = dist_ft / 3280.84
    curv_drop = (dist_mi**2) / (1.5 * EARTH_K)
    fspl = 20 * math.log10(max(0.01, dist_km)) + 20 * math.log10(2.4) + 92.45
    rssi = TX_EIRP + 3.0 - fspl
    
    for m in manual_hits:
        if m['dist'] < dist_ft:
            beam_at_obs = h_tx + (h_rx - h_tx) * (m['dist'] / dist_ft)
            if (m['msl'] + curv_drop) > beam_at_obs:
                rssi -= (12.0 if m['type'] == "Tree" else 30.0)
    
    if obs_msl > h_rx: rssi -= 20.0
    if rssi > MARGIN_HD: return "#00FF00", 5
    if rssi > MARGIN_DEGRADED: return "#FFA500", 3
    return "#FF0000", 2

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛰️ Tactical Site Survey")
    
    # PERMANENT CONTROLS (Always Visible)
    st.header("Global Mission Settings")
    drone_agl = st.selectbox("Drone Flight Alt (ft AGL)", [200, 400], index=0)
    clutter_h = st.slider("Global Clutter / Avg Tree Height (ft)", 0, 150, 80)
    
    st.divider()

    if not st.session_state.dock_confirmed:
        st.header("Step 1: Locate Dock")
        query = st.text_input("Address or Lat/Lon", "Acworth, GA")
        if st.button("📍 Jump to Site"):
            url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={query}&maxLocations=1"
            res = requests.get(url).json()
            if res.get('candidates'):
                loc = res['candidates'][0]['location']
                st.session_state.center = [loc['y'], loc['x']]
            st.session_state.map_key = f"map_{random.randint(0,999)}"
            st.rerun()
        
        ground = get_elev_msl(st.session_state.center[0], st.session_state.center[1])
        b_h = st.number_input("Building Height (ft)", 32)
        a_h = st.number_input("Antenna Height (ft)", 15)
        st.session_state.dock_msl = ground + b_h + a_h
        
        if st.button("✅ Confirm & Start Survey"):
            st.session_state.dock_confirmed = True
            st.rerun()
    
    else:
        st.header("Step 2: Obstacle Survey")
        if st.session_state.manual_obs:
            df = pd.DataFrame(st.session_state.manual_obs)
            edited_df = st.data_editor(df[['id', 'type', 'msl', 'dist']],
                column_config={"type": st.column_config.SelectboxColumn("Type", options=["Tree", "Solid"]), "dist": st.column_config.NumberColumn("Dist (ft)", disabled=True)},
                hide_index=True, key="obs_table_v36")
            for i, row in edited_df.iterrows():
                st.session_state.manual_obs[i]['msl'] = row['msl']
                st.session_state.manual_obs[i]['type'] = row['type']
        
        if st.button("🚀 RUN 8-DIRECTION SCAN"):
            with st.spinner("Calculating RSSI Decay..."):
                h_tx = st.session_state.dock_msl
                st.session_state.vault = []
                for ang in [0, 45, 90, 135, 180, 225, 270, 315]:
                    path = []
                    last_coord = st.session_state.center
                    for d in range(1500, 21000, 1500):
                        pt = geodesic(feet=d).destination(st.session_state.center, ang)
                        cur_g = get_elev_msl(pt.latitude, pt.longitude)
                        color, weight = get_signal_color(d, h_tx, cur_g + drone_agl, cur_g + clutter_h, st.session_state.manual_obs)
                        path.append({"coords": [last_coord, [pt.latitude, pt.longitude]], "color": color, "weight": weight, "dist": d})
                        last_coord = [pt.latitude, pt.longitude]
                        if color == "#FF0000": break
                    st.session_state.vault.append(path)
                st.rerun()

        if st.button("🚨 Reset All Data"):
            st.session_state.manual_obs, st.session_state.vault, st.session_state.dock_confirmed = [], [], False
            st.session_state.map_key = f"reset_{random.randint(0,999)}"
            st.rerun()

# --- 4. MAP ---
m = folium.Map(location=st.session_state.center, zoom_start=18, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center, icon=folium.Icon(color='blue', icon='home')).add_to(m)

for path in st.session_state.vault:
    for seg in path:
        folium.PolyLine(seg['coords'], color=seg['color'], weight=seg['weight'], opacity=0.8).add_to(m)
    last_seg = path[-1]
    folium.Marker(last_seg['coords'][1], icon=DivIcon(html=f'<div style="color:white; background:rgba(0,0,0,0.6); padding:2px; font-size:10px; border-radius:3px;">{round(last_seg["dist"]/5280, 2)}mi</div>')).add_to(m)

for ob in st.session_state.manual_obs:
    c = "green" if ob['type'] == "Tree" else "red"
    folium.Marker(ob['coords'], icon=folium.DivIcon(html=f'<div style="background:{c}; border-radius:50%; width:24px; height:24px; color:white; text-align:center; font-weight:bold; border:2px solid white; line-height:24px;">{ob["id"]}</div>')).add_to(m)

# RENDER
out = st_folium(m, width=1100, height=650, center=st.session_state.center, key=st.session_state.map_key)

if out and out.get("last_clicked") and st.session_state.dock_confirmed:
    lat, lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    new_id = len(st.session_state.manual_obs) + 1
    st.session_state.manual_obs.append({"id": new_id, "coords": [lat, lon], "msl": get_elev_msl(lat, lon) + clutter_h, "type": "Tree", "dist": int(geodesic(st.session_state.center, (lat, lon)).feet)})
    st.rerun()
