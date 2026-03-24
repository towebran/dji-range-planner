import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DJI M4TD RF Precision Planner")

# --- 1. SESSION STATE (Brain of the App) ---
if 'vault' not in st.session_state: st.session_state.vault = []
if 'center_coord' not in st.session_state: st.session_state.center_coord = [33.6644, -84.0113]
if 'last_click' not in st.session_state: 
    st.session_state.last_click = {"lat": 0, "lon": 0, "dist": 0, "g_msl": 900.0}
if 'map_v' not in st.session_state: st.session_state.map_v = 1

# --- 2. ENGINES ---
def get_elev_msl(lat, lon):
    """Fetch Ground MSL from USGS database."""
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=2).json()
        val = res.get('value')
        if val and val > -1000: return float(val)
    except: pass
    return None

def handle_search():
    """Handles address search or coordinate jump."""
    q = st.session_state.search_input
    if not q: return
    try:
        if "," in q:
            lat, lon = map(float, q.split(","))
            st.session_state.center_coord = [lat, lon]
        else:
            url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={q}&maxLocations=1"
            res = requests.get(url, timeout=5).json()
            if res.get('candidates'):
                loc = res['candidates'][0]['location']
                st.session_state.center_coord = [loc['y'], loc['x']]
        st.session_state.map_v += 1
        st.session_state.vault = [] # Reset obstacles on new site search
    except: st.error("Search Failed. Check format (Address or Lat, Lon).")

# --- 3. UI SIDEBAR ---
st.title("📡 DJI M4TD Surgical RF Precision Planner")

with st.sidebar:
    st.header("1. Deployment Location")
    st.text_input("Address or Lat, Lon:", key="search_input", on_change=handle_search)
    
    # Dock Elevation
    dock_g_msl = st.number_input("Dock Ground MSL (ft)", value=900.0)
    b_h = st.number_input("Building Height (ft)", value=20.0)
    ant_msl = dock_g_msl + b_h + 15.0 # Mast is 15ft
    st.caption(f"Antenna Origin: **{int(ant_msl)} ft MSL**")
    
    st.header("2. Mission Specs")
    d_alt_agl = st.slider("Mission Alt (ft AGL)", 100, 400, 200)
    drone_target_msl = dock_g_msl + d_alt_agl
    st.caption(f"Target Drone: **{int(drone_target_msl)} ft MSL**")
    
    st.header("3. Obstacle Entry")
    click_info = st.session_state.last_click
    st.write(f"**Selected Dist:** {int(click_info['dist'])} ft")
    
    # Auto-MSL Logic
    default_top = (click_info['g_msl'] + 40.0) if click_info['g_msl'] else 940.0
    obs_top_msl = st.number_input("Obstacle Top MSL", value=default_top)
    obs_w = st.number_input("Obstacle Width (ft)", value=100)
    
    if st.button("➕ Block This Wedge"):
        dist = click_info['dist']
        max_range = 3.5 * 5280
        # Calculate LOS Slope
        req_at_obs = ant_msl + ((drone_target_msl - ant_msl) * (dist / max_range))
        
        # RF Shadow Logic (12ft Diffraction Allowance)
        if (obs_top_msl - 12) > req_at_obs:
            # Similar Triangles to find where signal recovers behind obstacle
            shadow_touchdown = ((drone_target_msl - ant_msl) / (obs_top_msl - 12 - ant_msl)) * dist
            shadow_limit = max(shadow_touchdown, dist)
        else:
            shadow_limit = max_range # Clear LOS
            
        # Bearing Calculation
        l1, n1 = st.session_state.center_coord
        l2, n2 = click_info['lat'], click_info['lon']
        dL = math.radians(n2 - n1)
        y = math.sin(dL) * math.cos(math.radians(l2))
        x = math.cos(math.radians(l1)) * math.sin(math.radians(l2)) - math.sin(math.radians(l1)) * math.cos(math.radians(l2)) * math.cos(dL)
        brng = (math.degrees(math.atan2(y, x)) + 360) % 360
        
        st.session_state.vault.append({
            "dist": dist, "brng": brng, "width": obs_w, 
            "limit": shadow_limit, "coords": [l2, n2], "msl": obs_top_msl
        })
        st.success(f"Locked: Obstacle #{len(st.session_state.vault)}")
        st.rerun()

    if st.button("↩️ UNDO LAST"):
        if st.session_state.vault:
            st.session_state.vault.pop()
            st.rerun()

    if st.button("🚨 RESET ALL"):
        st.session_state.vault = []
        st.rerun()

