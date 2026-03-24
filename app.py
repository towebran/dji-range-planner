import streamlit as st
import folium, requests, random, time
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DJI M4TD Pro Planner")

# --- 1. SESSION STATE (The Vault) ---
dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

if 'vault' not in st.session_state:
    st.session_state.vault = {d: [] for d in dirs}
if 'center_coord' not in st.session_state:
    st.session_state.center_coord = [33.6644, -84.0113] # Conyers
if 'last_click_dist' not in st.session_state:
    st.session_state.last_click_dist = 0.0
if 'map_v' not in st.session_state:
    st.session_state.map_v = 1

# --- 2. THE NEW "UNBLOCKABLE" SEARCH ---
def perform_search():
    query = st.session_state.search_box
    if query:
        # Use a random browser-like User Agent to prevent blocking
        headers = {'User-Agent': f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) DJI_Survey_{random.randint(1,999)}'}
        url = f"https://nominatim.openstreetmap.org/search?q={query}&format=json&limit=1"
        try:
            res = requests.get(url, headers=headers, timeout=10).json()
            if res:
                st.session_state.center_coord = [float(res[0]['lat']), float(res[0]['lon'])]
                st.session_state.map_v += 1 # Forces map to snap to new location
                st.toast(f"📍 Found: {res[0]['display_name'][:40]}...")
            else:
                st.error("Address not found. Try adding Zip or State.")
        except Exception as e:
            st.error("Search service busy. Please try again in 5 seconds.")

# --- 3. UI LAYOUT ---
st.title("📡 DJI M4TD Multi-Obstacle Precision Planner")

with st.sidebar:
    st.header("1. Find Location")
    # Moved search here to prevent the map from "refresh-blocking" your typing
    st.text_input("Enter Address:", key="search_box", on_change=perform_search, placeholder="123 Main St, Conyers, GA")
    
    st.header("2. Site Specs")
    b_h = st.number_input("Building Height (ft)", value=20)
    d_alt = st.slider("Drone Alt (ft AGL)", 100, 400, 200)
    ant_total = b_h + 15
    
    st.divider()
    st.subheader("3. Add Obstacle")
    target_dir = st.selectbox("Direction:", dirs)
    
    st.write(f"**Click Dist:** {int(st.session_state.last_click_dist)} ft")
    g_msl = st.number_input("Ground MSL", value=900.0, step=1.0)
    t_msl = st.number_input("Top MSL", value=960.0, step=1.0)
    calc_h = t_msl - g_msl
    st.info(f"Tree Height: {int(calc_h)} ft")

    if st.button(f"➕ Add to {target_dir}"):
        st.session_state.vault[target_dir].append({"dist": round(st.session_state.last_click_dist, 1), "h": calc_h})
        st.success(f"Added to {target_dir}!")

    st.divider()
    if st.button("🚨 RESET ALL"):
        st.session_state.vault = {d: [] for d in dirs}
        st.session_state.center_coord = [33.6644, -84.0113]
        st.session_state.map_v += 1
        st.rerun()

# --- 4. SATELLITE SURVEY MAP ---
# The map version key forces the map to jump to the new search address
m_key = f"sat_map_v{st.session_state.map_v}"
m = folium.Map(location=st.session_state.center_coord, zoom_start=19, 
               tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(m)

out = st_folium(m, width=900, height=500, key=m_key)

if out and out.get("last_clicked"):
    nl, no = out["last_clicked"]["lat"], out["last_clicked"]["lng"]
    nd = geodesic(st.session_state.center_coord, (nl, no)).feet
    
    if nd < 25: # Click dock to move center
        st.session_state.center_coord = [nl, no]
        st.session_state.map_v += 1
        st.rerun()
    else:
        st.session_state.last_click_dist = nd
        st.write(f"Detected: **{int(nd)} ft**. Enter MSL in sidebar and click Add.")

# --- 5. RESULTS ANALYSIS ---
st.subheader("Final Range & Jurisdiction")
rf_pts = []
max_ft = 3.5 * 5280
bearings = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}

for d, ang in bearings.items():
    direction_limits = [max_ft]
    for obs in st.session_state.vault.get(d, []):
        h, dist = obs.get("h", 60.0), obs.get("dist", 150.0)
        limit = max_ft if h <= ant_total else ((d_alt - ant_total) * dist) / (h - ant_total)
        direction_limits.append(max(limit, dist))
    
    final_d = min(direction_limits)
    dest = geodesic(feet=final_d).destination(st.session_state.center_coord, ang)
    rf_pts.append({"lat": dest.latitude, "lon": dest.longitude, "name": d, "dist": final_d})

res_map = folium.Map(location=st.session_state.center_coord, zoom_start=13, control_scale=True)

# City Limits logic
try:
    c_url = f"https://nominatim.openstreetmap.org/reverse?lat={st.session_state.center_coord[0]}&lon={st.session_state.center_coord[1]}&format=json&polygon_geojson=1&zoom=10"
    c_res = requests.get(c_url, headers={'User-Agent': 'DJI_Survey_Tool'}).json()
    if 'geojson' in c_res:
        folium.GeoJson(c_res['geojson'], style_function=lambda x: {'color':'red','fill':None,'dashArray':'5,5','weight':3}).add_to(res_map)
except: pass

folium.Polygon([(p['lat'], p['lon']) for p in rf_pts], color="blue", fill=True, opacity=0.2).add_to(res_map)
folium.Marker(st.session_state.center_coord, icon=folium.Icon(color='red')).add_to(res_map)

for p in rf_pts:
    mi = p['dist'] / 5280
    lbl = f"{mi:.2f} mi" if mi > 0.1 else f"{int(p['dist'])} ft"
    folium.Marker([p['lat'], p['lon']], icon=DivIcon(icon_size=(100,40), icon_anchor=(50,20),
        html=f'<div style="background: white; border: 2px solid blue; border-radius: 5px; color: black; font-weight: bold; font-size: 10px; text-align: center; width: 70px; padding: 2px;">{p["name"]}<br>{lbl}</div>')).add_to(res_map)

st_folium(res_map, width=1100, height=600, key=f"res_v{st.session_state.map_v}")
