# -*- coding: utf-8 -*-
"""BUG-832: the analytics narration prompt no longer tells the model to end every answer with advice.

Rule 5 of the prompt read "Ends with ONE concrete actionable recommendation if relevant", and the
model found it relevant every time: "Conduct a quick audit of the HVAC airflow ... rule out any
blockage" on a 0.2 C spread, "increase ventilation" on a 0.6 % humidity spread, "implement alerts
above 1,100 ppm" (the observed maximum). Advice is now requested only when the question asks for it
(the same predicate the output validators use), and the output validators remove what still slips
through.
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
async def test_a_factual_question_is_told_to_give_no_recommendation(monkeypatch):
    prompt = await _prompt_for("Which floor is the warmest right now?", monkeypatch)
    assert "Gives NO recommendation" in prompt
    assert "actionable recommendation" not in prompt and "actionable response" not in prompt


@pytest.mark.asyncio
async def test_a_question_that_asks_for_advice_is_told_to_give_one(monkeypatch):
    prompt = await _prompt_for("What should I do about the warm floors?", monkeypatch)
    assert "ONE concrete recommendation" in prompt
    assert "Gives NO recommendation" not in prompt


@pytest.mark.asyncio
async def test_the_prompt_asks_for_counts_that_match_their_lists_and_same_instant_deltas(
    monkeypatch,
):
    prompt = await _prompt_for("What is the delta-T across the heating circuit?", monkeypatch)
    assert "every count or average you state must match the items you list" in prompt
    assert "SAME" in prompt and "never subtract one series' minimum" in prompt
