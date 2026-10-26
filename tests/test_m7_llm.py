"""Milestone 7 (part A): optional LLM client, summary validation, rule-based fallback and the Reports / Demand pages. No real API calls."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import config
from modules.data import io as dio
from modules.llm import client as C
from modules.llm import rules as R
from modules.llm import summary as S
from modules.reporting import sources

ROOT = Path(__file__).resolve().parents[1]
HAVE_DATA = dio.table_exists("route_summary", "processed")
try:
    import anthropic
except ImportError:  # the LLM extra is optional: tests that need the SDK are skipped, the rest still run
    anthropic = None
needs_sdk = pytest.mark.skipif(anthropic is None, reason="anthropic not installed (optional)")

SUMMARY = {"notice": "synthetic", "tables": {
    "route_summary": {"routes": [{"route_id": "L05", "load_factor_pct": 35.4, "avg_boardings_per_day": 725, "peak_hour_window": "07:00-08:00"}]},
    "recommendations": {"items": [{"id": "REC-002", "time_window": "07:00-09:00", "additional_departures": 3, "projected_load_factor_after": 0.78}]}}}
GOOD = {"answer": "L05 has a load factor of 35.4% and 725 boardings per day (route_summary).", "supported": True,
        "cited_tables": ["route_summary"], "caveats": "Synthetic data.",
        "figures_used": [{"label": "L05 load factor", "value": "35.4%", "table": "route_summary"},
                         {"label": "L05 boardings per day", "value": "725", "table": "route_summary"}]}


def _resp(payload=None, text=None, stop="end_turn"):
    body = text if text is not None else json.dumps(payload)
    return SimpleNamespace(stop_reason=stop, stop_details=SimpleNamespace(category="x"), content=[SimpleNamespace(type="text", text=body)])


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "cache_dir", lambda: tmp_path / "llm_cache")
    monkeypatch.setattr(C, "_secret", lambda name: None)
    monkeypatch.delenv("GSRTC_LLM_MODEL", raising=False)
    for v in C.CRED_VARS:
        monkeypatch.delenv(v, raising=False)


@pytest.fixture
def key(monkeypatch):
    if anthropic is None:
        pytest.skip("anthropic not installed (optional)")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")


def install(monkeypatch, *responses) -> FakeClient:
    fc = FakeClient(responses)
    monkeypatch.setattr(C, "_make_client", lambda: fc)
    return fc


def _exc(cls):
    e = cls.__new__(cls)
    Exception.__init__(e, "boom sk-test-not-a-real-key")
    return e


# ---------------------------------------------------------------------------------------------------------------- status
def test_status_false_without_key():
    ok, reason = C.llm_status()
    assert ok is False and "ANTHROPIC_API_KEY" in reason


def test_status_true_with_key_and_never_leaks_it(key):
    ok, reason = C.llm_status()
    assert ok and "sk-test" not in reason and C.model_name() in reason


@needs_sdk
def test_status_accepts_auth_token(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    assert C.llm_status()[0] and C._credentials() == {"auth_token": "tok"}


def test_status_false_without_package(monkeypatch, key):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    ok, reason = C.llm_status()
    assert not ok and "anthropic" in reason


def test_model_default_and_override(monkeypatch):
    assert C.model_name() == "claude-opus-5-5"
    monkeypatch.setenv("GSRTC_LLM_MODEL", "claude-test-model")
    assert C.model_name() == "claude-test-model"


# ---------------------------------------------------------------------------------------------------------------- ask_the_data
def test_ask_with_mock_returns_parsed_result_and_uses_current_api_shape(monkeypatch, key):
    fc = install(monkeypatch, _resp(GOOD))
    r = C.ask_the_data("Which route has the lowest load?", SUMMARY)
    assert r.status == "ok" and r.supported and r.cited_tables == ["route_summary"] and r.machine_generated
    assert all(f["verified"] for f in r.figures_used) and len(r.figures_used) == 2
    kw = fc.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default" and kw["betas"]
    assert kw["output_config"]["format"]["type"] == "json_schema" and kw["output_config"]["format"]["schema"]["additionalProperties"] is False
    for banned in ("temperature", "thinking", "tool_choice", "top_p", "top_k"):
        assert banned not in kw
    assert [m["role"] for m in kw["messages"]] == ["user"]  # no assistant prefill
    assert kw["system"][-1]["cache_control"] == {"type": "ephemeral"} and S.summary_json(SUMMARY) == kw["system"][-1]["text"]


def test_invented_figure_flags_unsupported(monkeypatch, key):
    bad = {**GOOD, "answer": "L05 load factor is 61.2%.", "figures_used": [{"label": "L05 load factor", "value": "61.2%", "table": "route_summary"}]}
    r = (install(monkeypatch, _resp(bad)), C.ask_the_data("q1", SUMMARY))[1]
    assert r.status == "unsupported" and not r.supported
    assert any("61.2" in w for w in r.warnings) and r.figures_used[0]["verified"] is False


def test_invented_table_and_text_number_and_time(monkeypatch, key):
    bad = {**GOOD, "answer": "At 19:00 about 1,234 passengers board.", "cited_tables": ["route_summary", "tickets"], "figures_used": []}
    install(monkeypatch, _resp(bad))
    r = C.ask_the_data("q2", SUMMARY)
    assert r.status == "unsupported"
    w = " ".join(r.warnings)
    assert "tickets" in w and "1234" in w and "19:00" in w
    assert r.cited_tables == ["route_summary"]  # the invented table is not presented as cited


def test_percentage_vs_ratio_and_exact_strings_are_accepted():
    p = {"answer": "Projected load factor is 78% for REC-002 in 07:00-09:00.", "supported": True, "cited_tables": ["recommendations"],
         "figures_used": [{"label": "after", "value": "78%", "table": "recommendations"}, {"label": "window", "value": "07:00-09:00", "table": "recommendations"},
                          {"label": "id", "value": "REC-002", "table": "recommendations"}]}
    v = S.validate_answer(p, SUMMARY)
    assert v.supported and not v.warnings


def test_model_declaring_unsupported_is_kept_unsupported(monkeypatch, key):
    install(monkeypatch, _resp({"answer": "The summary does not contain fare data.", "supported": False, "cited_tables": [], "figures_used": [], "caveats": ""}))
    r = C.ask_the_data("What is the Rajkot-Mumbai fare?", SUMMARY)
    assert r.status == "unsupported" and not r.supported and not r.warnings


def test_refusal_and_max_tokens_and_bad_json(monkeypatch, key):
    install(monkeypatch, _resp(GOOD, stop="refusal"))
    r = C.ask_the_data("q3", SUMMARY)
    assert r.status == "refused" and r.answer == ""
    install(monkeypatch, _resp(GOOD, stop="max_tokens"))
    r = C.ask_the_data("q4", SUMMARY)
    assert r.status == "truncated" and r.answer == ""
    install(monkeypatch, _resp(text="not json"))
    assert C.ask_the_data("q5", SUMMARY).status == "error"
    install(monkeypatch, SimpleNamespace(stop_reason="end_turn", content=[]))
    assert C.ask_the_data("q6", SUMMARY).status == "error"


_ERRS = [] if anthropic is None else [
    (anthropic.BadRequestError, "bad request"), (anthropic.AuthenticationError, "Authentication"), (anthropic.PermissionDeniedError, "permitted"),
    (anthropic.NotFoundError, "not found"), (anthropic.RateLimitError, "Rate limit"), (anthropic.APITimeoutError, "timed out"),
    (anthropic.APIConnectionError, "network"), (anthropic.APIStatusError, "server error")]


@pytest.mark.parametrize("cls, needle", _ERRS)
def test_api_errors_are_handled_without_leaking_secrets(monkeypatch, key, cls, needle):
    install(monkeypatch, _exc(cls))
    r = C.ask_the_data("will fail " + cls.__name__, SUMMARY)
    assert r.status == "error" and needle.lower() in r.message.lower()
    assert "sk-test" not in r.message and "boom" not in r.message


def test_unexpected_exception_is_contained(monkeypatch, key):
    install(monkeypatch, RuntimeError("secret sk-test"))
    r = C.ask_the_data("odd", SUMMARY)
    assert r.status == "error" and "sk-test" not in r.message


def test_cache_hit_avoids_second_call_and_errors_are_not_cached(monkeypatch, key, tmp_path):
    fc = install(monkeypatch, _resp(GOOD))
    a = C.ask_the_data("  Which route has   the lowest load? ", SUMMARY)
    b = C.ask_the_data("Which route has the lowest load?", SUMMARY)
    assert len(fc.calls) == 1 and not a.cached and b.cached and b.answer == a.answer and b.status == "ok"
    assert len(list((tmp_path / "llm_cache").glob("*.json"))) == 1
    assert "sk-test" not in next((tmp_path / "llm_cache").glob("*.json")).read_text()
    C.ask_the_data("A different question", SUMMARY)
    assert len(fc.calls) == 2
    other = {**SUMMARY, "notice": "changed"}
    C.ask_the_data("Which route has the lowest load?", other)  # different summary hash -> different key
    assert len(fc.calls) == 3
    fe = install(monkeypatch, _exc(anthropic.RateLimitError))
    C.ask_the_data("err once", SUMMARY)
    C.ask_the_data("err once", SUMMARY)
    assert len(fe.calls) == 2


def test_unavailable_makes_no_call_and_validates_input(monkeypatch):
    monkeypatch.setattr(C, "_make_client", lambda: (_ for _ in ()).throw(AssertionError("client must not be created")))
    r = C.ask_the_data("anything", SUMMARY)
    assert r.status == "unavailable" and "ANTHROPIC_API_KEY" in r.message
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert C.ask_the_data("", SUMMARY).status == "error"
    assert C.ask_the_data("x" * 600, SUMMARY).status == "error"


# ---------------------------------------------------------------------------------------------------------------- themes
THEME_TEXTS = ["The bus is often late and crowded.", "I would switch if the AC worked.", "Need real time info on bus arrival.", "The bus is often late and crowded."]


def test_theme_summary_validates_quotes_caches_and_samples_deterministically(monkeypatch, key):
    payload = {"themes": [{"theme": "Punctuality", "description": "Late buses.", "approx_share_pct": 40,
                           "example_quotes": ["The bus is often late and crowded.", "invented quote"]},
                          {"theme": "Odd", "description": "x", "approx_share_pct": 400, "example_quotes": []}]}
    fc = install(monkeypatch, _resp(payload))
    r = C.summarise_themes(THEME_TEXTS)
    assert r.status == "ok" and r.n_texts_used == 3 and r.machine_generated
    assert r.themes[0]["example_quotes"] == ["The bus is often late and crowded."]
    assert r.themes[1]["approx_share_pct"] is None
    assert any("invented" in w or "not found verbatim" in w for w in r.warnings)
    again = C.summarise_themes(list(reversed(THEME_TEXTS)))
    assert again.cached and len(fc.calls) == 1
    big = [f"text number {i:04d}" for i in range(1000)]
    assert C.sample_texts(big) == C.sample_texts(list(reversed(big))) and len(C.sample_texts(big)) == 200


@needs_sdk
def test_theme_summary_unavailable_and_error(monkeypatch):
    assert C.summarise_themes(THEME_TEXTS).status == "unavailable"
    assert C.summarise_themes([]).status == "error"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    install(monkeypatch, _resp(GOOD, stop="refusal"))
    assert C.summarise_themes(THEME_TEXTS).status == "refused"


# ---------------------------------------------------------------------------------------------------------------- summary
@pytest.mark.skipif(not HAVE_DATA, reason="processed tables not generated")
def test_build_summary_is_deterministic_compact_and_covers_tables():
    t = sources.load_tables()
    a, b = S.build_summary(t), S.build_summary(t)
    assert S.summary_json(a) == S.summary_json(b) and S.summary_hash(a) == S.summary_hash(b)
    assert {"route_summary", "route_scores", "recommendations", "hourly_demand_supply", "competition_analysis", "survey_responses",
            "ridership_model_metrics", "survey_model_metrics"} <= set(S.table_names(a))
    text = S.summary_json(a)
    assert len(text) < 40_000 and "generated_at" not in text and config.SIMULATION_BADGE_TEXT in text
    rs = t["route_summary"].set_index("route_id")
    row = next(r for r in a["tables"]["route_summary"]["routes"] if r["route_id"] == "L05")
    assert row["load_factor_pct"] == pytest.approx(rs.loc["L05", "load_factor_pct"], abs=0.05)
    # a real figure from the summary passes validation; an invented one fails
    ok = {"answer": f"L05 load factor is {row['load_factor_pct']}%.", "supported": True, "cited_tables": ["route_summary"], "figures_used": []}
    assert S.validate_answer(ok, a).supported
    assert not S.validate_answer({**ok, "answer": "L05 load factor is 12.3%."}, a).supported


# ---------------------------------------------------------------------------------------------------------------- rule-based
@pytest.fixture(scope="module")
def tabs():
    if not HAVE_DATA:
        pytest.skip("processed tables not generated")
    return sources.load_tables()


def test_rule_answers_are_labelled_and_match_tables(tabs):
    rs = tabs["route_summary"]
    a = R.answer("Which route has the highest load factor?", tabs)
    top = rs.sort_values(["load_factor_pct", "route_id"], ascending=[False, True]).iloc[0]
    assert a.supported and a.label == "Rule-based answer, not an LLM" and a.cited_tables == ["route_summary"]
    assert top["route_id"] in a.answer and f"{top['load_factor_pct']:.1f}%" in a.answer
    b = R.answer("which route carries the most passengers", tabs)
    top = rs.sort_values(["avg_boardings_per_day", "route_id"], ascending=[False, True]).iloc[0]
    assert top["route_id"] in b.answer and b.supported
    c = R.answer("What is the recommended evening Rajkot-Somnath action?", tabs)
    rec = tabs["recommendations"]
    exp = rec[(rec["corridor"] == "Rajkot-Somnath") & (rec["category"] == "add_service_corridor_slot")].iloc[0]
    assert exp["recommendation_id"] in c.answer and exp["title"] in c.answer and c.cited_tables == ["recommendations"]
    d = R.answer("What is the top recommended action?", tabs)
    assert rec.sort_values("priority_rank").iloc[0]["recommendation_id"] in d.answer
    e = R.answer("What would make private-vehicle users switch to the bus?", tabs)
    assert e.supported and e.cited_tables == ["survey_responses"] and "%" in e.answer
    f = R.answer("Where is the biggest competitive gap against private operators?", tabs)
    comp = tabs["competition_analysis"]
    best = comp[comp["day_type"] == "weekday"]["competitive_gap_score"].max()
    assert f.supported and f"{best:.1f}" in f.answer


def test_every_example_is_supported_and_unknown_is_unsupported(tabs):
    assert 4 <= len(R.EXAMPLES) <= 6
    for q in R.EXAMPLES:
        a = R.answer(q, tabs)
        assert a.supported and a.cited_tables, q
    u = R.answer("What will the weather be in Rajkot tomorrow?", tabs)
    assert not u.supported and "not one of the supported" in u.answer and u.cited_tables == []
    assert not R.answer("", tabs).supported


def test_rule_answer_reports_missing_table(tabs):
    a = R.answer("Which route has the highest load factor?", {})
    assert not a.supported and "route_summary" in a.answer


# ---------------------------------------------------------------------------------------------------------------- pages
pytestmark_pages = pytest.mark.skipif(not HAVE_DATA, reason="processed tables not generated")


def _md(at) -> str:
    return " ".join(m.value for m in at.markdown) + " " + " ".join(i.value for i in at.info) + " " + " ".join(c.value for c in at.caption)


@pytestmark_pages
def test_reports_page_without_key_shows_unavailable_examples_and_pdf_button():
    at = AppTest.from_file(str(ROOT / "pages/8_Reports.py"), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("LLM not configured" in i.value and "ANTHROPIC_API_KEY" in i.value for i in at.info)
    assert [b.label for b in at.button if b.label == "Generate PDF report"]
    assert any("not LLM answers" in m.value or "not an LLM" in m.value for m in at.markdown)
    # example lookups answer with the explicit rule-based label
    assert any("Rule-based answer, not an LLM" in m.value for m in at.markdown)
    at.selectbox(key="ask_example").set_value("Something else (unsupported)").run()
    at.text_input(key="ask_typed").set_value("What will the weather be?").run()
    assert any("not one of the supported" in w.value for w in at.warning)
    assert not any("machine-generated" in m.value.lower() for m in at.markdown)


@pytestmark_pages
def test_reports_page_generates_pdf_download():
    at = AppTest.from_file(str(ROOT / "pages/8_Reports.py"), default_timeout=120).run()
    next(b for b in at.button if b.label == "Generate PDF report").click().run()
    assert not at.exception, [e.value for e in at.exception]
    rep = at.session_state["report_pdf"]
    assert rep["bytes"].startswith(b"%PDF") and "Corridor: All" in rep["filters"]
    labels = [d.proto.label for d in at.get("download_button")]
    assert "Download PDF report" in labels and any("methodology" in x.lower() for x in labels)
    assert sum(1 for x in labels if x == "Download CSV") == len(__import__("modules.reporting.exports", fromlist=["x"]).EXPORTS)


@pytestmark_pages
def test_reports_page_with_mocked_llm_shows_cited_answer(monkeypatch, key, tmp_path):
    summ = S.build_summary(sources.load_tables())
    row = summ["tables"]["route_summary"]["routes"][0]
    payload = {"answer": f"{row['route_id']} carries {row['avg_boardings_per_day']} boardings a day.", "supported": True, "cited_tables": ["route_summary"],
               "caveats": "", "figures_used": [{"label": "boardings", "value": str(row["avg_boardings_per_day"]), "table": "route_summary"}]}
    fc = install(monkeypatch, _resp(payload))
    at = AppTest.from_file(str(ROOT / "pages/8_Reports.py"), default_timeout=60).run()
    assert not at.exception and not any("LLM not configured" in i.value for i in at.info)
    at.text_input(key="ask_q").set_value("How many boardings does the first route carry?").run()
    next(b for b in at.button if b.label == "Ask").click().run()
    assert not at.exception, [e.value for e in at.exception]
    txt = _md(at)
    assert "route_summary" in txt and "Machine-generated from data summaries" in txt and len(fc.calls) == 1


@pytestmark_pages
def test_demand_page_theme_panel_hidden_without_key_and_works_with_mock(monkeypatch):
    at = AppTest.from_file(str(ROOT / "pages/1_Demand_and_Surveys.py"), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert not [e for e in at.expander if "theme summary" in e.label.lower()]
    assert any("optional and needs an Anthropic API key" in c.value for c in at.caption)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    payload = {"themes": [{"theme": "Punctuality", "description": "Late buses.", "approx_share_pct": 30, "example_quotes": []}]}
    fc = install(monkeypatch, _resp(payload))
    at = AppTest.from_file(str(ROOT / "pages/1_Demand_and_Surveys.py"), default_timeout=60).run()
    assert [e for e in at.expander if "theme summary" in e.label.lower()]
    assert len(fc.calls) == 0  # runs only on click
    next(b for b in at.button if b.label == "Generate theme summary").click().run()
    assert not at.exception and len(fc.calls) == 1
    assert "Machine-generated from" in _md(at)


@pytestmark_pages
@pytest.mark.parametrize("page", ["pages/8_Reports.py", "pages/1_Demand_and_Surveys.py", "pages/0_Overview.py"])
def test_pages_work_without_anthropic_package(monkeypatch, page):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    assert C.llm_status()[0] is False
    at = AppTest.from_file(str(ROOT / page), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
