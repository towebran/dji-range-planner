import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

# --- 1. RF CONSTANTS ---
st.set_page_config(layout="wide", page_title="DJI M4TD Terrain Follower")

TX_EIRP = 33.0        
MARGIN_SOLID = -82.0   
MARGIN_DEGRADED = -92.0 
EARTH_K = 1.333        

if 'center' not in st.session_state: st.session_state.center = [33.6644, -84.0113]
if 'dock_confirmed' not in st.session_state: st.session_state.dock_confirmed = False
if 'dock_stack' not in st.session_state: st.session_state.dock_stack = {"b_height": 0.0, "ant_h": 15.0, "total_msl": 0.0, "ground": 0.0}
if 'vault' not in st.session_state: st.session_state.vault = []
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'map_v' not in st.session_state: st.session_state.map_v = 1

# --- 2. ENGINES ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=3).json()
        return float(res.get('value', 900.0))
    except: return 900.0

def get_signal_status(dist_ft, h_tx_msl, drone_agl, current_ground_msl, terrain_obs_msl, manual_hits):
    """
    Calculates signal based on Terrain Following logic.
    h_tx_msl: Fixed Dock Antenna height.
    h_rx_msl: DYNAMIC (Current Ground + Drone AGL).
    """
    dist_mi = dist_ft / 5280.0
    dist_km = dist_ft / 3280.84
    curv_drop = (dist_mi**2) / (1.5 * EARTH_K)
    
    # DYNAMIC DRONE HEIGHT (Terrain Follow)
    h_rx_msl = current_ground_msl + drone_agl
    
    # The signal beam at THIS point in space
    beam_h = h_tx_msl + (h_rx_msl - h_tx_msl) * 0.5 # Simplified midpoint clearance for this segment
    
    best_rssi = -120.0
    for freq in [2.4, 5.8]:
        fspl = 20 * math.log10(max(0.01, dist_km)) + 20 * math.log10(freq) + 92.45
        rssi = TX_EIRP + 3.0 - fspl
        fresnel_r = 72.1 * math.sqrt(((dist_mi/2)**2) / (freq * dist_mi))
        
        # Check if the Obstacle (MSL) pierces the beam
        clearance = h_rx_msl - (terrain_obs_msl + curv_drop)
        
        # Terrain Blockage
        if h_rx_msl < (terrain_obs_msl + curv_drop + (fresnel_r * 0.6)):
            rssi -= 15.0 
            
        # Manual Flag Blockage
        for m in manual_hits:
            m_clearance = h_rx_msl - (m['msl'] + curv_drop)
            if m_clearance < 0: 
                penalty = (12.0 if freq == 2.4 else 22.0) if m['type'] == "Tree" else 30.0
                rssi -= penalty
                    
        if rssi > best_rssi: best_rssi = rssi

    if best_rssi > MARGIN_SOLID: return "#00FF00", 5    
    if best_rssi > MARGIN_DEGRADED: return "#FFA500", 3 
    return "#FF0000", 2                                

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛡️ M4TD Terrain Follower")
    
    if not st.session_state.dock_confirmed:
        st.header("📍 Step 1: Set Dock")
        query = st.text_input("Search Site", "4415 Center Street, Acworth, GA")
        if st.button("Search"):
            arc_url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={query}&maxLocations=1"
            res = requests.get(arc_url).json()
            if res.get('candidates'):
                loc = res['candidates'][0]['location']
                st.session_state.center = [loc['y'], loc['x']]
                st.session_state.map_v += 1
                st.rerun()
        
        d_ground = get_elev_msl(st.session_state.center[0], st.session_state.center[1])
        d_bldg = st.number_input("Dock Building Height (ft)", 0.0)
        d_ant = st.number_input("Antenna Height (ft)", 15.0)
        st.session_state.dock_stack = {"b_height": d_bldg, "ant_h": d_ant, "total_msl": d_ground + d_bldg + d_ant, "ground": d_ground}
        if st.button("✅ Confirm Dock"):
            st.session_state.dock_confirmed = True
            st.rerun()
    else:
        st.header("🌳 Step 2: Survey")
        drone_agl = st.selectbox("Drone Mission Alt (ft AGL)", [200, 400], index=0)
        
        if st.session_state.manual_obs:
            df = pd.DataFrame(st.session_state.manual_obs)
            # Live Clearance: Drone Height (Ground + AGL) - Obstacle MSL
            for i, m in enumerate(st.session_state.manual_obs):
                m_ground = get_elev_msl(m['coords'][0], m['coords'][1])
                st.session_state.manual_obs[i]['clearance'] = int((m_ground + drone_agl) - m['msl'])

            edited_df = st.data_editor(
                df[['id', 'type', 'msl', 'clearance']], 
                column_config={"type": st.column_config.SelectboxColumn("Type", options=["Tree", "Solid"])},
                hide_index=True
            )
            for i, row in edited_df.iterrows():
                st.session_state.manual_obs[i]['msl'] = row['msl']
                st.session_state.manual_obs[i]['type'] = row['type']

        st.divider()
        st.header("📡 Step 3: Analysis")
        clutter = st.slider("Global Clutter (ft)", 0, 100, 50)
        
        if st.button("🚀 RUN TERRAIN-FOLLOW SCAN"):
            with st.spinner("Analyzing Variable Altitude Link..."):
                h_tx = st.session_state.dock_stack['total_msl']
                
                bearings = [0, 22.5, 45, 67.5, 90, 112.5, 135, 157.5, 180, 202.5, 225, 247.5, 270, 292.5, 315, 337.5]
                new_vault = []
                for ang in bearings:
                    path = []
                    last_coord = st.session_state.center
                    for d in range(800, 20000, 800):
                        pt = geodesic(feet=d).destination(st.session_state.center, ang)
                        current_ground = get_elev_msl(pt.latitude, pt.longitude)
                        
                        hits = [m for m in st.session_state.manual_obs if geodesic(m['coords'], (pt.latitude, pt.longitude)).feet < 600]
                        
                        # Logic now uses current_ground to establish drone h_rx
                        color, weight = get_signal_status(d, h_tx, drone_agl, current_ground, current_ground + clutter, hits)
                        path.append({"coords": [last_coord, [pt.latitude, pt.longitude]], "color": color, "weight": weight})
                        last_coord = [pt.latitude, pt.longitude]
                        if color == "#FF0000": break 
                    new_vault.append(path)
                st.session_state.vault = new_vault
                st.rerun()

# --- 4. MAP ---
m = folium.Map(location=st.session_state.center, zoom_start=18, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center, icon=folium.Icon(color='blue', icon='home')).add_to(m)

for path in st.session_state.vault:
    for seg in path:
        folium.PolyLine(seg['coords'], color=seg['color'], weight=seg['weight'], opacity=0.8).add_to(m)

for ob in st.session_state.manual_obs:
    c = "green" if ob['type'] == "Tree" else "red"
    folium.Marker(ob['coords'], icon=folium.DivIcon(html=f"""<div style="background-color: {c}; border-radius: 50%; width: 25px; height: 25px; display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; border: 2px solid white;">{ob['id']}</div>""")).add_to(m)

out = st_folium(m, width=1100, height=650, key=f"v{st.session_state.map_v}")

if out and out.get("last_clicked"):
    lat, lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    if not st.session_state.dock_confirmed:
        st.session_state.center = [lat, lon]
        st.session_state.map_v += 1
        st.rerun()
    else:
        new_id = len(st.session_state.manual_obs) + 1
        st.session_state.manual_obs.append({"id": new_id, "coords": [lat, lon], "msl": get_elev_msl(lat, lon) + 50.0, "type": "Tree", "clearance": 0})
        st.rerun()
