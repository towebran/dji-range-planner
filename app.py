import streamlit as st
import folium, requests, math, pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic
from folium.features import DivIcon
from fpdf import FPDF
from datetime import datetime

# --- 1. SETTINGS & RF PHYSICS ---
st.set_page_config(layout="wide", page_title="DJI M4TD Strategic Planner")

TX_POWER_DBM = 33.0     # Max FCC EIRP
ANTENNA_GAIN_DB = 3.0   # Dock 3 MIMO Gain
REQD_SIGNAL = -90.0     
FREQ_GHZ = 2.4          
D_STEP = 800            

# Initialize Session State
if 'center' not in st.session_state: st.session_state.center = [34.065, -84.677]
if 'dock_confirmed' not in st.session_state: st.session_state.dock_confirmed = False
if 'dock_stack' not in st.session_state: st.session_state.dock_stack = {"b_height": 0.0, "ant_h": 15.0, "total_msl": 0.0}
if 'vault' not in st.session_state: st.session_state.vault = []
if 'manual_obs' not in st.session_state: st.session_state.manual_obs = []
if 'staged_obs' not in st.session_state: st.session_state.staged_obs = None
if 'map_v' not in st.session_state: st.session_state.map_v = 1
if 'site_name' not in st.session_state: st.session_state.site_name = "New Project"

# --- 2. THE REPORT GENERATOR ---
def create_pdf_report():
    pdf = FPDF()
    pdf.add_page()
    
    # Header
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 15, "DJI DOCK 3 SITE SURVEY REPORT", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 10, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align="R")
    
    # Site Summary
    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, f"Site: {st.session_state.site_name}", ln=True)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, f"Coordinates: {st.session_state.center[0]:.5f}, {st.session_state.center[1]:.5f}", ln=True)
    pdf.cell(0, 8, f"Dock Height (Total Tip): {st.session_state.dock_stack['total_msl']} ft MSL", ln=True)
    
    # Obstacle Table
    if st.session_state.manual_obs:
        pdf.ln(10)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 10, "VERIFIED OBSTACLE LOG", ln=True)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(40, 8, "Direction", border=1)
        pdf.cell(40, 8, "Distance (ft)", border=1)
        pdf.cell(40, 8, "Top MSL (ft)", border=1, ln=True)
        
        pdf.set_font("Helvetica", "", 10)
        for ob in st.session_state.manual_obs:
            pdf.cell(40, 8, ob['dir'], border=1)
            pdf.cell(40, 8, str(int(ob['dist'])), border=1)
            pdf.cell(40, 8, str(int(ob['msl'])), border=1, ln=True)

    # Disclaimer
    pdf.ln(20)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(0, 5, "Note: RF projections are based on DJI O4 Enterprise link budget and 2.4GHz propagation models. Actual range may vary based on local RF interference and atmospheric conditions.")
    
    return bytes(pdf.output())

# --- 3. UI LOGIC (Summary only, full code uses your v14 logic) ---
with st.sidebar:
    st.session_state.site_name = st.text_input("Project Name", value=st.session_state.site_name)
    # ... (Phase 1 & Phase 2 logic from v14) ...

    if st.session_state.vault:
        st.divider()
        st.header("Step 4: Export Results")
        
        # DOWNLOAD BUTTONS
        st.download_button(
            label="📄 Download PDF Report",
            data=create_pdf_report(),
            file_name=f"Survey_{st.session_state.site_name}.pdf",
            mime="application/pdf"
        )
        
        # HTML Map Export
        m_html = folium.Map(location=st.session_state.center, zoom_start=15).get_root().render()
        st.download_button(
            label="🌐 Download Interactive HTML Map",
            data=m_html,
            file_name=f"Map_{st.session_state.site_name}.html",
            mime="text/html"
        )

# --- 4. MAP RENDERING (v14 Code) ---
# ... [Insert standard map rendering block here] ...
