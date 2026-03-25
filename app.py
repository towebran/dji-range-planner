import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
import random

# --- 1. SETTINGS ---
st.set_page_config(layout="wide", page_title="DJI M4TD Fast Planner")

# Initialize State
if 'center' not in st.session_state: st.session_state.center = [33.6644, -84.0113]
if 'dock_confirmed' not in st.session_state: st.session_state.dock_confirmed = False
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'vault' not in st.session_state: st.session_state.vault = []
if 'map_key' not in st.session_state: st.session_state.map_key = "start"

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
        st.header("Step 1: Set Dock")
        query = st.text_input("Enter Address or Lat/Lon", "4415 Center Street, Acworth, GA")
        
        if st.button("📍 Jump to Site"):
            # Search Logic
            if "," in query:
                try:
                    lat, lon = map(float, query.split(","))
                    st.session_state.center = [lat, lon]
                except: st.error("Use format: 34.0, -84.6")
            else:
                url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={query}&maxLocations=1"
                res = requests.get(url).json()
                if res.get('candidates'):
                    loc = res['candidates'][0]['location']
                    st.session_state.center = [loc['y'], loc['x']]
                else: st.error("Location not found.")
            
            # FORCE MAP RELOAD
            st.session_state.map_key = f"map_{random.randint(0,999)}"
            st.rerun()
        
        st.divider()
        ground = get_elev_msl(st.session_state.center[0], st.session_state.center[1])
        st.write(f"**Site Ground:** {int(ground)}' MSL")
        
        b_h = st.number_input("Building Height (ft)", 32)
        a_h = st.number_input("Antenna Height (ft)", 15)
        st.session_state.dock_msl = ground + b_h + a_h
        st.success(f"**Total Dock Tip:** {int(st.session_state.dock_msl)}' MSL")
        
        if st.button("✅ Confirm Dock & Start Survey"):
            st.session_state.dock_confirmed = True
            st.rerun()
    
    else:
        st.header("Step 2: Obstacle Survey")
        # EDITABLE TABLE
        if st.session_state.manual_obs:
            df = pd.DataFrame(st.session_state.manual_obs)
            edited_df = st.data_editor(
                df[['id', 'type', 'msl', 'dist']],
                column_config={
                    "type": st.column_config.SelectboxColumn("Type", options=["Tree", "Solid"]),
                    "msl": st.column_config.NumberColumn("MSL Height (ft)"),
                    "dist": st.column_config.NumberColumn("Dist (ft)", disabled=True)
                },
                hide_index=True,
                key="obs_table"
            )
            # Sync edits
            for i, row in edited_df.iterrows():
                st.session_state.manual_obs[i]['msl'] = row['msl']
                st.session_state.manual_obs[i]['type'] = row['type']
        
        if st.button("🚨 Reset All"):
            st.session_state.manual_obs = []
            st.session_state.vault = []
            st.session_state.dock_confirmed = False
            st.rerun()

        st.divider()
        st.header("Step 3: RF Scan")
        drone_agl = st.selectbox("Drone Mission Alt (ft AGL)", [200, 400])
        clutter = st.slider("Global Clutter Buffer (ft)", 0, 100, 60)
        
        if st.button("🚀 RUN 8-DIRECTION SCAN"):
            with st.spinner("Processing..."):
                h_tx = st.session_state.dock_msl
                # 8 Directions for speed and clarity
                bearings = [0, 45, 90, 135, 180, 225, 270, 315] 
                st.session_state.vault = []
                
                for ang in bearings:
                    path = []
                    last_coord = st.session_state.center
                    # Scan out 3.5 miles (18,480ft) in 1000ft increments
                    for d in range(1000, 19000, 1000):
                        pt = geodesic(feet=d).destination(st.session_state.center, ang)
                        cur_g = get_elev_msl(pt.latitude, pt.longitude)
                        
                        # Simplified Terrain Follow Logic
                        h_rx = cur_g + drone_agl
                        is_blocked = False
                        
                        # Check manual flags along this specific radial
                        for m in st.session_state.manual_obs:
                            # If flag is between dock and drone and is taller than beam
                            if m['dist'] < d:
                                # Slope: h_tx (dock) to h_rx (drone)
                                beam_at_obs = h_tx + (h_rx - h_tx) * (m['dist'] / d)
                                if m['msl'] > beam_at_obs:
                                    is_blocked = True
                        
                        # Check Global Clutter
                        if (cur_g + clutter) > h_rx: is_blocked = True
                        
                        color = "#FF0000" if is_blocked else "#00FF00"
                        path.append({"coords": [last_coord, [pt.latitude, pt.longitude]], "color": color})
                        last_coord = [pt.latitude, pt.longitude]
                        if is_blocked: break
                    st.session_state.vault.append(path)
                st.rerun()

# --- 4. THE MAP ---
# Force map re-center using session center and unique key
m = folium.Map(
    location=st.session_state.center, 
    zoom_start=18, 
    tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', 
    attr='Google'
)

# Dock Home
folium.Marker(st.session_state.center, icon=folium.Icon(color='blue', icon='home')).add_to(m)

# Draw Paths
for path in st.session_state.vault:
    for seg in path:
        folium.PolyLine(seg['coords'], color=seg['color'], weight=5).add_to(m)

# Draw Numbered Flags
for ob in st.session_state.manual_obs:
    c = "green" if ob['type'] == "Tree" else "red"
    folium.Marker(
        ob['coords'], 
        icon=folium.DivIcon(html=f'<div style="background:{c}; border-radius:50%; width:24px; height:24px; color:white; text-align:center; font-weight:bold; border:2px solid white; line-height:24px;">{ob["id"]}</div>')
    ).add_to(m)

# Render
out = st_folium(
    m, 
    width=1000, 
    height=600, 
    center=st.session_state.center, 
    key=st.session_state.map_key
)

# Click logic (Survey Mode Only)
if out and out.get("last_clicked") and st.session_state.dock_confirmed:
    lat, lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    dist = geodesic(st.session_state.center, (lat, lon)).feet
    new_id = len(st.session_state.manual_obs) + 1
    # Add obstacle to state
    st.session_state.manual_obs.append({
        "id": new_id, 
        "coords": [lat, lon], 
        "msl": get_elev_msl(lat, lon) + 50, # Default +50ft clutter
        "type": "Tree", 
        "dist": int(dist)
    })
    st.rerun()
