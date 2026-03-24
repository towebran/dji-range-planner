import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import folium_static
from geopy.distance import geodesic
from folium.features import DivIcon

# --- 1. CONFIG & RF CONSTANTS ---
# Calibrated for DJI O3 Enterprise (M4TD / RC Plus 2)
FREQ_GHZ = 2.4 
TX_POWER_DBM = 33.0     # DJI Max EIRP (FCC)
RX_SENSITIVITY = -95.0  # Threshold for HD Video link
FADE_MARGIN = 10.0      # Required buffer for interference
REQD_SIGNAL = RX_SENSITIVITY + FADE_MARGIN # -85 dBm target
EARTH_RADIUS_KM = 6371 * (4/3) # 4/3 Earth Radius for Refraction

# --- 2. CORE RF PHYSICS ENGINE ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=2).json()
        return float(res.get('value', 900.0))
    except: return 900.0

def calculate_link(dist_ft, h_tx_msl, h_rx_msl, obs_msl):
    """Calculates Path Loss, Fresnel, and Earth Curvature."""
    dist_km = dist_ft / 3280.84
    if dist_km == 0: return 0, True
    
    # 1. Free Space Path Loss (FSPL)
    fspl = 20 * math.log10(dist_km) + 20 * math.log10(FREQ_GHZ) + 92.45
    rssi = TX_POWER_DBM - fspl
    
    # 2. Earth Curvature Drop (ft)
    # drop = (dist_miles^2) / 1.5 (with 4/3 refraction)
    dist_mi = dist_ft / 5280
    curv_drop = (dist_mi**2) / 1.5
    
    # 3. Fresnel Zone Radius (60% clearance)
    # r = 17.32 * sqrt( (d1 * d2) / (f * D) ) in meters
    d1 = dist_km / 2
    fresnel_r_m = 17.32 * math.sqrt((d1 * d1) / (FREQ_GHZ * dist_km))
    fresnel_60_ft = (fresnel_r_m * 3.28084) * 0.60
    
    # 4. Line of Sight Math
    # The signal beam height at this point (Linear slope)
    beam_msl = h_tx_msl + (h_rx_msl - h_tx_msl) * 0.5 # Midpoint for worst Fresnel
    effective_obs = obs_msl + fresnel_60_ft + curv_drop
    
    is_los = beam_msl > effective_obs
    return rssi, is_los

# --- 3. UI LAYOUT ---
st.set_page_config(layout="wide", page_title="M4TD Site Planner")
st.title("🛡️ DJI M4TD Strategic RF & LOS Planner")

with st.sidebar:
    st.header("1. Site Inputs")
    addr = st.text_input("Dock Address / Lat,Lon", "Crooked Creek, GA")
    ant_agl = st.number_input("Antenna Height AGL (ft)", value=35.0)
    drone_alt = st.selectbox("Drone Mission Alt (ft AGL)", [200, 300, 400])
    
    st.header("2. Clutter/Obstacles")
    global_clutter = st.slider("Global Tree/Bldg Height (ft)", 0, 100, 50)
    
    st.subheader("Manual Overrides")
    ov_dir = st.selectbox("Direction", ["N", "E", "S", "W"])
    ov_dist = st.number_input("Dist to Obstacle (ft)", value=2500)
    ov_h = st.number_input("Obstacle Height MSL", value=1050.0)

# --- 4. PROCESSING ---
if 'center' not in st.session_state: st.session_state.center = [33.66, -84.01]
if 'results' not in st.session_state: st.session_state.results = []

if st.button("🚀 Run Cardinal LOS Scan"):
    with st.spinner("Sampling Terrain & Modeling Fresnel Zones..."):
        # Geocode
        g_url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={addr}&maxLocations=1"
        loc = requests.get(g_url).json()['candidates'][0]['location']
        clat, clon = loc['y'], loc['x']
        st.session_state.center = [clat, clon]
        
        dock_g = get_elev_msl(clat, clon)
        h_tx_msl = dock_g + ant_agl
        h_rx_msl = dock_g + drone_alt
        
        final_table = []
        # Scan Cardinal Directions
        bearings = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}
        
        for name, ang in bearings.items():
            max_r = 0
            limit_reason = "Max Range"
            limit_coord = [0,0]
            
            # Sample every 250ft out to 6 miles
            for d_ft in range(250, 31680, 250):
                pt = geodesic(feet=d_ft).destination((clat, clon), ang)
                ground = get_elev_msl(pt.latitude, pt.longitude)
                
                # Apply Clutter
                obs_msl = ground + global_clutter
                
                # Apply Manual Overrides for this direction
                if name == ov_dir and abs(d_ft - ov_dist) < 500:
                    obs_msl = max(obs_msl, ov_h)
                
                rssi, los = calculate_link(d_ft, h_tx_msl, h_rx_msl, obs_msl)
                
                if not los:
                    limit_reason = "LOS/Fresnel Block"
                    limit_coord = [pt.latitude, pt.longitude]
                    break
                if rssi < REQD_SIGNAL:
                    limit_reason = "Signal Decay"
                    limit_coord = [pt.latitude, pt.longitude]
                    break
                max_r = d_ft
            
            final_table.append({
                "Direction": name, 
                "Max Range (mi)": round(max_r/5280, 2),
                "Limit Reason": limit_reason,
                "Coord": limit_coord
            })
        st.session_state.results = final_table

# --- 5. VISUALIZATION ---
m = folium.Map(location=st.session_state.center, zoom_start=13, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

if st.session_state.results:
    poly_pts = []
    for row in st.session_state.results:
        ang = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}[row['Direction']]
        p = geodesic(miles=row['Max Range (mi)']).destination(st.session_state.center, ang)
        poly_pts.append([p.latitude, p.longitude])
        # Add Limit Markers
        if row['Limit Reason'] != "Max Range":
            folium.CircleMarker(row['Coord'], radius=5, color='red', fill=True, popup=row['Direction']).add_to(m)

    folium.Polygon(poly_pts, color='cyan', weight=3, fill=True, fill_opacity=0.2).add_to(m)
    st.table(pd.DataFrame(st.session_state.results))

folium_static(m, width=1100, height=600)
