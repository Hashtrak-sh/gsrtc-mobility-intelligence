"""M6 CCTV proof-of-concept tests: pure counting/aggregation logic, output contract, page states. Fast; no cv libs needed."""
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import config
from modules.analytics import cctv as CC
from modules.cv import aggregate as AG

ROOT = Path(__file__).resolve().parents[1]
A, B = (0.0, 100.0), (200.0, 100.0)  # horizontal line y=100, directed left->right; below (y>100) is the positive side


def test_side_of_line():
    assert AG.side_of_line((50, 150), A, B) == 1
    assert AG.side_of_line((50, 50), A, B) == -1
    assert AG.side_of_line((50, 100), A, B) == 0


def test_crossing_direction_and_segment_extent():
    assert AG.crossing_direction((50, 90), (50, 110), A, B) == "inbound"
    assert AG.crossing_direction((50, 110), (50, 90), A, B) == "outbound"
    assert AG.crossing_direction((50, 90), (50, 99), A, B) is None      # same side
    assert AG.crossing_direction((300, 90), (300, 110), A, B) is None   # beyond the segment end
    assert AG.crossing_direction((50, 90), (50, 110), A, B, positive_is="outbound") == "outbound"


def test_minute_bucket_and_line_counter_counts_each_object_once():
    lc = AG.LineCounter(A, B)
    # object 1 goes down across the line at t=59 (minute 0); object 2 crosses up at t=61 (minute 1); object 3 jitters on one side
    lc.update(58, [(1, (50, 90), "person"), (2, (80, 120), "car"), (3, (10, 20), "person")])
    lc.update(59, [(1, (50, 110), "person"), (2, (80, 118), "car"), (3, (10, 30), "person")])
    lc.update(60, [(1, (50, 130), "person"), (2, (80, 110), "car"), (3, (10, 25), "person")])
    lc.update(61, [(1, (50, 150), "person"), (2, (80, 90), "car"), (3, (10, 20), "person")])
    assert lc.tallies == {(0, "inbound", "person"): 1, (1, "outbound", "car"): 1}
    assert lc.totals() == {("inbound", "person"): 1, ("outbound", "car"): 1}
    assert AG.minute_bucket(59.9) == 0 and AG.minute_bucket(60.0) == 1


def test_tallies_to_frame_has_explicit_zeros_and_valid_schema():
    df = AG.tallies_to_frame({(1, "inbound", "person"): 3}, "LOC", n_minutes=3, classes=("person",))
    AG.validate_output(df)
    assert list(df.columns) == AG.OUTPUT_COLUMNS
    assert df["count"].sum() == 3
    inb = df[(df["direction"] == "inbound") & (df["class"] == "person")].sort_values("clip_minute")
    assert inb["count"].tolist() == [0, 3, 0]
    assert (df["measurement_method"] == "actual_detector").all() and (df["time_basis"] == "clip_relative").all()
    assert df["timestamp_min"].dt.minute.tolist() == df["clip_minute"].tolist()


def test_no_identity_columns_and_validation_rejects_them():
    df = AG.tallies_to_frame({}, "LOC", 1)
    assert not [c for c in df.columns if any(p in c.lower() for p in ("track", "face", "identity"))]
    with pytest.raises(ValueError):
        AG.validate_output(df.assign(track_id=1))
    with pytest.raises(ValueError):
        AG.validate_output(df.assign(count=-1))
    with pytest.raises(ValueError):
        AG.validate_output(df.assign(measurement_method="synthetic"))


def test_modules_import_without_cv_libraries():
    code = ("import sys; import modules.cv.aggregate, modules.cv.count_video, modules.analytics.cctv; "
            "bad=[m for m in ('cv2','torch','ultralytics','supervision') if m in sys.modules]; assert not bad, bad")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_committed_line_config_is_valid():
    cfg = json.loads((ROOT / "modules/cv/configs/a-morning-on-route-r014.lines.json").read_text(encoding="utf-8"))
    assert cfg["line"]["positive_is"] in ("inbound", "outbound") and cfg["recording_start"] is None
    assert set(cfg["classes"]) <= set(AG.COCO_TO_CLASS.values())


