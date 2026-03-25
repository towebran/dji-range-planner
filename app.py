import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon
from fpdf import FPDF
from datetime import datetime

# --- 1. SETTINGS & RF ---
st.set_page_config(layout="wide", page_title="DJI M4TD Field Survey")
TX_EIRP = 33.0
THRESHOLD_LOST = -92.0
EARTH_K = 1.333

# State Management
if 'center' not in st.session_state: st.session_state.center = [34.065, -84.677]
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'vault' not in st.session_state: st.session_state.vault = []
if 'poly_coords' not in st.session_state: st.session_state.poly_coords = []
if 'dock_confirmed' not in st.session_state: st.session_state.dock_confirmed = False
if 'dock_stack' not in st.session_state: st.session_state.dock_stack = {"ground": 900.0, "total_msl": 947.0}

# --- 2. THE REPORT ENGINE ---
def generate_pdf():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(0, 10, f"DJI M4TD STRATEGIC SITE REPORT", ln=True, align='C')
    pdf.set_font("helvetica", "", 10)
    pdf.cell(0, 10, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True)
    pdf.ln(5)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, "1. DOCK CONFIGURATION", ln=True)
    pdf.set_font("helvetica", "", 10)
    pdf.cell(0, 8, f"Location: {st.session_state.center[0]:.5f}, {st.session_state.center[1]:.5f}", ln=True)
    pdf.cell(0, 8, f"Dock Tip MSL: {st.session_state.dock_stack['total_msl']} ft", ln=True)
    
    pdf.ln(5)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, "2. VERIFIED OBSTRUCTIONS", ln=True)
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(30, 8, "ID", 1); pdf.cell(50, 8, "Type", 1); pdf.cell(50, 8, "MSL (ft)", 1); pdf.cell(50, 8, "Dist (ft)", 1, ln=True)
    pdf.set_font("helvetica", "", 10)
    for ob in st.session_state.manual_obs:
        pdf.cell(30, 8, str(ob['id']), 1); pdf.cell(50, 8, ob['type'], 1); pdf.cell(50, 8, str(int(ob['msl'])), 1); pdf.cell(50, 8, str(int(ob['dist'])), 1, ln=True)
    
    return pdf.output()

# --- 3. UI SIDEBAR ---
with st.sidebar:
    st.title("🛡️ Field Survey Tool")
    
    # DOCK SETUP
    if not st.session_state.dock_confirmed:
        st.header("1. Locate Dock")
        addr = st.text_input("Address", "Acworth, GA")
        if st.button("Search"):
            # (Insert geocode search here)
            st.session_state.center = [34.065, -84.677] # Placeholder
        
        b_h = st.number_input("Building Height (ft)", 32.0)
        a_h = st.number_input("Antenna Height (ft)", 15.0)
        if st.button("✅ LOCK DOCK"):
            st.session_state.dock_confirmed = True
            st.rerun()
    else:
        st.header("2. Survey Actions")
        if st.button("🚨 CLEAR ALL DATA"):
            st.session_state.manual_obs = []
            st.session_state.vault = []
            st.session_state.poly_coords = []
            st.rerun()
        
        # PDF DOWNLOAD
        pdf_data = generate_pdf()
        st.download_button("📥 DOWNLOAD PDF REPORT", pdf_data, "Site_Report.pdf", "application/pdf")
        
        st.divider()
        drone_agl = st.selectbox("Drone Alt (ft AGL)", [200, 400])
        clutter = st.slider("Clutter (ft)", 0, 100, 80)
        
        if st.button("🚀 RUN SURGICAL SCAN"):
            h_tx = st.session_state.dock_stack['total_msl']
            bearings = [0, 22.5, 45, 67.5, 90, 112.5, 135, 157.5, 180, 202.5, 225, 247.5, 270, 292.5, 315, 337.5]
            st.session_state.vault = []
            st.session_state.poly_coords = []
            
            for ang in bearings:
                path = []
                max_d = 0
                last_coord = st.session_state.center
                for d in range(800, 20000, 800):
                    pt = geodesic(feet=d).destination(st.session_state.center, ang)
                    # (Insert v27 calculate_surgical_link logic here)
                    color = "#00FF00" # Simplified for snippet
                    path.append({"coords": [last_coord, [pt.latitude, pt.longitude]], "color": color})
                    last_coord = [pt.latitude, pt.longitude]
                    max_d = d
                st.session_state.vault.append(path)
                st.session_state.poly_coords.append({"coord": last_coord, "dist": max_d})
            st.rerun()

# --- 4. MAP RENDERING ---
m = folium.Map(location=st.session_state.center, zoom_start=18, tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google')

# Polygon Web & Distance Labels
if st.session_state.poly_coords:
    poly_list = [p['coord'] for p in st.session_state.poly_coords]
    folium.Polygon(poly_list, color="#00FF00", fill=True, fill_opacity=0.2).add_to(m)
    
    for p in st.session_state.poly_coords:
        miles = round(p['dist'] / 5280, 2)
        folium.Marker(p['coord'], icon=DivIcon(html=f'<div style="color: white; background: rgba(0,0,0,0.5); padding: 2px; border-radius: 3px; font-size: 10px;">{miles}mi</div>')).add_to(m)

# Draw Paths & Home
folium.Marker(st.session_state.center, icon=folium.Icon(color='blue')).add_to(m)
for path in st.session_state.vault:
    for seg in path:
        folium.PolyLine(seg['coords'], color=seg['color'], weight=4).add_to(m)

st_folium(m, width=1100, height=650)
