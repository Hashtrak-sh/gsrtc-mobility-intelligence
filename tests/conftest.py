"""Shared session fixtures: the full 42-day generation runs once per test session."""
import pytest

from modules.data_gen import generate


@pytest.fixture(scope="session")
def tables():
    """Full-period tables generated with the default seed and the repo OSM cache (if present). Not written to disk."""
    return generate.generate_all(write=False)


@pytest.fixture(scope="session")
def tables_fallback():
    """Full-period tables with the OSM cache ignored -> manual_demo_input coordinates."""
    return generate.generate_all(write=False, use_osm=False)
