"""Streamlit rendering of the diagnostics panel (logic lives in modules.diagnostics)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from modules import diagnostics


def render_health_panel() -> None:
    try:
        d = diagnostics.run_diagnostics()
    except Exception as exc:  # diagnostics must never take the page down
        st.warning(f"Diagnostics unavailable: {exc}")
        return

    st.markdown("**Optional components** (the core app works without them)")
    deps = pd.DataFrame(
        [
            {
                "Package": s.module,
                "Used for": s.purpose,
                "Status": "installed" if s.available else "not installed",
                "Version": s.version or "",
            }
            for s in d["optional_deps"]
        ]
    )
    st.dataframe(deps, hide_index=True, width="stretch")

    st.markdown(
        f"**LLM key:** {'configured' if d['anthropic_api_key_set'] else 'not set (Ask the Data unavailable)'}"
        f"  \n**H3 hex grid:** {'available' if d['h3_available'] else 'not installed'} (resolution {d['h3_resolution']})"
        f"  \n**Permitted CCTV clips found:** {', '.join(d['video_clips']) or 'none'}"
    )

    for layer, tables in d["data"].items():
        present = [t for t, ok in tables.items() if ok]
        missing = [t for t, ok in tables.items() if not ok]
        st.markdown(
            f"**{layer} tables:** {len(present)} of {len(tables)} present"
            + (f"  \n_Missing:_ {', '.join(missing)}" if missing else "")
        )
