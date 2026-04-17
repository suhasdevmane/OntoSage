import importlib.util
import sys
import types
from pathlib import Path


def _ensure_pkg(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(path.resolve())]
    sys.modules[name] = pkg


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_standards_engine_checks():
    _ensure_pkg("orchestrator", Path("orchestrator"))
    _ensure_pkg("orchestrator.services", Path("orchestrator/services"))
    std_mod = _load_module(
        "orchestrator.services.standards_engine",
        Path("orchestrator/services/standards_engine.py"),
    )
    StandardsEngine = std_mod.StandardsEngine

    engine = StandardsEngine()
    readings = {"temp_c": 24.5, "humidity_rh": 45.0}
    result = engine.check("ashrae55", readings)

    assert "overall_status" in result
    assert result["overall_status"] in {"compliant", "borderline", "non_compliant", "no_data"}
    assert isinstance(result.get("checks", []), list)


def test_standards_engine_unknown_standard():
    _ensure_pkg("orchestrator", Path("orchestrator"))
    _ensure_pkg("orchestrator.services", Path("orchestrator/services"))
    std_mod = _load_module(
        "orchestrator.services.standards_engine",
        Path("orchestrator/services/standards_engine.py"),
    )
    StandardsEngine = std_mod.StandardsEngine

    engine = StandardsEngine()
    result = engine.check("not_a_standard", {"temp_c": 22.0})
    assert "error" in result