# ------------------------------------------------------------------ status + page
def _fixture_outputs(d: Path, with_prov=True):
    d.mkdir(parents=True, exist_ok=True)
    AG.tallies_to_frame({(0, "inbound", "person"): 4, (1, "outbound", "person"): 2}, "FIX", 2).to_parquet(d / "cctv_detector_counts.parquet", index=False)
    if with_prov:
        (d / "cctv_detector_counts.provenance.json").write_text(json.dumps({
            "generated_at_utc": "2026-01-01T00:00:00+00:00", "model": {"name": "fixture.pt", "family": "fixture"},
            "versions": {"ultralytics": "x", "supervision": "y"}, "thresholds": {"conf": 0.25, "iou": 0.5, "imgsz": 640}, "stride": 3,
            "clip": {"filename": "f.mp4", "duration_s": 120, "width": 10, "height": 10},
            "segment": {"start_s": 0, "processed_s": 120, "full_clip": True}, "frames_processed": 10, "processing_seconds": 1.0,
            "line_config": {"description": "fixture line"}, "annotated_video": None}), encoding="utf-8")


def _page(monkeypatch, tmp_path, outputs: str):
    d = tmp_path / "det"
    if outputs == "present":
        _fixture_outputs(d)
    monkeypatch.setattr(CC, "io", type("IO", (), {
        "table_exists": staticmethod(lambda n, l, b=None: (d / f"{n}.parquet").is_file()),
        "provenance_path": staticmethod(lambda n, l, b=None: d / f"{n}.provenance.json"),
        "layer_dir": staticmethod(lambda l, b=None: d)}))
    import modules.data.io as real_io
    orig_read = real_io.read_table
    monkeypatch.setattr(real_io, "read_table", lambda n, l, b=None: pd.read_parquet(d / f"{n}.parquet") if n == CC.DETECTOR_TABLE else orig_read(n, l, b))
    return AppTest.from_file(str(ROOT / "pages/7_CCTV_Analytics.py"), default_timeout=90).run()


needs_data = pytest.mark.skipif(not (config.PROCESSED_DIR / "cctv_hourly_profile.parquet").is_file(), reason="processed data not generated")


@needs_data
def test_detector_output_status_states(monkeypatch, tmp_path):
    monkeypatch.setattr(CC, "io", type("IO", (), {
        "table_exists": staticmethod(lambda n, l, b=None: (tmp_path / f"{n}.parquet").is_file()),
        "provenance_path": staticmethod(lambda n, l, b=None: tmp_path / f"{n}.provenance.json"),
        "layer_dir": staticmethod(lambda l, b=None: tmp_path)}))
    assert CC.detector_output_status()["state"] == "no_output"
    _fixture_outputs(tmp_path, with_prov=False)
    assert CC.detector_output_status()["state"] == "no_output"  # table without provenance is not "available"
    _fixture_outputs(tmp_path)
    assert CC.detector_output_status()["state"] == "available"


@needs_data
def test_page_without_detector_output(monkeypatch, tmp_path):
    at = _page(monkeypatch, tmp_path, "absent")
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(m.value for m in at.markdown) + " ".join(e.value for e in [*at.error, *at.info])
    assert "Detector output not available" in text and "no real counts" in text
    assert any("count_video" in c.value for c in at.code)
    assert any("Column" in d.value.columns for d in at.dataframe)
    assert "Inbound crossings (clip)" not in " ".join(x.value for x in at.markdown)


@needs_data
def test_page_with_detector_output(monkeypatch, tmp_path):
    at = _page(monkeypatch, tmp_path, "present")
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(x.value for x in at.markdown)
    assert "Inbound crossings (clip)" in text and ">4<" in text
    assert len(at.metric) <= 4
    text += " ".join(c.value for c in [*at.caption, *at.info])
    assert "fixture.pt" in text and "clip-relative" in text.lower() and "not a live" in text.lower()
    assert any("SYNTHETIC" in w.value for w in at.warning)  # section 1 still labelled
