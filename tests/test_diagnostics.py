import builtins

from modules import diagnostics


def test_runs_and_lists_all_deps():
    d = diagnostics.run_diagnostics()
    assert {s.module for s in d["optional_deps"]} == set(diagnostics.OPTIONAL_DEPS)
    assert set(d["data"]) == {"synthetic", "processed"}


def test_api_key_flag_never_leaks_value(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-value")
    assert diagnostics.api_key_configured() is True
    assert "sk-secret-value" not in repr(diagnostics.run_diagnostics())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "  ")
    assert diagnostics.api_key_configured() is False
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert diagnostics.api_key_configured() is False


def test_missing_dependency_does_not_crash(monkeypatch):
    monkeypatch.setattr(diagnostics, "_find", lambda m: False)
    deps = diagnostics.check_optional_deps()
    assert all(not s.available and s.version is None for s in deps)


def test_probe_does_not_import_heavy_modules(monkeypatch):
    real_import = builtins.__import__

    def guard(name, *a, **k):
        if name.split(".")[0] in {"ultralytics", "osmnx", "sklearn", "cv2"}:
            raise AssertionError(f"diagnostics imported {name}")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", guard)
    diagnostics.check_optional_deps()
