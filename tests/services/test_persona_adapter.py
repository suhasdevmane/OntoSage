import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


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


@pytest.mark.asyncio
async def test_general_persona_passthrough():
    _ensure_pkg("orchestrator", Path("orchestrator"))
    _ensure_pkg("orchestrator.services", Path("orchestrator/services"))
    persona_mod = _load_module(
        "orchestrator.services.persona_adapter",
        Path("orchestrator/services/persona_adapter.py"),
    )
    PersonaAdapter = persona_mod.PersonaAdapter

    adapter = PersonaAdapter()
    original = "The temperature is 23C."
    result = await adapter.enhance(original, persona="general", intent="analytics")
    assert result == original


@pytest.mark.asyncio
async def test_unknown_persona_passthrough():
    _ensure_pkg("orchestrator", Path("orchestrator"))
    _ensure_pkg("orchestrator.services", Path("orchestrator/services"))
    persona_mod = _load_module(
        "orchestrator.services.persona_adapter",
        Path("orchestrator/services/persona_adapter.py"),
    )
    PersonaAdapter = persona_mod.PersonaAdapter

    adapter = PersonaAdapter()
    original = "The temperature is 23C."
    result = await adapter.enhance(original, persona="nonexistent", intent="analytics")
    assert result == original


@pytest.mark.asyncio
async def test_executive_persona_uses_llm():
    _ensure_pkg("orchestrator", Path("orchestrator"))
    _ensure_pkg("orchestrator.services", Path("orchestrator/services"))
    persona_mod = _load_module(
        "orchestrator.services.persona_adapter",
        Path("orchestrator/services/persona_adapter.py"),
    )
    PersonaAdapter = persona_mod.PersonaAdapter

    adapter = PersonaAdapter()
    mock_llm = SimpleNamespace(
        generate=AsyncMock(return_value="Executive summary with key metrics included.")
    )

    result = await adapter.enhance(
        "Detailed analytics output.",
        persona="executive",
        intent="analytics",
        llm_manager=mock_llm,
    )
    assert result == "Executive summary with key metrics included."


@pytest.mark.asyncio
async def test_llm_failure_returns_original():
    _ensure_pkg("orchestrator", Path("orchestrator"))
    _ensure_pkg("orchestrator.services", Path("orchestrator/services"))
    persona_mod = _load_module(
        "orchestrator.services.persona_adapter",
        Path("orchestrator/services/persona_adapter.py"),
    )
    PersonaAdapter = persona_mod.PersonaAdapter

    adapter = PersonaAdapter()
    original = "The temperature is 23C."
    mock_llm = SimpleNamespace(generate=AsyncMock(side_effect=RuntimeError("LLM unavailable")))

    result = await adapter.enhance(
        original,
        persona="executive",
        intent="analytics",
        llm_manager=mock_llm,
    )
    assert result == original
