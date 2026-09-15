"""BUG-595: a chart caption said "a steady baseline of ~400-500 ppm" of a day whose minimum was 704."""

import asyncio
from types import SimpleNamespace as NS

import pytest

from orchestrator.agents import visualization_agent as mod

pytestmark = pytest.mark.unit


def test_the_caption_prompt_carries_statistics_over_every_row(monkeypatch):
    seen = {}

    async def fake_generate(prompt, **kw):
        seen["prompt"] = prompt
        return "caption"

    monkeypatch.setattr(mod.llm_manager, "generate", fake_generate)
    agent = mod.VisualizationAgent.__new__(mod.VisualizationAgent)
    rows = [
        {"uuid": "u", "timestamp": "2026-09-15 03:08:06", "value": 704},
        {"uuid": "u", "timestamp": "2026-09-15 15:49:15", "value": 916},
    ]
    state = NS(intermediate_results={"sensor_metadata": {"u": {"label": "CO2 2.01", "unit": "ppm"}}},
               building_id=None)
    asyncio.run(agent._generate_description("Plot CO2", "line_chart", {"data": rows}, state=state))
    assert "minimum 704" in seen["prompt"] and "maximum 916" in seen["prompt"]
    assert "must appear in the statistics above" in seen["prompt"]
    assert "[{'uuid'" not in seen["prompt"]  # no raw-data slice
