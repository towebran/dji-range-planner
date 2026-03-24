import streamlit as st
import folium, requests
from streamlit_folium import st_folium
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DJI M4TD Pro Planner")

# --- 1. STATE INITIALIZATION ---
dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

if 'vault' not in st.session_state:
    st.session_state.vault = {d: {"dist": 150.0, "h": 60.0} for d in dirs}
if 'center_coord' not in st.session_state:
    st.session_state.center_coord = [33.66, -84.01]
if 'last_click_dist' not in st.session_state:
    st.session_state.last_click_dist = 0.0

# --- 2. LOGIC FUNCTIONS ---
def search():
    if st.session_state.addr_input:
        try:
            loc = Nominatim(user_agent="dji_pro_manual_math").geocode(st.session_state.addr_input)
            if loc: st.session_state.center_coord = [loc.latitude, loc.longitude]
        except: st.error("Search error.")

def get_city(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&polygon_geojson=1&zoom=10"
    try:
        res = requests.get(url, headers={'User-Agent': 'DJI_Pro'}).json()
        return res.get('geojson')
    except: return None

# --- 3. UI & SIDEBAR ---
st.title("📡 DJI Dock 3 / M4TD Pro Site Planner")
st.text_input("Search Address", key="addr_input", on_change=search)

with st.sidebar:
    st.header("Site Specs")
    b_h = st.number_input("Building Height (ft)", value=20)
    d_alt = st.slider("Drone Alt (ft AGL)", 100, 400, 200)
    
    st.divider()
    st.subheader("Obstruction Targeting")
    target_dir = st.selectbox("Assign to Direction:", dirs)
    
    st.write(f"**Detected Distance:** {int(st.session_state.last_click_dist)} ft")
    
    # MANUAL MATH SECTION
    st.write("---")
    st.write(f"**{target_dir} Tree Height Calc (MSL)**")
    ground_msl = st.number_input("Ground Elevation (MSL)", value=900.0, step=1.0)
    top_msl = st.number_input("Tree Top Elevation (MSL)", value=960.0, step=1.0)
    
    calc_h = top_msl - ground_msl
    st.info(f"Calculated Tree Height: **{int(calc_h)} ft**")

    if st.button(f"📌 Save Data to {target_dir}"):
        st.session_state.vault[target_dir]["dist"] = round(st.session_state.last_click_dist, 1)
        st.session_state.vault[target_dir]["h"] = calc_h
        st.success(f"Saved {target_dir}!")

    st.divider()
    st.subheader("Vault Status")
    for d in dirs:
        v_h = st.session_state.vault[d]["h"]
        v_d = st.session_state.vault[d]["dist"]
        st.write(f"**{d}:** {int(v_h)}ft tree @ {int(v_d)}ft away")

    if st.button("🚨 RESET ALL"):
        st.session_state.vault = {d: {"dist": 150.0, "h": 60.0} for d in dirs}
        st.rerun()

# --- 4. SATELLITE MAP ---
m_k = f"m_{st.session_state.center_coord[0]}_{st.session_state.center_coord[1]}"
m = folium.Map(location=st.session_state.center_coord, zoom_start=19, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(m)

out = st_folium(m, width=900, height=500, key=m_k)

if out and out.get("last_clicked"):
    nl, no = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    nd = geodesic(st.session_state.center_coord, (nl, no)).feet
    if nd < 25:
        st.session_state.center_coord = [nl, no]
        st.rerun()
    else:
        st.session_state.last_click_dist = nd
        st.write(f"Detected: **{int(nd)} ft**. Enter MSL heights in sidebar and click 'Save'.")

# --- 5. RESULTS MAP ---
st.subheader("Final Range & Jurisdiction")
rf_pts = []
max_ft = 3.5 * 5280
bearings = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}

for d, ang in bearings.items():
    h, dist, ant = st.session_state.vault[d]["h"], st.session_state.vault[d]["dist"], b_h + 15
    cd = max_ft if h <= ant else ((d_alt - ant) * dist) / (h - ant)
    fd = min(max(cd, dist), max_ft)
    dest = geodesic(feet=fd).destination(st.session_state.center_coord, ang)
    rf_pts.append({"lat": dest.latitude, "lon": dest.longitude, "name": d, "dist": fd})

res_map = folium.Map(location=st.session_state.center_coord, zoom_start=13, control_scale=True)
geo = get_city(st.session_state.center_coord[0], st.session_state.center_coord[1])
if geo:
    folium.GeoJson(geo, style_function=lambda x: {'color':'red','fill':None,'dashArray':'5,5','weight':3}).add_to(res_map)

folium.Polygon([(p['lat'], p['lon']) for p in rf_pts], color="blue", fill=True, opacity=0.2).add_to(res_map)
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(res_map)

for p in rf_pts:
    mi = p['dist'] / 5280
    lbl = f"{mi:.2f} mi" if mi > 0.1 else f"{int(p['dist'])} ft"
    folium.Marker([p['lat'], p['lon']], icon=DivIcon(icon_size=(100,40), icon_anchor=(50,20),
        html=f'<div style="background: white; border: 2px solid blue; border-radius: 5px; color: black; font-weight: bold; font-size: 10px; text-align: center; width: 70px; padding: 2px;">{p["name"]}<br>{lbl}</div>')).add_to(res_map)

st_folium(res_map, width=1100, height=600, key="range_final")
