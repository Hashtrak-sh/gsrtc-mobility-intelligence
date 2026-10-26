"""Milestone 7 (part A): PDF report, CSV export provenance and report/dashboard consistency. Uses the processed tables on disk."""
import io
import re
from datetime import datetime, timezone

import pandas as pd
import pytest

import config
from modules.analytics import queries as Q
from modules.data import io as dio
from modules.reporting import exports as X
from modules.reporting import pdf as P
from modules.reporting import sources
from modules.reporting import text as TXT
from modules.ui import filters as F
from modules.ui import fmt

pytestmark = pytest.mark.skipif(not dio.table_exists("route_summary", "processed"),
                                reason="processed tables not generated (python -m modules.analytics.run)")

NOW = datetime(2026, 10, 26, 9, 30, 15, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def tabs():
    return sources.load_tables()


@pytest.fixture(scope="module")
def default_pdf(tabs):
    return P.build_report_pdf(F.Filters(), tabs, now=NOW)


@pytest.fixture(scope="module")
def filtered_filters():
    return F.Filters("Rajkot-Somnath", "weekend", 7, 22)


@pytest.fixture(scope="module")
def filtered_pdf(tabs, filtered_filters):
    return P.build_report_pdf(filtered_filters, tabs, now=NOW)


def _pages(data: bytes) -> list[str]:
    pypdf = pytest.importorskip("pypdf", reason="pypdf not installed: text assertions skipped")
    return [" ".join((p.extract_text() or "").split()) for p in pypdf.PdfReader(io.BytesIO(data)).pages]


def _norm(s: str) -> str:
    return " ".join(str(s).split())


def test_pdf_builds_nonempty_and_valid(default_pdf, filtered_pdf):
    for data in (default_pdf, filtered_pdf):
        assert data.startswith(b"%PDF") and len(data) > 20_000
        assert data.rstrip().endswith(b"%%EOF")


def test_pdf_deterministic_for_same_inputs(tabs, default_pdf):
    assert P.build_report_pdf(F.Filters(), tabs, now=NOW) == default_pdf


def test_default_pdf_content(default_pdf, tabs):
    pages = _pages(default_pdf)
    assert 8 <= len(pages) <= 20
    full = " ".join(pages)
    assert config.SIMULATION_BADGE_TEXT in pages[0]
    assert "2026-10-26 09:30:15 UTC" in full  # report generation timestamp
    assert f"Random seed {config.SEED}" in full
    assert F.Filters().describe() in full
    assert "Limitations" in full and "not profit" in full
    for sec in ("Executive summary", "Pilot scope and data provenance", "Route and demand findings", "Supply-gap findings", "Service recommendations",
                "Competition and pricing scenario", "Infrastructure and digital findings", "Survey findings", "Model and CCTV evidence status",
                "Methodology and limitations", "What a scale-up needs"):
        assert sec in full, sec
    for title in tabs["recommendations"]["title"]:
        assert _norm(title) in full, title
    # descriptive and model-based survey results are visibly separated; model metrics carry the caveat
    assert "Descriptive findings" in full and "Illustrative model" in full
    assert "Synthetic demonstration metrics" in full
    assert "OpenStreetMap" in full and "synthetic" in full.lower()
    assert "REC-001" in full and "Capture-share sensitivity" in full and "15%" in full and "35%" in full
    # CCTV status is read from the detector output, never hardcoded numbers
    assert "CCTV detector status" in full and "Detector output:" in full


def test_every_page_has_footer_and_page_number(default_pdf):
    pages = _pages(default_pdf)
    for i, text in enumerate(pages, 1):
        assert "Simulated data for demonstration" in text and "not GSRTC data" in text
        assert f"Page {i}" in text


def test_filtered_pdf_scopes_content(filtered_pdf, filtered_filters, tabs):
    full = " ".join(_pages(filtered_pdf))
    assert filtered_filters.describe() in full
    rs = tabs["route_summary"]
    in_scope = set(F.scope_routes(rs, "Rajkot-Somnath")["route_id"])
    recs = tabs["recommendations"]
    keep = F.filter_recommendations(recs, filtered_filters, rs)
    for title in keep["title"]:
        assert _norm(title) in full
    for title in recs.loc[~recs["recommendation_id"].isin(keep["recommendation_id"]), "title"]:
        assert _norm(title) not in full
    assert "L05" not in full.split("Route and demand findings")[1].split("Supply-gap findings")[0].replace("Rajkot", "")  # local routes absent
    assert in_scope  # sanity


def test_currency_glyph_or_fallback(default_pdf):
    fonts = P.setup_fonts()
    full = " ".join(_pages(default_pdf))
    if fonts.unicode:
        assert fmt.RUPEE in full
    else:
        assert "Rs." in full and fmt.RUPEE not in full
    assert P.fallback_text("₹1,23,456 – x") == "Rs.1,23,456 - x"


def test_pdf_degrades_without_optional_tables(tabs):
    slim = {k: v for k, v in tabs.items() if k in ("route_summary", "route_kpis", "routes", "stops", "zones")}
    data = P.build_report_pdf(F.Filters(), slim, now=NOW)
    full = " ".join(_pages(data))
    assert "Not available" in full and "Nothing has been substituted" in full
    assert "Simulated data for demonstration" in full


def test_pdf_requires_route_summary():
    with pytest.raises(FileNotFoundError):
        P.build_report_pdf(F.Filters(), {})


def test_cli_writes_pdf(tmp_path, capsys):
    out = tmp_path / "r" / "report.pdf"
    assert P.main(["--out", str(out), "--corridor", "Rajkot-Somnath", "--day-type", "weekday", "--hours", "6", "23"]) == 0
    assert out.read_bytes().startswith(b"%PDF")
    assert "Simulated data for demonstration" in capsys.readouterr().out


@pytest.mark.parametrize("flt", [F.Filters(), F.Filters("Rajkot-Somnath", "weekday", 0, 24), F.Filters(F.LOCAL, "weekend", 6, 22),
                                 F.Filters("Rajkot-Ahmedabad", "festival", 17, 23)], ids=lambda x: x.corridor)
def test_report_totals_equal_dashboard_and_exports(tabs, flt):
    t = P.report_totals(flt, tabs)
    rs = tabs["route_summary"]
    scope = F.scope_routes(rs, flt.corridor)
    dash = Q.scope_kpis(scope)  # what Overview/Reports pages show
    assert t["boardings"] == int(scope["boardings"].sum()) == dash["boardings"]
    assert t["kpis"] == dash
    # CSV export totals equal the same numbers
    ctx = {"route_summary": rs, "route_stops": tabs["route_stops"], "stops": tabs["stops"]}
    built = X.build_exports({"route_summary": rs, "recommendations": tabs["recommendations"], "od_flows": tabs["od_flows"]}, flt, ctx, lambda n: None)
    assert int(built["route_summary"][0]["boardings"].sum()) == t["boardings"]
    assert len(built["recommendations"][0]) == t["n_recommendations"]
    assert float(built["od_flows"][0]["passenger_count"].sum()) == pytest.approx(t["od_passengers"])
    # the PDF prints exactly these numbers
    full = " ".join(_pages(P.build_report_pdf(flt, tabs, now=NOW)))
    assert fmt.number(t["boardings"]) in full
    assert fmt.number(dash["avg_boardings_per_day"]) in full


# ---------------------------------------------------------------------------------------------------------------- CSV exports
def _ctx(tabs):
    return {"route_summary": tabs["route_summary"], "route_stops": tabs["route_stops"], "stops": tabs["stops"]}


def test_all_exports_carry_provenance_and_limitations(tabs):
    ex = {n: tabs[n] for n in X.EXPORTS if n in tabs}
    assert {"competition_analysis", "predictions", "ridership_model_metrics", "route_paths", "route_candidates", "survey_model_metrics",
            "survey_model_coefficients"} <= set(ex), "new M7 export tables should be generated in this environment"
    built = X.build_exports(ex, F.Filters(), _ctx(tabs), lambda n: sources.provenance(n))
    for name, (df, data) in built.items():
        text = data.decode("utf-8")
        head = [ln for ln in text.splitlines() if ln.startswith("#")]
        assert head[0].startswith("# GSRTC Mobility Intelligence export:")
        assert any(config.SIMULATION_BADGE_TEXT in ln for ln in head)
        assert any(ln.startswith("# seed: ") and "unknown" not in ln for ln in head), name
        assert any(ln.startswith("# generated_at: ") and "unknown" not in ln for ln in head), name
        assert any(ln.startswith("# filters: ") for ln in head)
        assert sum(ln.startswith("# limitation: ") for ln in head) == len(X.LIMITATIONS)
        assert f"# rows: {len(df)}" in head
        back = pd.read_csv(io.StringIO(text), comment="#")
        assert len(back) == len(df) and list(back.columns) == list(df.columns)
    for n in ("competition_analysis", "predictions", "ridership_model_metrics", "route_candidates", "survey_model_metrics"):
        assert any(ln.startswith("# note: ") for ln in built[n][1].decode().splitlines()), n


def test_new_export_filters(tabs):
    ctx = _ctx(tabs)
    comp = tabs["competition_analysis"]
    f = F.Filters("Rajkot-Somnath", "weekday", 18, 22)
    c = X.filter_table("competition_analysis", comp, f, ctx)
    assert len(c) and set(c["route_pair"]) == {"Rajkot-Somnath"} and set(c["day_type"]) == {"weekday"} and c["hour"].between(18, 21).all()
    assert X.filter_table("competition_analysis", comp, F.Filters(F.LOCAL), ctx).empty
    pr = X.filter_table("predictions", tabs["predictions"], F.Filters("Rajkot-Somnath", "weekday"), ctx)
    assert set(pr["entity_id"]) <= set(F.route_ids(tabs["route_summary"], "Rajkot-Somnath")) and set(pr["day_type"]) <= {"weekday"}
    assert len(X.filter_table("ridership_model_metrics", tabs["ridership_model_metrics"], f, ctx)) == len(tabs["ridership_model_metrics"])
    cands = X.filter_table("route_candidates", tabs["route_candidates"], F.Filters("Rajkot-Somnath"), ctx)
    assert len(cands) and cands["corridor"].str.startswith("Rajkot-Somnath").all()
    assert len(X.filter_table("route_candidates", tabs["route_candidates"], F.Filters(F.LOCAL), ctx)) > 0
    paths = X.filter_table("route_paths", tabs["route_paths"], F.Filters("Rajkot-Somnath"), ctx)
    assert set(paths["route_id"]) <= set(F.route_ids(tabs["route_summary"], "Rajkot-Somnath"))


def test_candidate_score_may_be_null_exports_cleanly(tabs):
    cands = tabs["route_candidates"].copy()
    cands.loc[cands.index[0], "score"] = float("nan")
    data = X.to_csv_bytes("route_candidates", cands, F.Filters(), sources.provenance("route_candidates")).decode()
    back = pd.read_csv(io.StringIO(data), comment="#")
    assert back["score"].isna().sum() == 1


def test_methodology_note_markdown():
    md = TXT.methodology_markdown("Corridor: All", "2026-10-26 09:30 UTC")
    assert config.SIMULATION_BADGE_TEXT in md and "## Methodology" in md and "## Limitations" in md and "ETM" in md
    assert re.search(r"seed 42", md)
