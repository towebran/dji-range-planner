import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import folium_static
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from folium.features import DivIcon

# --- 1. SETTINGS ---
st.set_page_config(layout="wide", page_title="DJI M4TD Strategic Planner")

if 'center' not in st.session_state: st.session_state.center = [33.6644, -84.0113]
if 'vault' not in st.session_state: st.session_state.vault = []
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'city_info' not in st.session_state: st.session_state.city_info = {"name": "Searching...", "poly": None}

# --- 2. ENGINES ---
def get_elev_msl(lat, lon):
    url = f"https://epqs.nationalmap.gov/v1/json?x={lon}&y={lat}&units=Feet&output=json"
    try:
        res = requests.get(url, timeout=2).json()
        return float(res.get('value', 900.0))
    except: return 900.0

def calculate_rssi(dist_ft, h_tx, h_rx, obs_msl):
    dist_km = dist_ft / 3280.84
    fspl = 20 * math.log10(max(0.01, dist_km)) + 20 * math.log10(2.4) + 92.45
    rssi_base = 33.0 - fspl
    mid_dist_m = (dist_ft / 2) * 0.3048
    h_clearance = (h_tx + (h_rx - h_tx) * 0.5) - obs_msl
    v = -h_clearance * math.sqrt(2 / (0.125 * mid_dist_m))
    loss = 6.9 + 20 * math.log10(math.sqrt((v-0.1)**2 + 1) + v - 0.1) if v > -0.7 else 0
    return rssi_base - loss

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.header("1. Site Config")
    addr_input = st.text_input("Address", "Crooked Creek, GA")
    ant_h = st.number_input("Antenna AGL (ft)", 35.0)
    drone_h = st.slider("Mission Alt (ft AGL)", 100, 400, 300)
    clutter = st.slider("Tree Canopy (ft)", 0, 100, 60)
    
    st.header("2. Manual Obstacles")
    m_dist = st.number_input("Dist (ft)", 2000)
    m_h = st.number_input("Obstacle AGL (ft)", 150.0)
    m_dir = st.selectbox("Direction", ["N", "NE", "E", "SE", "S", "SW", "W", "NW"])
    
    if st.button("➕ Add Obstacle"):
        st.session_state.manual_obs.append({"dist": m_dist, "agl": m_h, "dir": m_dir})
        st.toast("Obstacle Added")

    if st.button("🚀 RUN FULL ASSESSMENT"):
        with st.spinner("Analyzing Site..."):
            g_url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?f=json&singleLine={addr_input}&maxLocations=1"
            res = requests.get(g_url).json()
            if res.get('candidates'):
                loc = res['candidates'][0]['location']
                st.session_state.center = [loc['y'], loc['x']]
                
                # Jurisdiction
                try:
                    geo = Nominatim(user_agent="m4td_v3")
                    location = geo.reverse(f"{loc['y']}, {loc['x']}", timeout=3)
                    city = location.raw.get('address', {}).get('city', "Unknown Jurisdiction")
                    st.session_state.city_info = {"name": city, "poly": None}
                except: pass
                
                # RF Scan
                dock_g = get_elev_msl(loc['y'], loc['x'])
                h_tx, h_rx = dock_g + ant_h + 15, dock_g + drone_h
                new_vault = []
                bearings = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}
                for name, ang in bearings.items():
                    limit = 18480
                    for d in range(1500, 18501, 1500):
                        pt = geodesic(feet=d).destination(st.session_state.center, ang)
                        ground = get_elev_msl(pt.latitude, pt.longitude)
                        obs_total = ground + clutter
                        for m_ob in st.session_state.manual_obs:
                            if m_ob['dir'] == name and abs(m_ob['dist'] - d) < 750:
                                obs_total = max(obs_total, ground + m_ob['agl'])
                        if calculate_rssi(d, h_tx, h_rx, obs_total) < -88.0:
                            limit = d; break
                    new_vault.append({"brng": ang, "limit": limit, "name": name})
                st.session_state.vault = new_vault

# --- 4. MAP ---
st.subheader(f"Jurisdiction: {st.session_state.city_info['name']}")
m = folium.Map(location=st.session_state.center, zoom_start=13, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

# Corrected Rings & Labels
for mi in [1, 2, 3]:
    folium.Circle(st.session_state.center, radius=mi*1609.34, color='white', weight=1, opacity=0.3).add_to(m)
    p = geodesic(miles=mi).destination(st.session_state.center, 45)
    folium.Marker([p.latitude, p.longitude], icon=DivIcon(html=f'<div style="color:white; font-size:10px;">{mi}mi</div>')).add_to(m)

folium.Marker(st.session_state.center, icon=folium.Icon(color='blue', icon='home')).add_to(m)

if st.session_state.vault:
    poly_pts = []
    for a in range(0, 361, 10):
        closest = min(st.session_state.vault, key=lambda x: abs(x['brng'] - a))
        p = geodesic(feet=closest['limit']).destination(st.session_state.center, a)
        poly_pts.append([p.latitude, p.longitude])
    folium.Polygon(poly_pts, color='#00FF00', fill=True, fill_opacity=0.2).add_to(m)

folium_static(m, width=1100, height=600)

# --- 5. CROSS-SECTION CHART ---
if st.session_state.vault:
    st.divider()
    st.subheader("📊 Path Profile (Cross-Section)")
    sel_dir = st.selectbox("Select Direction for Profile:", [v['name'] for v in st.session_state.vault])
    
    # Simple profile visualization
    v_data = next(item for item in st.session_state.vault if item["name"] == sel_dir)
    st.info(f"The {sel_dir} path is limited to {round(v_data['limit']/5280, 2)} miles based on current terrain and clutter settings.")
