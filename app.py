import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon
from fpdf import FPDF

# --- 1. RF CONSTANTS (DJI O4/O3 ENTERPRISE SPECS) ---
st.set_page_config(layout="wide", page_title="M4TD Range Planner")

TX_EIRP = 33.0        # Max FCC EIRP (dBm)
RX_SENSITIVITY = -95.0 # Conservative DJI Threshold
FADE_MARGIN = 12.0     # Required Link Margin
THRESHOLD = RX_SENSITIVITY + FADE_MARGIN # -83.0 dBm Target
EARTH_K = 1.333        # 4/3 Earth Radius for Refraction

# --- 2. THE CORE ENGINE ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=3).json()
        return float(res.get('value', 900.0))
    except: return 900.0

def check_link_viability(dist_ft, h_tx, h_rx, obs_msl, freq_ghz):
    """Calculates LOS, Fresnel, and Link Margin."""
    dist_km = dist_ft / 3280.84
    dist_mi = dist_ft / 5280.0
    
    # 1. Path Loss (FSPL)
    fspl = 20 * math.log10(max(0.01, dist_km)) + 20 * math.log10(freq_ghz) + 92.45
    rssi = TX_EIRP - fspl
    
    # 2. Earth Curvature Drop (ft)
    # drop = (d^2) / (1.5 * K)
    curv_drop = (dist_mi**2) / (1.5 * EARTH_K)
    
    # 3. First Fresnel Zone Radius (ft) at midpoint
    # r = 72.1 * sqrt( (d1*d2) / (f*D) )
    fresnel_r = 72.1 * math.sqrt( ((dist_mi/2) * (dist_mi/2)) / (freq_ghz * dist_mi) )
    fresnel_60 = fresnel_r * 0.60
    
    # 4. Line of Sight Math
    beam_h = h_tx + (h_rx - h_tx) * 0.5 # Elevation of signal at midpoint
    effective_obs = obs_msl + curv_drop + fresnel_60
    
    is_viable = (rssi >= THRESHOLD) and (beam_h > effective_obs)
    return is_viable, rssi

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛡️ M4TD Tactical Planner")
    
    # DOCK SETUP
    if not st.session_state.get('dock_confirmed'):
        st.header("Phase 1: Dock Setup")
        query = st.text_input("Address or Lat, Lon", "Acworth, GA")
        if st.button("📍 Locate Dock"):
            # (Standard ArcGIS Geocode Logic)
            st.session_state.dock_confirmed = False # Placeholder for rerender
            st.rerun()
        
        d_ground = get_elev_msl(st.session_state.center[0], st.session_state.center[1])
        d_bldg = st.number_input("Dock Building Height (ft)", 20.0)
        d_ant = st.number_input("Antenna Mast Height (ft)", 15.0)
        st.session_state.dock_msl = d_ground + d_bldg + d_ant
        
        if st.button("✅ Confirm Dock"):
            st.session_state.dock_confirmed = True
            st.rerun()
    
    # SCAN PHASE
    else:
        st.header("Phase 2: Site Survey")
        drone_alt = st.slider("Drone Mission Alt (ft AGL)", 100, 400, 200)
        clutter_ft = st.slider("Global Clutter (Trees/Bldg)", 0, 100, 50)
        
        if st.button("🚀 RUN ACCURACY SCAN"):
            h_tx = st.session_state.dock_msl
            h_rx = (h_tx - d_bldg - d_ant) + drone_alt
            
            bearings = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}
            scan_results = []
            
            for name, ang in bearings.items():
                max_usable_range = 0
                limit_point = None
                confidence = "High (Manual)" if any(o['dir'] == name for o in st.session_state.manual_obs) else "Medium (DEM)"
                
                # Sample every 500ft per coworker request for resolution
                for d in range(500, 31681, 500):
                    pt = geodesic(feet=d).destination(st.session_state.center, ang)
                    ground = get_elev_msl(pt.latitude, pt.longitude)
                    
                    # Obstacle logic (Public DEM + Clutter)
                    obs_msl = ground + clutter_ft
                    
                    # Overwrite with Manual Building data if exists
                    for m in st.session_state.manual_obs:
                        if m['dir'] == name and abs(m['dist'] - d) < 400:
                            obs_msl = m['msl']
                            confidence = "High (Verified)"

                    viable, rssi = check_link_viability(d, h_tx, h_rx, obs_msl, 2.4)
                    
                    if not viable:
                        limit_point = {"coords": [pt.latitude, pt.longitude], "dist": d}
                        break
                    max_usable_range = d
                
                scan_results.append({
                    "Direction": name,
                    "Max Range (mi)": round(max_usable_range/5280, 2),
                    "Confidence": confidence,
                    "Limit Reason": "Terrain/Obstruction" if limit_point else "Max Budget",
                    "Limit Lat/Lon": f"{limit_point['coords'][0]:.4f}, {limit_point['coords'][1]:.4f}" if limit_point else "N/A"
                })
            st.session_state.vault = scan_results
            st.rerun()

# --- 4. MAP & REPORT ---
st.subheader("Interactive LOS & Fresnel Analysis")
if st.session_state.vault:
    st.table(pd.DataFrame(st.session_state.vault))

m = folium.Map(location=st.session_state.center, zoom_start=15, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

# Draw Rings & Resulting Web
if st.session_state.vault:
    poly_pts = []
    for res in st.session_state.vault:
        ang = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}[res['Direction']]
        p = geodesic(miles=res['Max Range (mi)']).destination(st.session_state.center, ang)
        poly_pts.append([p.latitude, p.longitude])
        
        # Mark the "Limiting Obstruction" in Red
        if res['Limit Lat/Lon'] != "N/A":
            folium.Marker(list(map(float, res['Limit Lat/Lon'].split(','))), 
                          icon=folium.Icon(color='red', icon='warning'),
                          tooltip=f"Limit: {res['Direction']}").add_to(m)

    folium.Polygon(poly_pts, color='cyan', fill=True, fill_opacity=0.2).add_to(m)

st_folium(m, width=1100, height=600)
