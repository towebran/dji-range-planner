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
    st.session_state.vault = {d: [] for d in dirs}
if 'center_coord' not in st.session_state:
    st.session_state.center_coord = [33.66, -84.01] # Conyers default
if 'last_click_dist' not in st.session_state:
    st.session_state.last_click_dist = 0.0
if 'map_version' not in st.session_state:
    st.session_state.map_version = 0

# --- 2. SEARCH FUNCTION (FIXED) ---
def search():
    if st.session_state.addr_input:
        try:
            geolocator = Nominatim(user_agent="dji_pro_final_v15")
            location = geolocator.geocode(st.session_state.addr_input)
            if location:
                # Update the coordinates
                st.session_state.center_coord = [location.latitude, location.longitude]
                # BUMP THE VERSION: This forces the map to reset its view to the new center
                st.session_state.map_version += 1
        except:
            st.error("Search failed.")

# --- 3. UI LAYOUT ---
st.title("📡 DJI M4TD Multi-Obstacle Precision Planner")

# Search bar with the fixed callback
st.text_input("Search Address", key="addr_input", on_change=search)

with st.sidebar:
    st.header("Site Specs")
    b_h = st.number_input("Building Height (ft)", value=20)
    d_alt = st.slider("Drone Alt (ft AGL)", 100, 400, 200)
    ant_total = b_h + 15
    
    st.divider()
    st.subheader("Add Obstruction")
    target_dir = st.selectbox("Direction:", dirs)
    
    st.write(f"**Distance:** {int(st.session_state.last_click_dist)} ft")
    g_msl = st.number_input("Ground MSL", value=900.0)
    t_msl = st.number_input("Top MSL", value=960.0)
    calc_h = t_msl - g_msl
    st.info(f"Tree Height: {int(calc_h)} ft")

    if st.button(f"➕ Add Obstacle to {target_dir}"):
        new_obs = {"dist": round(st.session_state.last_click_dist, 1), "h": calc_h}
        st.session_state.vault[target_dir].append(new_obs)
        st.success(f"Added to {target_dir}!")

    st.divider()
    for d in dirs:
        if st.session_state.vault[d]:
            if st.button(f"🗑️ Clear {d} ({len(st.session_state.vault[d])})", key=f"clr_{d}"):
                st.session_state.vault[d] = []
                st.rerun()

    if st.button("🚨 RESET ALL"):
        st.session_state.vault = {d: [] for d in dirs}
        st.session_state.center_coord = [33.66, -84.01]
        st.session_state.map_version += 1
        st.rerun()

# --- 4. INTERACTIVE SATELLITE MAP ---
# The KEY now includes the 'map_version' so it refreshes when you search
m_k = f"sat_map_v{st.session_state.map_version}"

m = folium.Map(location=st.session_state.center_coord, zoom_start=19, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(m)

out = st_folium(m, width=900, height=500, key=m_k)

if out and out.get("last_clicked"):
    nl, no = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    nd = geodesic(st.session_state.center_coord, (nl, no)).feet
    
    if nd < 25: # Click near dock to move center
        st.session_state.center_coord = [nl, no]
        st.session_state.map_version += 1 # Reset map to new center
        st.rerun()
    else:
        st.session_state.last_click_dist = nd
        st.write(f"Detected: **{int(nd)} ft**. Add details in sidebar.")

# --- 5. CALCULATION & RESULTS MAP ---
st.subheader("Final Range Analysis")
rf_pts = []
max_ft = 3.5 * 5280
bearings = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}

for d, ang in bearings.items():
    direction_limits = [max_ft]
    current_obs_list = st.session_state.vault.get(d, [])
    
    for obs in current_obs_list:
        h, dist = obs.get("h", 60.0), obs.get("dist", 150.0)
        limit = max_ft if h <= ant_total else ((d_alt - ant_total) * dist) / (h - ant_total)
        direction_limits.append(max(limit, dist))
    
    final_d = min(direction_limits)
    dest = geodesic(feet=final_d).destination(st.session_state.center_coord, ang)
    rf_pts.append({"lat": dest.latitude, "lon": dest.longitude, "name": d, "dist": final_d})

# Result map key also updates with map_version
res_map_k = f"res_map_v{st.session_state.map_version}"
res_map = folium.Map(location=st.session_state.center_coord, zoom_start=13, control_scale=True)

# City Limits reverse geocode logic
try:
    url = f"https://nominatim.openstreetmap.org/reverse?lat={st.session_state.center_coord[0]}&lon={st.session_state.center_coord[1]}&format=json&polygon_geojson=1&zoom=10"
    geo_res = requests.get(url, headers={'User-Agent': 'dji_pro'}).json()
    if 'geojson' in geo_res:
        folium.GeoJson(geo_res['geojson'], style_function=lambda x: {'color':'red','fill':None,'dashArray':'5,5','weight':3}).add_to(res_map)
except: pass

folium.Polygon([(p['lat'], p['lon']) for p in rf_pts], color="blue", fill=True, opacity=0.2).add_to(res_map)
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(res_map)

for p in rf_pts:
    mi = p['dist'] / 5280
    lbl = f"{mi:.2f} mi" if mi > 0.1 else f"{int(p['dist'])} ft"
    folium.Marker([p['lat'], p['lon']], icon=DivIcon(icon_size=(100,40), icon_anchor=(50,20),
        html=f'<div style="background: white; border: 2px solid blue; border-radius: 5px; color: black; font-weight: bold; font-size: 10px; text-align: center; width: 70px; padding: 2px;">{p["name"]}<br>{lbl}</div>')).add_to(res_map)

st_folium(res_map, width=1100, height=600, key=res_map_k)
