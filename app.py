import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
import random

st.set_page_config(layout="wide", page_title="DJI M4TD Tactical Planner")

# --- 1. SESSION STATE ---
if 'center' not in st.session_state: st.session_state.center = [33.6644, -84.0113]
if 'dock_confirmed' not in st.session_state: st.session_state.dock_confirmed = False
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'vault' not in st.session_state: st.session_state.vault = []
if 'zones' not in st.session_state: st.session_state.zones = {"green": [], "orange": [], "red": []}
if 'map_key' not in st.session_state: st.session_state.map_key = 0

# --- 2. THE "CLEAN JUMP" CALLBACK ---
def handle_search():
    query = st.session_state.search_query
    # 1. Clear OLD scan data so it doesn't ghost on the new map
    st.session_state.vault = []
    st.session_state.zones = {"green": [], "orange": [], "red": []}
    st.session_state.manual_obs = []
    st.session_state.dock_confirmed = False
    
    # 2. Find New Location
    if "," in query:
        try:
            lat, lon = map(float, query.split(","))
            st.session_state.center = [lat, lon]
        except: st.error("Use: 34.1, -84.2")
    else:
        url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={query}&maxLocations=1"
        res = requests.get(url).json()
        if res.get('candidates'):
            loc = res['candidates'][0]['location']
            st.session_state.center = [loc['y'], loc['x']]
    
    # 3. Force map rebuild
    st.session_state.map_key += 1

# --- 3. RF ENGINE ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=2).json()
        return float(res.get('value', 900.0))
    except: return 900.0

def get_signal_rssi(dist_ft, h_tx, h_rx, terrain_msl, manual_hits):
    fspl = 20 * math.log10(max(0.01, dist_ft/3280.84)) + 20 * math.log10(2.4) + 92.45
    rssi = 36.0 - fspl
    for m in manual_hits:
        if m['dist'] < dist_ft:
            beam_at_obs = h_tx + (h_rx - h_tx) * (m['dist'] / dist_ft)
            if m['msl'] > beam_at_obs:
                rssi -= (12.0 if m['type'] == "Tree" else 30.0)
    if terrain_msl > h_rx: rssi -= 20.0
    return rssi

# --- 4. UI SIDEBAR ---
with st.sidebar:
    st.title("🛰️ Tactical Site Survey")
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
        
        if st.button("✅ Confirm Dock Location"):
            st.session_state.dock_confirmed = True
            st.session_state.dock_msl = dock_msl
            st.rerun()
    else:
        st.header("Step 2: Analysis")
        if st.session_state.manual_obs:
            df = pd.DataFrame(st.session_state.manual_obs)
            edited = st.data_editor(df[['id', 'type', 'msl', 'dist']], hide_index=True)
            for i, row in edited.iterrows():
                st.session_state.manual_obs[i]['msl'], st.session_state.manual_obs[i]['type'] = row['msl'], row['type']
        
        if st.button("🚀 SCAN ALL DIRECTIONS"):
            h_tx = st.session_state.dock_msl
            dock_coord = st.session_state.center
            st.session_state.zones = {"green": [], "orange": [], "red": []}
            st.session_state.vault = []
            
            for ang in [0, 45, 90, 135, 180, 225, 270, 315]:
                path = []
                last_coord = dock_coord
                g_pt, o_pt, r_pt = None, None, None
                
                for d in range(1200, 19200, 1200): # Surgical steps
                    pt_raw = geodesic(feet=d).destination(dock_coord, ang)
                    pt = [pt_raw.latitude, pt_raw.longitude]
                    g_val = get_elev_msl(pt[0], pt[1])
                    rssi = get_signal_rssi(d, h_tx, g_val + drone_agl, g_val + clutter_h, st.session_state.manual_obs)
                    
                    color = "#00FF00" if rssi > -82.0 else "#FFA500" if rssi > -90.0 else "#FF0000"
                    weight = 5 if color == "#00FF00" else 3
                    
                    path.append({"coords": [last_coord, pt], "color": color, "weight": weight, "dist": d})
                    last_coord = pt
                    
                    # Store Zone Transitions
                    if rssi > -82.0: g_pt = {"c": pt, "d": d}
                    elif rssi > -90.0: o_pt = {"c": pt, "d": d}
                    else: 
                        r_pt = {"c": pt, "d": d}
                        break
                
                st.session_state.vault.append(path)
                if g_pt: st.session_state.zones['green'].append(g_pt)
                if o_pt: st.session_state.zones['orange'].append(o_pt)
                if r_pt: st.session_state.zones['red'].append(r_pt)
            st.rerun()

        if st.button("🚨 Reset All"):
            st.session_state.manual_obs, st.session_state.vault, st.session_state.zones, st.session_state.dock_confirmed = [], [], {"green":[],"orange":[],"red":[]}, False
            st.session_state.map_key += 1
            st.rerun()

# --- 5. THE MAP ---
m = folium.Map(location=st.session_state.center, zoom_start=18, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center, icon=folium.Icon(color='blue', icon='home')).add_to(m)

# Polygon Shading
for color, zone_key, label_bg in [("#FF0000", 'red', "rgba(255,0,0,0.6)"), ("#FFA500", 'orange', "rgba(255,165,0,0.6)"), ("#00FF00", 'green', "rgba(0,255,0,0.4)")]:
    pts = st.session_state.zones[zone_key]
    if len(pts) > 2:
        folium.Polygon([p['c'] for p in pts], color=color, weight=2, fill=True, fill_opacity=0.15).add_to(m)
        for p in pts:
            folium.Marker(p['c'], icon=folium.features.DivIcon(html=f'<div style="color:white; background:{label_bg}; padding:1px 3px; font-size:9px; border-radius:2px;">{round(p["d"]/5280, 2)}mi</div>')).add_to(m)

for path in st.session_state.vault:
    for seg in path:
        folium.PolyLine(seg['coords'], color=seg['color'], weight=seg['weight'], opacity=0.8).add_to(m)

for ob in st.session_state.manual_obs:
    c = "green" if ob['type'] == "Tree" else "red"
    folium.Marker(ob['coords'], icon=folium.features.DivIcon(html=f'<div style="background:{c}; border-radius:50%; width:22px; height:22px; color:white; text-align:center; font-weight:bold; border:2px solid white; line-height:22px;">{ob["id"]}</div>')).add_to(m)

# FINAL RENDER
out = st_folium(m, width=1100, height=650, center=st.session_state.center, key=f"map_{st.session_state.map_key}")

if out and out.get("last_clicked") and st.session_state.dock_confirmed:
    lat, lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    st.session_state.manual_obs.append({"id": len(st.session_state.manual_obs)+1, "coords": [lat, lon], "msl": get_elev_msl(lat, lon)+clutter_h, "type": "Tree", "dist": int(geodesic(st.session_state.center, (lat, lon)).feet)})
    st.rerun()
