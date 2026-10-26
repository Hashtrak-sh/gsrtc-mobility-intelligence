"""Overview page."""
import streamlit as st

from modules.ui.health import render_health_panel
from modules.ui.layout import render_page_shell

render_page_shell("overview")

with st.expander("System health and diagnostics"):
    render_health_panel()