# --- 4. PRECISION MAP ENGINE ---
m = folium.Map(location=st.session_state.center_coord, zoom_start=18, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

max_ft = 3.5 * 5280

# Build angles list (360 degrees + custom surgical wedges)
angles_to_check = list(range(0, 361, 2))
for v in st.session_state.vault:
    hw = math.degrees(v['width'] / v['dist']) / 2
    angles_to_check.extend([v['brng'] - hw, v['brng'], v['brng'] + hw])
angles_to_check = sorted(list(set(angles_to_check)))

# Construct High-Precision Green Safe Zone
poly_pts = []
for angle in angles_to_check:
    d_limit = max_ft
    for v in st.session_state.vault:
        hw = math.degrees(v['width'] / v['dist']) / 2
        if abs(angle - v['brng']) <= hw:
            d_limit = min(d_limit, v['limit'])
    
    p = geodesic(feet=d_limit).destination(st.session_state.center_coord, angle)
    poly_pts.append([p.latitude, p.longitude])

if poly_pts:
    folium.Polygon(poly_pts, color='green', fill=True, fill_opacity=0.25, weight=2).add_to(m)

# Distance Rings
for mi in [1, 2, 3]:
    folium.Circle(location=st.session_state.center_coord, radius=mi*5280*0.3048, color='white', weight=1, opacity=0.3).add_to(m)

# Render Red Dead Zones and Surgical Markers
for v in st.session_state.vault:
    if v['limit'] < max_ft:
        hw = math.degrees(v['width'] / v['dist']) / 2
        pts = [
            geodesic(feet=v['limit']).destination(st.session_state.center_coord, v['brng']-hw),
            geodesic(feet=v['limit']).destination(st.session_state.center_coord, v['brng']+hw),
            geodesic(feet=max_ft).destination(st.session_state.center_coord, v['brng']+hw),
            geodesic(feet=max_ft).destination(st.session_state.center_coord, v['brng']-hw)
        ]
        folium.Polygon([[p.latitude, p.longitude] for p in pts], color='red', fill=True, fill_opacity=0.45, weight=1).add_to(m)
    
    # Orange Marker for the physical object
    folium.Marker(v['coords'], icon=folium.Icon(color='orange', icon='tree', prefix='fa')).add_to(m)

# Dock Location
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='blue', icon='tower-broadcast', prefix='fa')).add_to(m)

# Map Output & Logic
out = st_folium(m, width=1100, height=650, key=f"map_v{st.session_state.map_v}")

if out and out.get("last_clicked"):
    clat, clon = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    cdist = geodesic(st.session_state.center_coord, (clat, clon)).feet
    det_msl = get_elev_msl(clat, clon)
    st.session_state.last_click = {"lat": clat, "lon": clon, "dist": cdist, "g_msl": det_msl}
    st.rerun()

# --- 5. DATA REPORTING ---
if st.session_state.vault:
    st.write("### 📝 Engineering Summary")
    df = pd.DataFrame(st.session_state.vault)[['dist', 'brng', 'width', 'msl', 'limit']]
    df.columns = ["Dist (ft)", "Bearing (°)", "Width (ft)", "Top MSL", "Safe Edge (ft)"]
    st.table(df)
    
    # Export Button
    report_html = f"<h2>DJI M4TD Survey Report</h2><hr>{df.to_html()}"
    st.download_button("📩 Download Survey Report", data=report_html, file_name="DJI_Survey.html", mime="text/html")
