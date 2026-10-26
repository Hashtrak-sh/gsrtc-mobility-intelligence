import pytest

import config


def test_seed_is_42():
    assert config.SEED == 42


def test_weights_sum_to_one_and_versioned():
    w = config.ROUTE_SCORE_WEIGHTS
    assert w.total() == pytest.approx(1.0)
    assert w.weight_version
    assert len(w.components()) == 7
    w.validate()


def test_bad_weights_rejected():
    with pytest.raises(ValueError):
        config.RouteScoreWeights(demand_potential=0.5).validate()


def test_bbox_contains_rajkot_and_somnath():
    assert config.PILOT_BBOX.contains(*config.RAJKOT_LAT_LON)
    assert config.PILOT_BBOX.contains(*config.SOMNATH_LAT_LON)
    assert not config.PILOT_BBOX.contains(28.6, 77.2)  # Delhi


def test_bbox_ordering():
    b = config.PILOT_BBOX
    assert b.south < b.north and b.west < b.east
    assert b.osmnx_bbox == (b.west, b.south, b.east, b.north)


def test_labels_and_paths():
    assert config.SIMULATION_BADGE_TEXT == "Simulated data for demonstration"
    assert config.PILOT_CITY == "Rajkot, Gujarat, India"
    assert config.PRIMARY_CORRIDOR in config.INTERCITY_CORRIDORS
    assert config.H3_RESOLUTION == 8
    assert config.SYNTHETIC_DIR.parent == config.DATA_DIR
    assert config.CROWDING_GAP_INDEX_THRESHOLD > 1.0
