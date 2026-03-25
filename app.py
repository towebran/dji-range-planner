import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

# --- 1. RF CONSTANTS (O4 AUTO-LOGIC) ---
st.set_page_config(layout="wide", page_title="DJI Dock 3 Strategic Planner")

TX_EIRP = 33.0        
RX_SENSITIVITY = -95.0 
FADE_MARGIN = 12.0     
THRESHOLD = RX_SENSITIVITY + FADE_MARGIN # -83.0 dBm
EARTH_K = 1.333        
SURVEY_DIST_FT = 18480 # 3.5 Miles

# Initialize Session State
if 'center' not in st.session_state: st.session_state.center = [33.6644, -84.0113]
if 'dock_confirmed' not in st.session_state: st.session_state.dock_confirmed = False
if 'dock_stack' not in st.session_state: st.session_state.dock_stack = {"b_height": 0.0, "ant_h": 15.0, "total_msl": 0.0}
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

def calculate_auto_link(dist_ft, h_tx, h_rx, obs_msl):
    """Checks 2.4 and 5.8. Returns True if either band is viable."""
    dist_mi = dist_ft / 5280.0
    dist_km = dist_ft / 3280.84
    curv_drop = (dist_mi**2) / (1.5 * EARTH_K)
    beam_h = h_tx + (h_rx - h_tx) * (dist_ft / 19000)
    
    viable_bands = []
    for freq in [2.4, 5.8]:
        # Path Loss
        fspl = 20 * math.log10(max(0.01, dist_km)) + 20 * math.log10(freq) + 92.45
        rssi = TX_EIRP + 3.0 - fspl # +3dB for Pole Array
        
        # Fresnel Clearance
        fresnel_r = 72.1 * math.sqrt(((dist_mi/2)**2) / (freq * dist_mi))
        fresnel_60 = fresnel_r * 0.60
        
        if (rssi >= THRESHOLD) and (beam_h > (obs_msl + curv_drop + fresnel_60)):
            viable_bands.append(freq)
            
    return len(viable_bands) > 0

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛡️ M4TD Tactical Planner")
    
    if not st.session_state.dock_confirmed:
        st.header("📍 Step 1: Set Dock")
        query = st.text_input("Find Site", "4415 Center Street, Acworth, GA")
        if st.button("Search & Center"):
            arc_url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={query}&maxLocations=1"
            res = requests.get(arc_url).json()
            if res.get('candidates'):
                loc = res['candidates'][0]['location']
                st.session_state.center = [loc['y'], loc['x']]
                st.session_state.map_v += 1
                st.rerun()
        
        d_ground = get_elev_msl(st.session_state.center[0], st.session_state.center[1])
        st.write(f"Ground Elevation: **{int(d_ground)} ft MSL**")
        d_bldg = st.number_input("Dock Building Height (ft)", 0.0)
        d_ant = st.number_input("Antenna Height (ft)", 15.0)
        st.session_state.dock_stack['total_msl'] = d_ground + d_bldg + d_ant
        
        if st.button("✅ Confirm Dock & Start Survey"):
            st.session_state.dock_confirmed = True
            st.rerun()
    else:
        st.header("🌳 Step 2: Obstacle Survey")
        st.caption("Click map to add flags. Edit MSL in table.")
        
        if st.session_state.manual_obs:
            df = pd.DataFrame(st.session_state.manual_obs)
            edited_df = st.data_editor(df[['id', 'msl', 'dist']], hide_index=True)
            for i, row in edited_df.iterrows():
                st.session_state.manual_obs[i]['msl'] = row['msl']
        
        if st.button("🚨 Clear All Flags"):
            st.session_state.manual_obs = []
            st.session_state.vault = []
            st.rerun()
        
        st.divider()
        st.header("📡 Step 3: RF Analysis")
        st.info("Mode: **O4 Auto-Frequency**")
        drone_h = st.slider("Mission Alt (ft AGL)", 100, 400, 200)
        clutter = st.slider("Global Clutter (ft)", 0, 100, 50)
        
        if st.button("🚀 RUN STRATEGIC SCAN"):
            with st.spinner("Analyzing Dual-Band Paths..."):
                h_tx = st.session_state.dock_stack['total_msl']
                dock_ground = h_tx - st.session_state.dock_stack['b_height'] - st.session_state.dock_stack['ant_h']
                h_rx = dock_ground + drone_h
                
                bearings = [0, 22.5, 45, 67.5, 90, 112.5, 135, 157.5, 180, 202.5, 225, 247.5, 270, 292.5, 315, 337.5]
                new_vault = []
                for ang in bearings:
                    path = []
                    last_coord = st.session_state.center
                    for d in range(800, 20000, 800):
                        pt = geodesic(feet=d).destination(st.session_state.center, ang)
                        ground = get_elev_msl(pt.latitude, pt.longitude)
                        obs = ground + clutter
                        for m in st.session_state.manual_obs:
                            if geodesic(m['coords'], (pt.latitude, pt.longitude)).feet < 500:
                                obs = max(obs, m['msl'])
                        
                        viable = calculate_auto_link(d, h_tx, h_rx, obs)
                        color = "#00FF00" if viable else "#FF0000"
                        path.append({"coords": [last_coord, [pt.latitude, pt.longitude]], "color": color})
                        last_coord = [pt.latitude, pt.longitude]
                        if not viable: break
                    new_vault.append(path)
                st.session_state.vault = new_vault
                st.rerun()

# --- 4. MAP RENDERING ---
m = folium.Map(location=st.session_state.center, zoom_start=18, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center, icon=folium.Icon(color='blue', icon='home')).add_to(m)

if st.session_state.dock_confirmed:
    bearings = [0, 22.5, 45, 67.5, 90, 112.5, 135, 157.5, 180, 202.5, 225, 247.5, 270, 292.5, 315, 337.5]
    for ang in bearings:
        dest = geodesic(feet=SURVEY_DIST_FT).destination(st.session_state.center, ang)
        folium.PolyLine([st.session_state.center, [dest.latitude, dest.longitude]], color='white', weight=1, opacity=0.4, dash_array='5').add_to(m)

for mi in [1, 2, 3]:
    folium.Circle(st.session_state.center, radius=mi*1609.34, color='white', weight=1, opacity=0.3).add_to(m)

for path in st.session_state.vault:
    for seg in path:
        folium.PolyLine(seg['coords'], color=seg['color'], weight=4, opacity=0.8).add_to(m)

for ob in st.session_state.manual_obs:
    folium.Marker(
        ob['coords'], 
        icon=folium.DivIcon(html=f"""<div style="background-color: orange; border-radius: 50%; width: 25px; height: 25px; display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; border: 2px solid white;">{ob['id']}</div>"""),
        tooltip=f"Flag {ob['id']}"
    ).add_to(m)

out = st_folium(m, width=1100, height=650, key=f"v{st.session_state.map_v}")

if out and out.get("last_clicked"):
    lat, lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    if not st.session_state.dock_confirmed:
        st.session_state.center = [lat, lon]
        st.session_state.map_v += 1
        st.rerun()
    else:
        new_id = len(st.session_state.manual_obs) + 1
        ground = get_elev_msl(lat, lon)
        dist = geodesic(st.session_state.center, (lat, lon)).feet
        st.session_state.manual_obs.append({"id": new_id, "coords": [lat, lon], "msl": ground + 50.0, "dist": int(dist)})
        st.rerun()
