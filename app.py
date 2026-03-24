import streamlit as st
import folium, requests
from streamlit_folium import st_folium
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from folium.features import DivIcon

st.set_page_config(layout="wide", page_title="DJI M4TD Multi-Obstacle Planner")

# --- 1. STATE INITIALIZATION ---
dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

if 'vault' not in st.session_state:
    # Now storing a LIST of obstacles for each direction
    st.session_state.vault = {d: [] for d in dirs}
if 'center_coord' not in st.session_state:
    st.session_state.center_coord = [33.66, -84.01]
if 'last_click_dist' not in st.session_state:
    st.session_state.last_click_dist = 0.0

# --- 2. LOGIC FUNCTIONS ---
def search():
    if st.session_state.addr_input:
        try:
            loc = Nominatim(user_agent="dji_multi_obs").geocode(st.session_state.addr_input)
            if loc: st.session_state.center_coord = [loc.latitude, loc.longitude]
        except: st.error("Search error.")

def get_city(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&polygon_geojson=1&zoom=10"
    try:
        res = requests.get(url, headers={'User-Agent': 'DJI_Pro'}).json()
        return res.get('geojson')
    except: return None

# --- 3. UI & SIDEBAR ---
st.title("📡 DJI M4TD Multi-Obstacle Precision Planner")
st.text_input("Search Address", key="addr_input", on_change=search)

with st.sidebar:
    st.header("Site Specs")
    b_h = st.number_input("Building Height (ft)", value=20)
    d_alt = st.slider("Drone Alt (ft AGL)", 100, 400, 200)
    ant_total = b_h + 15
    
    st.divider()
    st.subheader("Add Obstruction")
    target_dir = st.selectbox("Direction:", dirs)
    
    st.write(f"**Detected Distance:** {int(st.session_state.last_click_dist)} ft")
    g_msl = st.number_input("Ground MSL", value=900.0)
    t_msl = st.number_input("Top MSL", value=960.0)
    calc_h = t_msl - g_msl
    st.info(f"Tree Height: {int(calc_h)} ft")

    if st.button(f"➕ Add Obstacle to {target_dir}"):
        new_obs = {"dist": round(st.session_state.last_click_dist, 1), "h": calc_h}
        st.session_state.vault[target_dir].append(new_obs)
        st.success(f"Added to {target_dir} list!")

    st.divider()
    st.subheader("Current Obstacles")
    for d in dirs:
        if st.session_state.vault[d]:
            st.write(f"**{d}:** {len(st.session_state.vault[d])} obstacles")
            if st.button(f"🗑️ Clear {d}", key=f"clr_{d}"):
                st.session_state.vault[d] = []
                st.rerun()

    if st.button("🚨 RESET ENTIRE SURVEY"):
        st.session_state.vault = {d: [] for d in dirs}
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
        st.write(f"Detected Distance: **{int(nd)} ft**. Enter MSL and click 'Add'.")

# --- 5. CALCULATION (WORST-CASE ANALYSIS) ---
st.subheader("Final Range Analysis (Worst-Case Obstruction)")
rf_pts = []
max_ft = 3.5 * 5280
bearings = {"N":0, "NE":45, "E":90, "SE":135, "S":180, "SW":225, "W":270, "NW":315}

for d, ang in bearings.items():
    direction_limits = [max_ft] # Default to 3.5 miles
    
    # Check every obstacle in this direction
    for obs in st.session_state.vault[d]:
        h, dist = obs["h"], obs["dist"]
        
        if h <= ant_total:
            limit = max_ft
        else:
            # How far can we go before THIS specific obstacle blocks us?
            limit = ((d_alt - ant_total) * dist) / (h - ant_total)
            limit = max(limit, dist) # Can't fly through the tree
            
        direction_limits.append(limit)
    
    # THE DECIDING FACTOR: The shortest limit wins
    final_d = min(direction_limits)
    final_d = min(final_d, max_ft)
    
    dest = geodesic(feet=final_d).destination(st.session_state.center_coord, ang)
    rf_pts.append({"lat": dest.latitude, "lon": dest.longitude, "name": d, "dist": final_d})

# Results Map
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
