import pandas as pd
import pytest

from modules.data import io
from modules.data.provenance import Provenance, SourceType, make_provenance


def test_round_trip(tmp_path):
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    p = io.write_table(df, "zones", "synthetic", base_dir=tmp_path)
    assert p.is_file() and io.table_exists("zones", "synthetic", base_dir=tmp_path)
    pd.testing.assert_frame_equal(io.read_table("zones", "synthetic", base_dir=tmp_path), df)
    assert "zones" not in io.missing_tables("synthetic", base_dir=tmp_path)
    assert "stops" in io.missing_tables("synthetic", base_dir=tmp_path)


def test_missing_table_raises(tmp_path):
    assert not io.table_exists("zones", "processed", base_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        io.read_table("zones", "processed", base_dir=tmp_path)


def test_invalid_layer_and_name(tmp_path):
    with pytest.raises(ValueError):
        io.table_path("zones", "bogus", base_dir=tmp_path)
    with pytest.raises(ValueError):
        io.table_path("../evil", "raw", base_dir=tmp_path)


def test_provenance_sidecar_round_trip(tmp_path):
    prov = make_provenance("synthetic", assumptions={"k": 1}, description="t")
    io.write_table(pd.DataFrame({"a": [1]}), "routes", "synthetic", base_dir=tmp_path, provenance=prov)
    back = io.read_provenance("routes", "synthetic", base_dir=tmp_path)
    assert back == prov
    assert back.seed == 42 and back.source_type is SourceType.SYNTHETIC and back.is_simulated
    assert io.read_provenance("zones", "synthetic", base_dir=tmp_path) is None


def test_provenance_validation_and_json():
    with pytest.raises(ValueError):
        make_provenance("made_up")
    p = make_provenance(SourceType.OPENSTREETMAP, seed=None)
    assert not p.is_simulated
    assert Provenance.from_json(p.to_json()) == p
    assert {s.value for s in SourceType} >= {"synthetic", "openstreetmap", "manual_demo_input", "model_output"}
