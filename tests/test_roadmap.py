"""Digital transformation roadmap: scheduling logic, figure and page (AppTest)."""
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from modules.analytics import roadmap as R
from modules.ui.roadmap_chart import roadmap_figure

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def digital() -> pd.DataFrame:
    return pd.read_parquet(ROOT / "data" / "synthetic" / "digital_assessment.parquet")


def test_dependencies_respected(digital):
    rm = R.build_roadmap(digital).set_index("id")
    for _, r in rm[rm["status"] == "scheduled"].iterrows():
        for d in r["dependencies"]:
            if rm.loc[d, "status"] == "scheduled":
                assert r["start_month"] >= rm.loc[d, "end_month"]
        assert r["end_month"] == r["start_month"] + r["duration_months"]


def test_phase_matches_start(digital):
    rm = R.build_roadmap(digital)
    for r in rm[rm["status"] == "scheduled"].itertuples():
        want = 1 if r.start_month < 6 else 2 if r.start_month < 18 else 3
        assert r.phase == want


def test_phase3_nonempty_and_dependency_driven(digital):
    rm = R.build_roadmap(digital)
    p3 = rm[rm["phase"] == 3]
    assert len(p3) >= 2
    ends = rm.set_index("id")["end_month"]
    for r in p3.itertuples():
        assert max(ends[d] for d in r.dependencies if pd.notna(ends[d])) >= 18  # pushed late by its dependencies


def test_targets_coherent_per_capability():
    c = R.CATALOGUE
    for _, g in c.groupby("capability"):
        # a later initiative (one that transitively follows the other) never has a lower target
        for r in g.itertuples():
            for d in r.dependencies:
                if d in set(g["id"]):
                    assert r.target_maturity >= g.set_index("id").loc[d, "target_maturity"]
    assert (c["source_type"] == "manual_demo_input").all()


def test_current_is_mean_of_assessment(digital):
    rm = R.build_roadmap(digital)
    means = digital.groupby("capability")["maturity_score"].mean()
    mins = digital.groupby("capability")["maturity_score"].min()
    for r in rm.itertuples():
        assert r.current == pytest.approx(means[r.capability])
        assert r.current_min == pytest.approx(mins[r.capability])
    assert (rm["source_type"] == "manual_demo_input").all()


def test_capability_at_target_dropped(digital):
    d = digital.copy()
    d.loc[d["capability"] == "live tracking", "maturity_score"] = 5.0
    rm = R.build_roadmap(d)
    r = rm.set_index("id")
    assert (r.loc[["LT1", "LT2"], "status"] == "not needed").all()
    assert r.loc[["LT1", "LT2"], "start_month"].isna().all()
    assert r.loc["PI2", "start_month"] == 0  # dropped dependency counts as complete
    fig = roadmap_figure(rm)
    assert "LT1" not in " ".join(str(y) for t in fig.data for y in t.y)


def test_all_at_target(digital):
    rm = R.build_roadmap(digital.assign(maturity_score=5.0))
    assert (rm["status"] == "not needed").all()
    assert roadmap_figure(rm) is not None
    assert "no initiatives" in R.takeaway(rm).lower()


def test_deterministic(digital):
    pd.testing.assert_frame_equal(R.build_roadmap(digital), R.build_roadmap(digital.sample(frac=1, random_state=1)))


def test_figure_builds(digital):
    fig = roadmap_figure(R.build_roadmap(digital))
    assert len(fig.data) >= 1 and fig.layout.xaxis.range[0] == 0


def test_page_renders_roadmap():
    at = AppTest.from_file(str(ROOT / "pages" / "6_Infrastructure_and_Digital.py"), default_timeout=90).run()
    assert not at.exception
    assert "Digital transformation roadmap" in [h.value for h in at.subheader]
    assert "illustrative assumptions" in " ".join(c.value for c in at.caption)
