import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon
import random

# --- 1. RF CONFIG ---
st.set_page_config(layout="wide", page_title="DJI M4TD Tactical Planner")
TX_EIRP = 33.0        
THRESHOLD_LOST = -92.0 
EARTH_K = 1.333        

# State Initialization
for key, val in {
    'center': [34.065, -84.677],
    'dock_confirmed': False,
    'dock_stack': {"b_height": 32.0, "ant_h": 15.0, "total_msl": 0.0, "ground": 0.0},
    'vault': [],
    'poly_coords': [],
    'manual_obs': [],
    'map_key': "init_37"
}.items():
    if key not in st.session_state: st.session_state[key] = val

# --- 2. ENGINES ---
@st.cache_data(ttl=3600)
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=3).json()
        return float(res.get('value', 900.0))
    except: return 900.0

def calculate_recovery_link(dist_ft, h_tx, h_rx, obstacles, clutter_ft):
    dist_mi = dist_ft / 5280.0
    dist_km = dist_ft / 3280.84
    curv_drop = (dist_mi**2) / (1.5 * EARTH_K)
    
    # Base O4 Signal
    fspl = 20 * math.log10(max(0.01, dist_km)) + 20 * math.log10(2.4) + 92.45
    rssi = TX_EIRP + 4.0 - fspl 
    
    path_penalty = 0
    # Check current "String" for obstructions
    for m in obstacles:
        if m['dist'] < dist_ft:
            # Beam height at the obstacle's location
            beam_at_obs = h_tx + (h_rx - h_tx) * (m['dist'] / dist_ft)
            if beam_at_obs < (m['msl'] + curv_drop):
                # Apply penalty based on type
                path_penalty += (18.0 if m['type'] == "Tree" else 35.0)
                
    final_rssi = rssi - path_penalty
    color = "#00FF00" if final_rssi > -82 else "#FFA500" if final_rssi > THRESHOLD_LOST else "#FF0000"
    return color, 5 if color == "#00FF00" else 3

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛡️ M4TD Tactical Planner")
    
    if not st.session_state.dock_confirmed:
        st.header("Step 1: Locate Dock")
        query = st.text_input("Address or Lat, Lon", value="4415 Center Street, Acworth, GA")
        if st.button("📍 Set & Jump"):
            if "," in query:
                lat, lon = map(float, query.split(","))
                st.session_state.center = [lat, lon]
            else:
                res = requests.get(f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={query}&maxLocations=1").json()
                if res['candidates']:
                    loc = res['candidates'][0]['location']
                    st.session_state.center = [loc['y'], loc['x']]
            st.session_state.map_key = f"map_{random.randint(0,999)}"
            st.rerun()
            
        d_ground = get_elev_msl(st.session_state.center[0], st.session_state.center[1])
        b_h = st.number_input("Building Height (ft)", value=32.0)
        a_h = st.number_input("Antenna Height (ft)", value=15.0)
        st.session_state.dock_stack = {"total_msl": d_ground + b_h + a_h, "ground": d_ground}
        if st.button("✅ Confirm Dock Location"):
            st.session_state.dock_confirmed = True; st.rerun()
    else:
        st.header("Step 2: Obstacle Survey")
        if st.button("🚨 RELOCATE DOCK / CLEAR"):
            st.session_state.manual_obs, st.session_state.vault, st.session_state.dock_confirmed = [], [], False
            st.rerun()

        # FIXED DATA EDITOR WITH SELECTBOX
        if st.session_state.manual_obs:
            df = pd.DataFrame(st.session_state.manual_obs)
            edited = st.data_editor(
                df[['id', 'type', 'msl', 'dist']], 
                column_config={
                    "type": st.column_config.SelectboxColumn(
                        "Obstruction Type",
                        help="Tree = Signal penetrates with loss. Solid = Total blockage.",
                        options=["Tree", "Solid"],
                        required=True,
                    ),
                    "msl": st.column_config.NumberColumn("Top MSL (ft)"),
                    "dist": st.column_config.NumberColumn("Dist (ft)", disabled=True)
                },
                hide_index=True,
                key="obs_editor_v37"
            )
            # Update session state with edits
            for i, row in edited.iterrows():
                st.session_state.manual_obs[i].update(row)

        st.divider()
        drone_agl = st.selectbox("Drone Mission Alt (ft AGL)", [200, 400])
        clutter = st.slider("Global Tree Buffer (ft)", 0, 100, 80)
        
        if st.button("🚀 RUN RECOVERY SCAN"):
            with st.spinner("Analyzing Path Recovery..."):
                h_tx = st.session_state.dock_stack['total_msl']
                st.session_state.vault, st.session_state.poly_coords = [], []
                for ang in [0, 22.5, 45, 67.5, 90, 112.5, 135, 157.5, 180, 202.5, 225, 247.5, 270, 292.5, 315, 337.5]:
                    path, last_coord, max_d = [], st.session_state.center, 0
                    for d in range(800, 20000, 800):
                        pt = geodesic(feet=d).destination(st.session_state.center, ang)
                        cur_g = get_elev_msl(pt.latitude, pt.longitude)
                        # LINK RECOVERY CHECK
                        color, weight = calculate_recovery_link(d, h_tx, cur_g + drone_agl, st.session_state.manual_obs, clutter)
                        path.append({"coords": [last_coord, [pt.latitude, pt.longitude]], "color": color, "weight": weight})
                        last_coord, max_d = [pt.latitude, pt.longitude], d
                        # We don't 'break' here because we want to see if signal recovers further out
                    st.session_state.vault.append(path)
                    st.session_state.poly_coords.append({"coord": last_coord, "dist": max_d})
                st.rerun()

# --- 4. MAP ---
m = folium.Map(location=st.session_state.center, zoom_start=18, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center, icon=folium.Icon(color='blue', icon='home')).add_to(m)

for path in st.session_state.vault:
    for seg in path:
        folium.PolyLine(seg['coords'], color=seg['color'], weight=seg['weight'], opacity=0.7).add_to(m)

for ob in st.session_state.manual_obs:
    c = "green" if ob['type'] == "Tree" else "red"
    folium.Marker(ob['coords'], icon=folium.DivIcon(html=f'<div style="background-color:{c}; border-radius:50%; width:22px; height:22px; color:white; border:2px solid white; text-align:center; font-weight:bold; line-height:22px;">{ob["id"]}</div>')).add_to(m)

out = st_folium(m, center=st.session_state.center, key=st.session_state.map_key, width=1100, height=650)

if out and out.get("last_clicked") and st.session_state.dock_confirmed:
    lat, lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    st.session_state.manual_obs.append({
        "id": len(st.session_state.manual_obs)+1, 
        "coords": [lat, lon], 
        "msl": get_elev_msl(lat, lon)+50, 
        "type": "Tree", 
        "dist": int(geodesic(st.session_state.center, (lat, lon)).feet)
    })
    st.rerun()
