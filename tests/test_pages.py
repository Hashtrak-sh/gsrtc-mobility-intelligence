"""Page smoke tests. Extend ``PAGES`` expectations as later milestones add content."""
import py_compile
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import config
from modules.ui.pages_registry import PAGES

ROOT = Path(__file__).resolve().parents[1]
NAV_ORDER = [
    "Overview", "Operations Replay", "Demand & Surveys", "Route Intelligence", "Demand–Supply Gaps",
    "Passenger Flow & O-D", "Competition & Pricing", "Cost-Benefit & Fares", "Infrastructure & Digital",
    "CCTV Analytics", "Reports",
]


def test_nav_order_and_count():
    assert [p.title for p in PAGES] == NAV_ORDER


def test_entry_point_exists_and_single():
    assert (ROOT / "app.py").is_file()
    assert not (ROOT / "pages" / "app.py").exists()
    assert not (ROOT / "Home.py").exists()


@pytest.mark.parametrize("spec", PAGES, ids=lambda s: s.key)
def test_page_file_exists_and_compiles(spec):
    f = ROOT / spec.file
    assert f.is_file()
    py_compile.compile(str(f), doraise=True)


def test_every_pages_file_is_registered():
    registered = {Path(p.file).name for p in PAGES}
    on_disk = {p.name for p in (ROOT / "pages").glob("*.py")}
    assert registered == on_disk


@pytest.mark.parametrize("spec", PAGES, ids=lambda s: s.key)
def test_page_runs_without_exception(spec):
    at = AppTest.from_file(str(ROOT / spec.file), default_timeout=30).run()
    assert not at.exception, [e.value for e in at.exception]
    assert [t.value for t in at.title] == [spec.title]
    html = " ".join(m.value for m in at.markdown)
    assert config.SIMULATION_BADGE_TEXT in html
    assert "What this means" in html


def test_empty_state_shows_command_when_data_missing(monkeypatch, tmp_path):
    # Point the data layers at an empty directory so the test does not depend on whether data has been generated.
    from modules.data import io

    empty = {"raw": tmp_path / "raw", "synthetic": tmp_path / "synthetic", "processed": tmp_path / "processed"}
    monkeypatch.setattr(config, "LAYER_DIRS", empty)
    assert io.missing_tables("synthetic")
    spec = PAGES[1]
    at = AppTest.from_file(str(ROOT / spec.file), default_timeout=30).run()
    assert not at.exception
    assert any(spec.command in c.value for c in at.code)
    assert "Data not yet generated" in " ".join(m.value for m in at.markdown)


def test_overview_has_health_panel():
    at = AppTest.from_file(str(ROOT / "pages/0_Overview.py"), default_timeout=30).run()
    assert not at.exception
    assert any("System health" in e.label for e in at.expander)


def test_main_app_runs_with_navigation():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
