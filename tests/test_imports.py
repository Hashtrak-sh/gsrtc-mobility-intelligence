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


# M7: every entry point is now built (the LLM client prints its status instead of raising NotImplementedError).
def test_llm_client_entry_point_runs(capsys):
    importlib.import_module("modules.llm.client").main()
    assert "LLM available" in capsys.readouterr().out
