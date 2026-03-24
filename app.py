import streamlit as st
import folium, requests
from streamlit_folium import st_folium
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DJI M4TD Pro Planner")

# --- 1. PERMANENT STATE MANAGEMENT ---
dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

if 'center_coord' not in st.session_state:
    st.session_state.center_coord = [33.66, -84.01]
if 'last_click_dist' not in st.session_state:
    st.session_state.last_click_dist = 0.0

# Initialize directions in a way that Streamlit widgets won't overwrite
for d in dirs:
    if f"dist_{d}" not in st.session_state: st.session_state[f"dist_{d}"] = 150.0
    if f"h_{d}" not in st.session_state: st.session_state[f"h_{d}"] = 60.0

# --- 2. LOGIC FUNCTIONS ---
def search():
    if st.session_state.addr_input:
        try:
            loc = Nominatim(user_agent="dji_pro_fix").geocode(st.session_state.addr_input)
            if loc: st.session_state.center_coord = [loc.latitude, loc.longitude]
        except: st.error("Search error.")

def get_city(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&polygon_geojson=1&zoom=10"
    try:
        res = requests.get(url, headers={'User-Agent': 'DJI_Pro'}).json()
        return res.get('geojson'), res.get('address', {}).get('city', 'City')
    except: return None, None

# --- 3. SEARCH & SIDEBAR ---
st.title("📡 DJI Dock 3 / M4TD Pro Site Planner")
st.text_input("Search Address", key="addr_input", on_change=search)

with st.sidebar:
    st.header("Site Specs")
    
    # Reset Map View Button
    if st.button("🎯 Fly to Center (Reset Zoom)"):
        st.rerun()
        
    b_h = st.number_input("Bldg Height (ft)", value=20)
    d_alt = st.slider("Drone Alt (ft AGL)", 100, 400, 200)
    
    st.divider()
    target_dir = st.selectbox("Assign Click to:", dirs)
    
    # THE FIX: When clicked, we update the state directly
    if st.button(f"📌 Save {int(st.session_state.last_click_dist)}ft to {target_dir}"):
        st.session_state[f"dist_{target_dir}"] = round(st.session_state.last_click_dist, 1)
        st.rerun()

    st.divider()
    for d in dirs:
        st.write(f"**Direction {d}**")
        cols = st.columns(2)
        # We use 'key' and 'on_change' logic to ensure these stay synced
        st.session_state[f"h_{d}"] = cols[0].number_input(f"H_{d}", value=st.session_state[f"h_{d}"], label_visibility="collapsed")
        st.session_state[f"dist_{d}"] = cols[1].number_input(f"D_{d}", value=st.session_state[f"dist_{d}"], label_visibility="collapsed")
    
    if st.button("🗑️ Clear All Data"):
        for d in dirs:
            st.session_state[f"dist_{d}"] = 150.0
            st.session_state[f"h_{d}"] = 60.0
        st.rerun()

# --- 4. INTERACTIVE SATELLITE MAP ---
st.info(f"Targeting: **{target_dir}** | Click tree, then hit 'Save' in sidebar.")

m_key = f"map_{st.session_state.center_coord[0]}" # Key changes on move to force refresh
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
        st.write(f"Detected: **{int(nd)} ft**. Now click 'Save' in the sidebar.")

# --- 5. FINAL RANGE MAP ---
st.subheader("Final Range & Jurisdiction")
rf_pts = []
max_ft = 3.5 * 5280
bearings = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}

for d, ang in bearings.items():
    h, dist, ant = st.session_state[f"h_{d}"], st.session_state[f"dist_{d}"], b_h + 15
    cd = max_ft if h <= ant else ((d_alt - ant) * dist) / (h - ant)
    fd = min(max(cd, dist), max_ft)
    dest = geodesic(feet=fd).destination(st.session_state.center_coord, ang)
    rf_pts.append({"lat": dest.latitude, "lon": dest.longitude, "name": d, "dist": fd})

res_map = folium.Map(location=st.session_state.center_coord, zoom_start=13, control_scale=True)
geo, cname = get_city(st.session_state.center_coord[0], st.session_state.center_coord[1])
if geo:
    folium.GeoJson(geo, style_function=lambda x: {'color':'red','fill':None,'dashArray':'5,5','weight':3}).add_to(res_map)

folium.Polygon([(p['lat'], p['lon']) for p in rf_pts], color="blue", fill=True, opacity=0.2).add_to(res_map)
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(res_map)

for p in rf_pts:
    mi = p['dist'] / 5280
    lbl = f"{mi:.2f} mi" if mi > 0.1 else f"{int(p['dist'])} ft"
    folium.Marker(
        [p['lat'], p['lon']],
        icon=DivIcon(
            icon_size=(100, 40),
            icon_anchor=(50, 20),
            html=f'<div style="background: white; border: 2px solid blue; border-radius: 5px; color: black; font-weight: bold; font-size: 10px; text-align: center; width: 70px; padding: 2px;">{p["name"]}<br>{lbl}</div>'
        )
    ).add_to(res_map)

st_folium(res_map, width=1100, height=600, key="range_final")
