import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic

# --- 1. SETTINGS ---
st.set_page_config(layout="wide", page_title="DJI M4TD Fast Planner")

# Initialize State
if 'center' not in st.session_state: st.session_state.center = [34.065, -84.677]
if 'dock_confirmed' not in st.session_state: st.session_state.dock_confirmed = False
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'vault' not in st.session_state: st.session_state.vault = []
if 'dock_msl' not in st.session_state: st.session_state.dock_msl = 947.0

# --- 2. FAST ELEVATION ENGINE ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=2).json()
        return float(res.get('value', 900.0))
    except: return 900.0

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛰️ Tactical Site Survey")
    
    if not st.session_state.dock_confirmed:
        st.header("1. Set Dock")
        query = st.text_input("Address or Lat/Lon", "Acworth, GA")
        if st.button("📍 Jump to Site"):
            # Simple Geocode
            url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={query}&maxLocations=1"
            res = requests.get(url).json()
            if res.get('candidates'):
                loc = res['candidates'][0]['location']
                st.session_state.center = [loc['y'], loc['x']]
                st.rerun()
        
        ground = get_elev_msl(st.session_state.center[0], st.session_state.center[1])
        b_h = st.number_input("Building Height (ft)", 32)
        a_h = st.number_input("Antenna Height (ft)", 15)
        st.session_state.dock_msl = ground + b_h + a_h
        st.success(f"Dock Tip: {int(st.session_state.dock_msl)}' MSL")
        
        if st.button("✅ Confirm Dock Location"):
            st.session_state.dock_confirmed = True
            st.rerun()
    
    else:
        st.header("2. Obstacle Table")
        if st.session_state.manual_obs:
            df = pd.DataFrame(st.session_state.manual_obs)
            # THIS IS YOUR EDITABLE TABLE
            edited_df = st.data_editor(
                df[['id', 'type', 'msl', 'dist']],
                column_config={
                    "type": st.column_config.SelectboxColumn("Type", options=["Tree", "Solid"]),
                    "msl": st.column_config.NumberColumn("MSL Height"),
                    "dist": st.column_config.NumberColumn("Dist (ft)", disabled=True)
                },
                hide_index=True,
                key="obs_editor"
            )
            # Save edits back to session
            for i, row in edited_df.iterrows():
                st.session_state.manual_obs[i]['msl'] = row['msl']
                st.session_state.manual_obs[i]['type'] = row['type']
        
        if st.button("🚨 Clear / Reset"):
            st.session_state.manual_obs = []
            st.session_state.vault = []
            st.session_state.dock_confirmed = False
            st.rerun()

        st.divider()
        st.header("3. Run Analysis")
        drone_agl = st.selectbox("Flight Alt (ft AGL)", [200, 400])
        clutter = st.slider("Global Clutter (ft)", 0, 100, 80)
        
        if st.button("🚀 SCAN NOW"):
            with st.spinner("Scanning..."):
                h_tx = st.session_state.dock_msl
                bearings = [0, 45, 90, 135, 180, 225, 270, 315] # 8 directions for speed
                st.session_state.vault = []
                for ang in bearings:
                    path = []
                    last_coord = st.session_state.center
                    for d in range(1000, 19000, 1000): # Larger steps for speed
                        pt = geodesic(feet=d).destination(st.session_state.center, ang)
                        g = get_elev_msl(pt.latitude, pt.longitude)
                        # Check if any flag blocks this segment
                        is_blocked = False
                        for m in st.session_state.manual_obs:
                            if m['dist'] < d and m['msl'] > (h_tx + 20): # Basic LOS check
                                is_blocked = True
                        
                        color = "#FF0000" if is_blocked or (g + clutter) > (h_tx + drone_agl) else "#00FF00"
                        path.append({"coords": [last_coord, [pt.latitude, pt.longitude]], "color": color})
                        last_coord = [pt.latitude, pt.longitude]
                        if color == "#FF0000": break
                    st.session_state.vault.append(path)
                st.rerun()

# --- 4. MAP ---
m = folium.Map(location=st.session_state.center, zoom_start=17, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center, icon=folium.Icon(color='blue')).add_to(m)

# Draw Paths
for path in st.session_state.vault:
    for seg in path:
        folium.PolyLine(seg['coords'], color=seg['color'], weight=5).add_to(m)

# Draw Numbered Flags
for ob in st.session_state.manual_obs:
    color = "green" if ob['type'] == "Tree" else "red"
    folium.Marker(
        ob['coords'], 
        icon=folium.DivIcon(html=f'<div style="background:{color}; border-radius:50%; width:25px; height:25px; color:white; text-align:center; font-weight:bold; border:2px solid white;">{ob["id"]}</div>')
    ).add_to(m)

# Capture Clicks
out = st_folium(m, width=1000, height=600, center=st.session_state.center, key="map")

if out and out.get("last_clicked") and st.session_state.dock_confirmed:
    lat, lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    dist = geodesic(st.session_state.center, (lat, lon)).feet
    new_id = len(st.session_state.manual_obs) + 1
    st.session_state.manual_obs.append({
        "id": new_id, "coords": [lat, lon], "msl": get_elev_msl(lat, lon) + 50, "type": "Tree", "dist": int(dist)
    })
    st.rerun()
