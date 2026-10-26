"""Shared Streamlit layout helpers: header, badge, summary box, evidence, empty/error states.

Every page goes through these so the look and the labelling rules (RULES.md)
stay consistent. No data values are produced here.
"""
from __future__ import annotations

from collections.abc import Iterable

import streamlit as st

import config
from modules.data import io
from modules.ui.pages_registry import PAGES_BY_KEY, PageSpec

_CSS = """
<style>
.block-container { padding-top: 2rem; max-width: 1200px; }
h1 { font-size: 1.9rem !important; letter-spacing: -0.01em; margin-bottom: 0.2rem; }
.gsrtc-purpose { color: #4a5a6a; font-size: 1.05rem; margin: 0 0 0.9rem 0; }
.gsrtc-badge { display: inline-block; padding: 0.15rem 0.7rem; border-radius: 999px;
  background: #fff4e0; border: 1px solid #e0a030; color: #7a4b00; font-size: 0.82rem; font-weight: 600; }
.gsrtc-meaning { border-left: 4px solid #1f4e79; background: #f3f6fa; padding: 0.7rem 1rem;
  border-radius: 0 6px 6px 0; margin: 1rem 0; }
.gsrtc-meaning .gsrtc-meaning-title { font-weight: 700; color: #1f4e79; margin-bottom: 0.2rem; }
.gsrtc-empty { border: 1px dashed #9aa9b8; background: #fafbfc; padding: 1.1rem 1.3rem;
  border-radius: 8px; margin: 1rem 0; }
.gsrtc-empty .gsrtc-empty-title { font-weight: 700; margin-bottom: 0.3rem; }
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def simulation_badge() -> None:
    st.markdown(f'<span class="gsrtc-badge">{config.SIMULATION_BADGE_TEXT}</span>', unsafe_allow_html=True)


def page_header(title: str, purpose: str, *, simulated: bool = True) -> None:
    """Title, one-sentence purpose and (by default) the simulation badge."""
    inject_css()
    st.title(title)
    st.markdown(f'<p class="gsrtc-purpose">{purpose}</p>', unsafe_allow_html=True)
    if simulated:
        simulation_badge()


def what_this_means(text: str) -> None:
    st.markdown(
        f'<div class="gsrtc-meaning"><div class="gsrtc-meaning-title">What this means</div>{text}</div>',
        unsafe_allow_html=True,
    )


def evidence_expander(
    sources: Iterable[str] = (),
    assumptions: Iterable[str] = (),
    title: str = "Data and assumptions",
) -> None:
    with st.expander(title):
        src, asm = list(sources), list(assumptions)
        st.markdown("**Data sources**")
        st.markdown("\n".join(f"- {s}" for s in src) if src else "- None yet (no data has been generated).")
        st.markdown("**Assumptions and limitations**")
        st.markdown("\n".join(f"- {a}" for a in asm) if asm else "- None recorded yet.")


def empty_state(title: str, message: str, command: str | None = None) -> None:
    st.markdown(
        f'<div class="gsrtc-empty"><div class="gsrtc-empty-title">{title}</div>{message}</div>',
        unsafe_allow_html=True,
    )
    if command:
        st.code(command, language="bash")


def error_state(message: str, exc: BaseException | None = None) -> None:
    st.error(message)
    if exc is not None:
        with st.expander("Technical details"):
            st.exception(exc)


def missing_required(spec: PageSpec) -> list[str]:
    """Names of required tables (as 'layer/table') not yet generated."""
    return [f"{layer}/{name}" for layer, name in spec.required if not io.table_exists(name, layer)]


def render_page_shell(key: str) -> PageSpec:
    """Header + data-availability state for a page. Returns the spec.

    In Milestone 0 no page has analytics, so a page either reports missing data
    or states that its content is not built yet. Neither shows numbers.
    """
    spec = PAGES_BY_KEY[key]
    page_header(spec.title, spec.purpose)
    missing = missing_required(spec)
    if missing:
        empty_state(
            "Data not yet generated",
            f"This page needs: {', '.join(f'<code>{m}</code>' for m in missing)}. "
            "Run the command below from the project root, then reload. "
            "(The command is implemented in the milestone noted in the README.)",
            spec.command,
        )
    else:
        empty_state(
            "Page content not built yet",
            f"The required tables exist, but the views for this page are scheduled for milestone {spec.milestone}.",
        )
    what_this_means("No findings are shown until this page is built on generated data.")
    evidence_expander(
        sources=[f"Required tables: {', '.join(f'{lay}/{n}' for lay, n in spec.required)}"],
        assumptions=[f"{config.SIMULATION_BADGE_TEXT}. Nothing on this page is a real GSRTC measurement."],
    )
    return spec
