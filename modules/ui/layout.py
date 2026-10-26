"""Shared Streamlit layout helpers: header, badge, KPI cards, summary box, evidence, empty/error states.

Every page goes through these so the look and the labelling rules (RULES.md) stay consistent. No data values are
produced here; pages pass in values computed by the analytics modules.
"""
from __future__ import annotations

import html
from collections.abc import Iterable, Sequence

import plotly.graph_objects as go
import streamlit as st

import config
from modules.ui import data as ui_data
from modules.ui import filters as F
from modules.ui.pages_registry import PAGES_BY_KEY, PageSpec

_CSS = """
<style>
.block-container { padding-top: 2rem; max-width: 1200px; }
h1 { font-size: 1.9rem !important; letter-spacing: -0.01em; margin-bottom: 0.2rem; color: #1c2833; }
h2, h3 { color: #1c2833; letter-spacing: -0.005em; }
.gsrtc-purpose { color: #4a5a6a; font-size: 1.05rem; margin: 0 0 0.7rem 0; }
.gsrtc-badge { display: inline-block; padding: 0.15rem 0.7rem; border-radius: 999px;
  background: #fff4e0; border: 1px solid #e0a030; color: #7a4b00; font-size: 0.82rem; font-weight: 600; }
.gsrtc-meaning { border-left: 4px solid #1f4e79; background: #f3f6fa; padding: 0.7rem 1rem;
  border-radius: 0 6px 6px 0; margin: 1rem 0; }
.gsrtc-meaning .gsrtc-meaning-title { font-weight: 700; color: #1f4e79; margin-bottom: 0.2rem; }
.gsrtc-empty { border: 1px dashed #9aa9b8; background: #fafbfc; padding: 1.1rem 1.3rem;
  border-radius: 8px; margin: 1rem 0; }
.gsrtc-empty .gsrtc-empty-title { font-weight: 700; margin-bottom: 0.3rem; }
.gsrtc-card { border: 1px solid #d5dbe1; border-radius: 8px; padding: 0.8rem 1rem; background: #ffffff; height: 100%; }
.gsrtc-card .gsrtc-card-title { font-weight: 700; color: #1f4e79; margin-bottom: 0.25rem; }
.gsrtc-card .gsrtc-card-body { color: #1c2833; font-size: 0.95rem; }
.gsrtc-pill { display: inline-block; padding: 0.05rem 0.55rem; border-radius: 999px; font-size: 0.75rem; font-weight: 700;
  margin-right: 0.4rem; border: 1px solid #1f4e79; color: #1f4e79; background: #eaf1f8; }
.gsrtc-pill.high { border-color: #c4551b; color: #8a3a0f; background: #fbe9dd; }
.gsrtc-meta { color: #5a6978; font-size: 0.85rem; margin-top: 0.3rem; }
[data-testid="stMetricLabel"] p { font-size: 0.85rem; color: #4a5a6a; }
[data-testid="stSidebar"] { background: #f3f6fa; }
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
    st.markdown(f'<p class="gsrtc-purpose">{html.escape(purpose)}</p>', unsafe_allow_html=True)
    if simulated:
        simulation_badge()


def page_setup(key: str, show_filters: Sequence[str] = ("corridor", "day_type", "hours")) -> tuple[PageSpec, F.Filters]:
    """Header + sidebar filters + 'Active filters' caption. Returns the page spec and the active filters."""
    spec = PAGES_BY_KEY[key]
    page_header(spec.title, spec.purpose)
    f = F.sidebar(tuple(show_filters)) if show_filters else F.current()
    if show_filters:
        st.caption("Active filters: " + f.describe(corridor="corridor" in show_filters, day_type="day_type" in show_filters,
                                                   hours="hours" in show_filters))
    return spec, f


def require_tables(spec: PageSpec, extra: Iterable[tuple[str, str]] = ()) -> dict:
    """Load the page's required tables (plus ``extra``); on missing data show the empty state and stop the page."""
    req = list(dict.fromkeys([*spec.required, *extra]))
    try:
        return ui_data.load_many(req)
    except ui_data.DataUnavailable as exc:
        empty_state(
            "Data not yet generated",
            f"This page needs: {', '.join(f'<code>{m}</code>' for m in exc.missing)}. "
            "Run the command below from the project root, then reload the page.",
            spec.command,
        )
        st.stop()
        raise  # pragma: no cover - st.stop() raises


def kpi_row(cards: Sequence[dict]) -> None:
    """At most four KPI cards: dicts with ``label``, ``value`` (formatted string with unit) and ``help``."""
    cards = list(cards)[:4]
    cols = st.columns(len(cards))
    for col, c in zip(cols, cards):
        with col:
            st.metric(c["label"], c["value"], help=c.get("help"), border=True)


def show_chart(fig: go.Figure, key: str | None = None) -> None:
    st.plotly_chart(fig, width="stretch", key=key, config={"displaylogo": False, "displayModeBar": False})


def what_this_means(text: str) -> None:
    st.markdown(
        f'<div class="gsrtc-meaning"><div class="gsrtc-meaning-title">What this means</div>{html.escape(text)}</div>',
        unsafe_allow_html=True,
    )


def evidence_expander(
    sources: Iterable[str] = (),
    assumptions: Iterable[str] = (),
    title: str = "Data and assumptions",
    *,
    formulas: Iterable[str] = (),
    filters: str | None = None,
) -> None:
    with st.expander(title):
        src, asm, frm = list(sources), list(assumptions), list(formulas)
        st.markdown("**Data sources**")
        st.markdown("\n".join(f"- {s}" for s in src) if src else "- None yet (no data has been generated).")
        if filters:
            st.markdown("**Filters applied**")
            st.markdown(f"- {filters}")
        if frm:
            st.markdown("**How this was calculated**")
            st.markdown("\n".join(f"- {x}" for x in frm))
        st.markdown("**Assumptions and limitations**")
        st.markdown("\n".join(f"- {a}" for a in asm) if asm else "- None recorded yet.")


def card(title: str, body: str, *, pill: str | None = None, pill_class: str = "", meta: str | None = None) -> None:
    pill_html = f'<span class="gsrtc-pill {pill_class}">{html.escape(pill)}</span>' if pill else ""
    meta_html = f'<div class="gsrtc-meta">{html.escape(meta)}</div>' if meta else ""
    st.markdown(
        f'<div class="gsrtc-card"><div class="gsrtc-card-title">{pill_html}{html.escape(title)}</div>'
        f'<div class="gsrtc-card-body">{html.escape(body)}</div>{meta_html}</div>',
        unsafe_allow_html=True,
    )


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


def note(text: str) -> None:
    """A short neutral explanation under a chart/table."""
    st.caption(text)
