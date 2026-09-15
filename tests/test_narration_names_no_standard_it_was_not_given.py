"""BUG-582: an analytics narration may cite a standard only when one was supplied.

Rehearsed 3x on 2026-09-15: "WHO's recommended indoor threshold of 1,000 ppm", three different
"standard comfort ranges" for one question, and "a typical threshold of 300 kWh per floor" —
none of them in the prompt, all of them presented as fact.
"""

import pytest

from orchestrator.agents import analytics_agent as mod

pytestmark = pytest.mark.unit


async def _prompt_for(question, monkeypatch):
    seen = {}

    async def fake_generate(prompt, task_type=None):
        seen["prompt"] = prompt
        return "ok"

    monkeypatch.setattr(mod.llm_manager, "generate", fake_generate)
    agent = mod.AnalyticsAgent.__new__(mod.AnalyticsAgent)
    await agent._format_analysis({"success": True, "output": "Floor 0: mean 23.6"}, question, {})
    return seen["prompt"]


@pytest.mark.asyncio
async def test_no_reference_values_means_no_standard_and_no_compliance_icons(monkeypatch):
    prompt = await _prompt_for("Which floor is the warmest right now?", monkeypatch)
    assert "do NOT name any standard" in prompt
    assert "compliant with standards?" not in prompt
    assert "ASHRAE 55" not in prompt


@pytest.mark.asyncio
async def test_supplied_reference_values_may_be_cited_and_only_those(monkeypatch):
    prompt = await _prompt_for("Is floor 3 compliant with the comfort standard?", monkeypatch)
    assert "ASHRAE 55" in prompt
    assert "never cite one that is not listed" in prompt


@pytest.mark.asyncio
async def test_a_tie_is_reported_as_a_tie(monkeypatch):
    prompt = await _prompt_for("Which floor is the warmest right now?", monkeypatch)
    assert "TIED" in prompt
