import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
import random

st.set_page_config(layout="wide", page_title="DJI M4TD Tactical Planner")

# --- 1. SESSION STATE INITIALIZATION ---
if 'center' not in st.session_state: st.session_state.center = [33.6644, -84.0113]
if 'dock_confirmed' not in st.session_state: st.session_state.dock_confirmed = False
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'vault' not in st.session_state: st.session_state.vault = []
if 'map_key' not in st.session_state: st.session_state.map_key = 0

# --- 2. CALLBACKS (The Secret to the Map Fix) ---
def handle_search():
    query = st.session_state.search_query
    if "," in query:
        try:
            lat, lon = map(float, query.split(","))
            st.session_state.center = [lat, lon]
        except: st.error("Format error.")
    else:
        url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={query}&maxLocations=1"
        res = requests.get(url).json()
        if res.get('candidates'):
            loc = res['candidates'][0]['location']
            st.session_state.center = [loc['y'], loc['x']]
    # Incrementing the key forces a clean map redraw
    st.session_state.map_key += 1

# --- 3. RF ENGINE ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=2).json()
        return float(res.get('value', 900.0))
    except: return 900.0

def get_signal_color(dist_ft, h_tx, h_rx, terrain_msl, manual_hits):
    dist_mi = dist_ft / 5280.0
    fspl = 20 * math.log10(max(0.01, dist_ft/3280.84)) + 20 * math.log10(2.4) + 92.45
    rssi = 36.0 - fspl # EIRP + Gain
    
    for m in manual_hits:
        if m['dist'] < dist_ft:
            beam_at_obs = h_tx + (h_rx - h_tx) * (m['dist'] / dist_ft)
            if m['msl'] > beam_at_obs:
                rssi -= (12.0 if m['type'] == "Tree" else 30.0)
    
    if terrain_msl > h_rx: rssi -= 20.0
    if rssi > -82.0: return "#00FF00", 5    # Green
    if rssi > -90.0: return "#FFA500", 3    # Orange
    return "#FF0000", 2                    # Red

# --- 4. UI SIDEBAR ---
with st.sidebar:
    st.title("🛰️ Tactical Site Survey")
    
    # GLOBAL CONTROLS
    st.header("Global Settings")
    drone_agl = st.selectbox("Drone Alt (ft AGL)", [200, 400])
    clutter_h = st.slider("Global Clutter (Avg Tree Ht)", 0, 150, 80)
    
    st.divider()

    if not st.session_state.dock_confirmed:
        st.header("Step 1: Set Dock")
        st.text_input("Search Address or Lat, Lon", key="search_query")
        st.button("📍 Jump to Site", on_click=handle_search)
        
        ground = get_elev_msl(st.session_state.center[0], st.session_state.center[1])
        b_h = st.number_input("Bldg Ht (ft)", 32)
        a_h = st.number_input("Ant Ht (ft)", 15)
        dock_msl = ground + b_h + a_h
        st.info(f"Dock Tip: {int(dock_msl)}' MSL")
        
        if st.button("✅ Confirm Dock"):
            st.session_state.dock_confirmed = True
            st.session_state.dock_msl = dock_msl
            st.rerun()
    else:
        st.header("Step 2: Obstacles")
        if st.session_state.manual_obs:
            df = pd.DataFrame(st.session_state.manual_obs)
            edited = st.data_editor(df[['id', 'type', 'msl', 'dist']], hide_index=True)
            for i, row in edited.iterrows():
                st.session_state.manual_obs[i]['msl'] = row['msl']
                st.session_state.manual_obs[i]['type'] = row['type']
        
        if st.button("🚀 SCAN 8-DIRECTIONS"):
            h_tx = st.session_state.dock_msl
            st.session_state.vault = []
            for ang in [0, 45, 90, 135, 180, 225, 270, 315]:
                path = []
                last_coord = st.session_state.center
                for d in range(1500, 19500, 1500):
                    pt = geodesic(feet=d).destination(st.session_state.center, ang)
                    cur_g = get_elev_msl(pt.latitude, pt.longitude)
                    color, weight = get_signal_color(d, h_tx, cur_g + drone_agl, cur_g + clutter_h, st.session_state.manual_obs)
                    path.append({"coords": [last_coord, [pt.latitude, pt.longitude]], "color": color, "weight": weight, "dist": d})
                    last_coord = [pt.latitude, pt.longitude]
                    if color == "#FF0000": break
                st.session_state.vault.append(path)
            st.rerun()

        if st.button("🚨 Reset All"):
            st.session_state.manual_obs, st.session_state.vault, st.session_state.dock_confirmed = [], [], False
            st.session_state.map_key += 1
            st.rerun()

# --- 5. THE MAP ---
m = folium.Map(location=st.session_state.center, zoom_start=18, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center, icon=folium.Icon(color='blue', icon='home')).add_to(m)

for path in st.session_state.vault:
    for seg in path:
        folium.PolyLine(seg['coords'], color=seg['color'], weight=seg['weight']).add_to(m)
    dist_label = f"{round(path[-1]['dist']/5280, 2)}mi"
    folium.Marker(path[-1]['coords'][1], icon=folium.features.DivIcon(html=f'<div style="color:white; background:black; padding:2px; font-size:9px;">{dist_label}</div>')).add_to(m)

for ob in st.session_state.manual_obs:
    c = "green" if ob['type'] == "Tree" else "red"
    folium.Marker(ob['coords'], icon=folium.features.DivIcon(html=f'<div style="background:{c}; border-radius:50%; width:22px; height:22px; color:white; text-align:center; font-weight:bold; border:2px solid white; line-height:22px;">{ob["id"]}</div>')).add_to(m)

# FINAL RENDER
out = st_folium(m, width=1100, height=650, center=st.session_state.center, key=f"map_{st.session_state.map_key}")

if out and out.get("last_clicked") and st.session_state.dock_confirmed:
    lat, lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    st.session_state.manual_obs.append({"id": len(st.session_state.manual_obs)+1, "coords": [lat, lon], "msl": get_elev_msl(lat, lon)+clutter_h, "type": "Tree", "dist": int(geodesic(st.session_state.center, (lat, lon)).feet)})
    st.rerun()
