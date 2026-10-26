"""Single entry point: `python -m streamlit run app.py`.

Navigation uses st.navigation / st.Page. Because st.navigation is used, Streamlit
does NOT auto-generate a second sidebar menu from the pages/ directory.
"""
from __future__ import annotations

import streamlit as st

import config
from modules.ui.layout import inject_css
from modules.ui.pages_registry import PAGES

st.set_page_config(
    page_title="GSRTC Mobility Intelligence",
    page_icon=":material/directions_bus:",
    layout="wide",
)
inject_css()

pages = [
    st.Page(p.file, title=p.title, icon=p.icon, url_path=p.key, default=(p.key == "overview"))
    for p in PAGES
]
nav = st.navigation(pages)

with st.sidebar:
    st.caption(f"Pilot: {config.PILOT_CITY}")
    st.caption(f"Primary corridor: {config.PRIMARY_CORRIDOR}")
    st.caption(config.SIMULATION_BADGE_TEXT)

nav.run()
