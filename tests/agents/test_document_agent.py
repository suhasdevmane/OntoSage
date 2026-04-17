import importlib.util
import sys
import types
from pathlib import Path

import pytest

from shared.models import ConversationState, Message


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


def make_state(**kwargs) -> ConversationState:
    defaults = dict(
        conversation_id="test-conv-1",
        user_id="test-user",
        user_message="generate a report",
        messages=[Message(role="user", content="generate a report")],
        building_id="bldg1",
    )
    defaults.update(kwargs)
    return ConversationState(**defaults)


@pytest.mark.asyncio
async def test_document_agent_generates_download_url(monkeypatch):
    _ensure_pkg("orchestrator", Path("orchestrator"))
    _ensure_pkg("orchestrator.services", Path("orchestrator/services"))
    _ensure_pkg("orchestrator.agents", Path("orchestrator/agents"))

    document_builder = _load_module(
        "orchestrator.services.document_builder",
        Path("orchestrator/services/document_builder.py"),
    )
    doc_agent_mod = _load_module(
        "orchestrator.agents.document_agent",
        Path("orchestrator/agents/document_agent.py"),
    )
    DocumentAgent = doc_agent_mod.DocumentAgent

    def fake_render(
        self,
        report_data,
        report_type="summary",
        persona="general",
        output_format="html",
        title=None,
        template_name=None,
        **kwargs,
    ):
        return {
            "success": True,
            "content": "<html></html>",
            "filename": "report_summary_test.html",
            "format": output_format,
            "size_bytes": 13,
        }

    def fake_save_to_exports(self, result):
        return f"/exports/{result['filename']}"

    monkeypatch.setattr(document_builder.DocumentBuilder, "render", fake_render)
    monkeypatch.setattr(document_builder.DocumentBuilder, "save_to_exports", fake_save_to_exports)

    agent = DocumentAgent()
    state = make_state()
    result = await agent.generate(state, document_type="summary", output_format="html")

    assert result["success"] is True
    assert result["download_url"].startswith("/exports/")
    assert result["download_url"].endswith(".html")
