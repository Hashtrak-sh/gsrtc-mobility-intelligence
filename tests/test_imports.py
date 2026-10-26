import importlib
import pkgutil

import pytest

import modules


def _all_modules() -> list[str]:
    return sorted(m.name for m in pkgutil.walk_packages(modules.__path__, "modules."))


@pytest.mark.parametrize("name", _all_modules())
def test_module_importable(name):
    importlib.import_module(name)


def test_expected_packages_present():
    names = set(_all_modules())
    for pkg in ("data_gen", "data", "analytics", "routing", "survey",
                "competition", "cv", "llm", "reporting", "ui"):
        assert f"modules.{pkg}" in names


@pytest.mark.parametrize("name", [
    "modules.cv.count_video", "modules.llm.client",
])
def test_unbuilt_entry_points_fail_loudly(name):
    with pytest.raises(NotImplementedError):
        importlib.import_module(name).main()
