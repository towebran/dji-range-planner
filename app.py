import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

# --- 1. SETTINGS & RF PHYSICS ---
st.set_page_config(layout="wide", page_title="DJI M4TD Point-and-Shoot")

TX_POWER = 33.0     
REQD_SIGNAL = -90.0 
FREQ = 2.4          
D_STEP = 800        

# Initialize Session State
if 'center' not in st.session_state: st.session_state.center = [33.6644, -84.0113]
if 'vault' not in st.session_state: st.session_state.vault = []
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'map_v' not in st.session_state: st.session_state.map_v = 1

# --- 2. ENGINES ---
def get_elev_msl(lat, lon):
    """Fetch Topography MSL from USGS."""
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=2).json()
        return float(res.get('value', 900.0))
    except: return 900.0

def calculate_rf(dist_ft, h_tx, h_rx, obs_msl):
    """Lee's Knife-Edge Diffraction Model."""
    dist_km = dist_ft / 3280.84
    fspl = 20 * math.log10(max(0.01, dist_km)) + 20 * math.log10(FREQ) + 92.45
    rssi_base = TX_POWER - fspl
    mid_dist_m = (dist_ft / 2) * 0.3048
    wavelength = 0.125
    beam_h = h_tx + (h_rx - h_tx) * 0.5
    h_clearance = beam_h - obs_msl
    v = -h_clearance * math.sqrt(2 / (wavelength * mid_dist_m))
    loss = 6.9 + 20 * math.log10(math.sqrt((v-0.1)**2 + 1) + v - 0.1) if v > -0.7 else 0
    return rssi_base - loss

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("📡 Site Loadout")
    addr = st.text_input("1. Find Site", "Crooked Creek, GA")
    if st.button("📍 Locate Dock"):
        g_url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={addr}&maxLocations=1"
        res = requests.get(g_url).json()
        if res.get('candidates'):
            loc = res['candidates'][0]['location']
            st.session_state.center = [loc['y'], loc['x']]
            st.session_state.manual_obs = [] # Reset on new site
            st.session_state.vault = []
            st.session_state.map_v += 1
            st.rerun()

    st.divider()
    ant_h = st.number_input("Antenna AGL (ft)", 35.0)
    drone_h = st.slider("Mission Alt (ft AGL)", 100, 400, 300)
    clutter = st.slider("Canopy/Clutter Buffer (ft)", 0, 100, 60)
    
    st.divider()
    st.write("### 🖱️ Click to Add Obstacles")
    if st.session_state.manual_obs:
        st.dataframe(pd.DataFrame(st.session_state.manual_obs)[['dir', 'dist', 'msl']], hide_index=True)
        if st.button("🚨 Clear Marks"):
            st.session_state.manual_obs = []
            st.session_state.vault = []
            st.rerun()

    st.divider()
    if st.button("🚀 RUN STRATEGIC SCAN"):
        with st.spinner("Calculating Multi-Path Link Budget..."):
            dock_g = get_elev_msl(st.session_state.center[0], st.session_state.center[1])
            h_tx, h_rx = dock_g + ant_h + 15, dock_g + drone_h
            
            bearings = {"N":0, "NNE":22.5, "NE":45, "ENE":67.5, "E":90, "ESE":112.5, "SE":135, "SSE":157.5, "S":180, "SSW":202.5, "SW":225, "WSW":247.5, "W":270, "WNW":292.5, "NW":315, "NNW":337.5}
            new_vault = []
            for name, ang in bearings.items():
                path = []
                last_coord = st.session_state.center
                for d in range(D_STEP, 19000, D_STEP):
                    pt = geodesic(feet=d).destination(st.session_state.center, ang)
                    this_coord = [pt.latitude, pt.longitude]
                    
                    # USGS Base + Global Clutter
                    obs_msl = get_elev_msl(pt.latitude, pt.longitude) + clutter
                    
                    # Apply Point-and-Shoot Overrides (Manual MSL)
                    for m in st.session_state.manual_obs:
                        if m['dir'] == name and abs(m['dist'] - d) < (D_STEP/2 + 300):
                            obs_msl = max(obs_msl, m['msl'])
                    
                    final_rssi = calculate_rf(d, h_tx, h_rx, obs_msl)
                    
                    # Color Mapping
                    color = "#00FF00" if final_rssi > -80 else "#FFA500" if final_rssi > -90 else "#FF0000"
                    weight = 5 if color == "#00FF00" else 3
                    
                    path.append({"coords": [last_coord, this_coord], "color": color, "weight": weight})
                    last_coord = this_coord
                    if final_rssi < -95: break # Complete signal blackout
                new_vault.append(path)
            st.session_state.vault = new_vault
            st.rerun()

# --- 4. MAP RENDERING ---
m = folium.Map(location=st.session_state.center, zoom_start=15, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

# Home Point
folium.Marker(st.session_state.center, tooltip="DOCK ORIGIN", icon=folium.Icon(color='blue', icon='home')).add_to(m)

# Draw Scan Results
for path in st.session_state.vault:
    for seg in path:
        folium.PolyLine(seg['coords'], color=seg['color'], weight=seg['weight'], opacity=0.8).add_to(m)

# Draw Clicked Obstacles
for o in st.session_state.manual_obs:
    folium.Marker(o['coords'], tooltip=f"{int(o['msl'])}ft MSL (Manual Mark)", icon=folium.Icon(color='orange', icon='tree', prefix='fa')).add_to(m)

# Distance Rings
for mi in [1, 2, 3]:
    folium.Circle(st.session_state.center, radius=mi*1609.34, color='white', weight=1, opacity=0.3).add_to(m)

# INTERACTION: Capture Map Clicks
out = st_folium(m, width=1100, height=650, key=f"map_v{st.session_state.map_v}")

if out and out.get("last_clicked"):
    c_lat, c_lon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    
    # 1. Calc Distance
    dist = geodesic(st.session_state.center, (c_lat, c_lon)).feet
    
    # 2. Calc Bearing & Snap to 16
    dL = math.radians(c_lon - st.session_state.center[1])
    y = math.sin(dL) * math.cos(math.radians(c_lat))
    x = math.cos(math.radians(st.session_state.center[0])) * math.sin(math.radians(c_lat)) - \
        math.sin(math.radians(st.session_state.center[0])) * math.cos(math.radians(c_lat)) * math.cos(dL)
    brng = (math.degrees(math.atan2(y, x)) + 360) % 360
    directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    snap_dir = directions[int((brng + 11.25) / 22.5) % 16]
    
    # 3. Auto-MSL + Clutter
    with st.spinner("Fetching Lidar Height..."):
        ground = get_elev_msl(c_lat, c_lon)
        auto_msl = ground + clutter # Assumes trees/buildings at that spot
    
    # 4. Save to Loadout
    st.session_state.manual_obs.append({
        "dist": dist, "msl": auto_msl, "dir": snap_dir, "coords": [c_lat, c_lon]
    })
    st.toast(f"Marked {snap_dir} at {int(dist)}ft")
    st.rerun()
