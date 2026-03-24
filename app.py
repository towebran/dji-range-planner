import streamlit as st
import folium, requests
from streamlit_folium import st_folium
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DJI M4TD Pro Planner")

# --- 1. THE VAULT (SESSION STATE) ---
dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

# Initialize the Vault if it doesn't exist
if 'vault' not in st.session_state:
    st.session_state.vault = {d: {"dist": 150.0, "h": 60.0} for d in dirs}
if 'center_coord' not in st.session_state:
    st.session_state.center_coord = [33.66, -84.01]
if 'last_click_dist' not in st.session_state:
    st.session_state.last_click_dist = 0.0

# --- 2. FUNCTIONS ---
def search_addr():
    if st.session_state.addr_search_box:
        try:
            loc = Nominatim(user_agent="dji_vault_v10").geocode(st.session_state.addr_search_box)
            if loc: st.session_state.center_coord = [loc.latitude, loc.longitude]
        except: st.error("Search error.")

def reset_everything():
    st.session_state.vault = {d: {"dist": 150.0, "h": 60.0} for d in dirs}
    st.session_state.center_coord = [33.66, -84.01]
    st.session_state.last_click_dist = 0.0
    st.rerun()

def get_city_limit(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&polygon_geojson=1&zoom=10"
    try:
        res = requests.get(url, headers={'User-Agent': 'DJI_Pro'}).json()
        return res.get('geojson')
    except: return None

# --- 3. UI ---
st.title("📡 DJI Dock 3 / M4TD Pro Site Planner")
st.text_input("Search Address", key="addr_search_box", on_change=search_addr)

with st.sidebar:
    st.header("Site Specs")
    b_h = st.number_input("Building Height (ft)", value=20)
    d_alt = st.slider("Drone Alt (ft AGL)", 100, 400, 200)
    
    st.divider()
    st.subheader("Targeting")
    target_dir = st.selectbox("Assign Click to:", dirs)
    
    # SAVE BUTTON: Writes specifically to the Vault
    if st.button(f"📌 Save {int(st.session_state.last_click_dist)}ft to {target_dir}"):
        st.session_state.vault[target_dir]["dist"] = round(st.session_state.last_click_dist, 1)
        st.success(f"Locked {target_dir}!")

    st.divider()
    st.subheader("Current Vault Data")
    # We display the data as text so the user can't accidentally overwrite it via widgets
    for d in dirs:
        dist_val = st.session_state.vault[d]["dist"]
        h_val = st.session_state.vault[d]["h"]
        cols = st.columns([1,1,1])
        cols[0].write(f"**{d}**")
        # Allow manual height entry that saves to vault
        st.session_state.vault[d]["h"] = cols[1].number_input(f"H", value=h_val, key=f"h_in_{d}", label_visibility="collapsed")
        cols[2].write(f"{int(dist_val)} ft")

    st.divider()
    if st.button("🚨 RESET ALL DATA"):
        reset_everything()

# --- 4. INTERACTIVE SATELLITE MAP ---
st.info(f"Targeting: **{target_dir}** | Click tree on map, then click 'Save' in sidebar.")
m_key = f"m_{st.session_state.center_coord[0]}_{st.session_state.center_coord[1]}"
m = folium.Map(location=st.session_state.center_coord, zoom_start=19, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(m)

out = st_folium(m, width=900, height=500, key=m_key)

if out and out.get("last_clicked"):
    nl, no = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    nd = geodesic(st.session_state.center_coord, (nl, no)).feet
    if nd < 25:
        st.session_state.center_coord = [nl, no]
        st.rerun()
    else:
        st.session_state.last_click_dist = nd
        st.write(f"Detected: **{int(nd)} ft**. Click 'Save' in sidebar to lock it in.")

# --- 5. CALCULATION & RESULTS ---
rf_pts = []
max_ft = 3.5 * 5280
bearings = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}

for d, ang in bearings.items():
    h = st.session_state.vault[d]["h"]
    dist = st.session_state.vault[d]["dist"]
    ant = b_h + 15
    cd = max_ft if h <= ant else ((d_alt - ant) * dist) / (h - ant)
    fd = min(max(cd, dist), max_ft)
    dest = geodesic(feet=fd).destination(st.session_state.center_coord, ang)
    rf_pts.append({"lat": dest.latitude, "lon": dest.longitude, "name": d, "dist": fd})

st.subheader("Final Range & City Jurisdiction")
res_map = folium.Map(location=st.session_state.center_coord, zoom_start=13, control_scale=True)

# Add City Limits
geo = get_city_limit(st.session_state.center_coord[0], st.session_state.center_coord[1])
if geo:
    folium.GeoJson(geo, style_function=lambda x: {'color':'red','fill':None,'dashArray':'5,5','weight':3}).add_to(res_map)

# Add Range Polygon
folium.Polygon([(p['lat'], p['lon']) for p in rf_pts], color="blue", fill=True, opacity=0.2).add_to(res_map)
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(res_map)

for p in rf_pts:
    mi = p['dist'] / 5280
    lbl = f"{mi:.2f} mi" if mi > 0.1 else f"{int(p['dist'])} ft"
    folium.Marker([p['lat'], p['lon']], icon=DivIcon(icon_size=(100,40), icon_anchor=(50,20),
        html=f'<div style="background: white; border: 2px solid blue; border-radius: 5px; color: black; font-weight: bold; font-size: 10px; text-align: center; width: 70px; padding: 2px;">{p["name"]}<br>{lbl}</div>')).add_to(res_map)

st_folium(res_map, width=1100, height=600, key="range_final")
