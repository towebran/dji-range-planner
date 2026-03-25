import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic

# --- 1. RF PHYSICS (WORST-CASE ENTERPRISE) ---
st.set_page_config(layout="wide", page_title="DJI M4TD Surgical Planner")

TX_EIRP = 33.0        
THRESHOLD_HD = -80.0   # Green: Needs -80dBm for O4 1080p
THRESHOLD_LOST = -92.0 # Red: RTH Trigger
EARTH_K = 1.333        

# State Management
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'vault' not in st.session_state: st.session_state.vault = []
if 'dock_stack' not in st.session_state: st.session_state.dock_stack = {"total_msl": 0.0, "ground": 0.0}

# --- 2. THE SURGICAL ENGINE ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=3).json()
        return float(res.get('value', 900.0))
    except: return 900.0

def calculate_surgical_link(dist_ft, h_tx, h_rx, terrain_msl, obstacles, freq=2.4):
    """
    Advanced Look-Back Logic: 
    Calculates Link Budget + Knife-Edge Diffraction + Foliage Loss.
    """
    dist_km = dist_ft / 3280.84
    dist_mi = dist_ft / 5280.0
    
    # 1. Base Signal (FSPL)
    fspl = 20 * math.log10(max(0.01, dist_km)) + 20 * math.log10(freq) + 92.45
    rssi = TX_EIRP + 3.0 - fspl # EIRP + 4-Ant Array Gain
    
    # 2. Earth Curvature (Added to all obstacles)
    curv_drop = (dist_mi**2) / (1.5 * EARTH_K)
    
    # 3. THE "LOOK-BACK" OBSTRUCTION SCAN
    # We check every manual obstacle you've flagged between the dock and the drone.
    for m in obstacles:
        # Is this obstacle between the dock and the current drone position?
        if m['dist'] < dist_ft:
            # Beam Height at the obstacle's location (Slant Line)
            beam_at_obs = h_tx + (h_rx - h_tx) * (m['dist'] / dist_ft)
            clearance = beam_at_obs - (m['msl'] + curv_drop)
            
            # Fresnel Radius at obstacle
            d1_mi = m['dist'] / 5280.0
            d2_mi = (dist_ft - m['dist']) / 5280.0
            fresnel_r = 72.1 * math.sqrt((d1_mi * d2_mi) / (freq * dist_mi))
            
            # PENALTY LOGIC
            if clearance < (fresnel_r * 0.6): # Fresnel Breach
                if m['type'] == "Solid":
                    # Knife-Edge Diffraction (Lee Model approximation)
                    v = -clearance * math.sqrt(2 / (0.125 * 100))
                    loss = 6.9 + 20 * math.log10(math.sqrt((v-0.1)**2 + 1) + v - 0.1)
                    rssi -= max(20.0, loss) # Solid objects kill signal fast
                else:
                    # Foliage Attenuation (More realistic)
                    rssi -= 15.0 # Average 15dB loss for hitting a tree canopy
            
    if rssi > THRESHOLD_HD: return "#00FF00", 5    # Green
    if rssi > THRESHOLD_LOST: return "#FFA500", 3  # Orange
    return "#FF0000", 2                            # Red

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛡️ Surgical RF Planner")
    
    # STEP 1: DOCK SETTINGS
    st.header("1. Dock Setup")
    d_lat = st.number_input("Lat", value=34.0658, format="%.5f")
    d_lon = st.number_input("Lon", value=-84.6775, format="%.5f")
    if st.button("Fetch Ground MSL"):
        st.session_state.dock_stack['ground'] = get_elev_msl(d_lat, d_lon)
    
    st.write(f"Ground: {st.session_state.dock_stack['ground']} ft")
    b_h = st.number_input("Building Height (ft)", 32.0)
    a_h = st.number_input("Antenna Height (ft)", 15.0)
    st.session_state.dock_stack['total_msl'] = st.session_state.dock_stack['ground'] + b_h + a_h
    
    # STEP 2: OBSTACLE TABLE
    st.divider()
    st.header("2. Manual Obstacles")
    if st.session_state.manual_obs:
        df = pd.DataFrame(st.session_state.manual_obs)
        st.data_editor(df[['id', 'type', 'msl', 'dist']], key="obs_editor")
    
    # STEP 3: MISSION
    st.divider()
    drone_agl = st.selectbox("Drone Alt (ft AGL)", [200, 400])
    clutter = st.slider("Global Tree Buffer (ft)", 0, 100, 80)
    
    if st.button("🚀 RUN SURGICAL SCAN"):
        h_tx = st.session_state.dock_stack['total_msl']
        bearings = [0, 22.5, 45, 67.5, 90, 112.5, 135, 157.5, 180, 202.5, 225, 247.5, 270, 292.5, 315, 337.5]
        new_vault = []
        
        for ang in bearings:
            path = []
            last_coord = [d_lat, d_lon]
            for d in range(800, 20000, 800):
                pt = geodesic(feet=d).destination((d_lat, d_lon), ang)
                cur_ground = get_elev_msl(pt.latitude, pt.longitude)
                h_rx = cur_ground + drone_agl # Terrain Follow
                
                # RUN THE LOOK-BACK ENGINE
                color, weight = calculate_surgical_link(d, h_tx, h_rx, cur_ground + clutter, st.session_state.manual_obs)
                
                path.append({"coords": [last_coord, [pt.latitude, pt.longitude]], "color": color, "weight": weight})
                last_coord = [pt.latitude, pt.longitude]
                if color == "#FF0000": break
            new_vault.append(path)
        st.session_state.vault = new_vault
        st.rerun()

# --- 4. MAP ---
m = folium.Map(location=[d_lat, d_lon], zoom_start=17, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker([d_lat, d_lon], icon=folium.Icon(color='blue')).add_to(m)

for path in st.session_state.vault:
    for seg in path:
        folium.PolyLine(seg['coords'], color=seg['color'], weight=seg['weight']).add_to(m)

st_folium(m, width=1100, height=650)
