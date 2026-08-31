# -*- coding: utf-8 -*-
"""The document lane answers, declines, or degrades — but never pastes an unrelated passage.

Measured on the 111-question stakeholder probe: 38 of the 56 responses graded as answers
were pastes, and several answered a different question entirely. "Which plant can be
installed, commissioned and replaced through a credible route" returned the ASBESTOS
REGISTER, and it passed the existing distinctiveness check. Whether a passage answers a
question is not decidable from word overlap, so it is decided by trying.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from orchestrator.agents.capability_agent import CapabilityAgent
from orchestrator.llm_manager import llm_manager as _manager

pytestmark = pytest.mark.unit

HITS = [{"doc_name": "asbestos_register", "text": "Management survey 2024-09-14. AIB panels..."}]


async def _compose(reply):
    with patch.object(_manager, "generate", new=AsyncMock(return_value=reply)):
        return await CapabilityAgent._answer_from_passages("Which plant can be replaced?", HITS)


@pytest.mark.asyncio
async def test_a_passage_that_answers_is_used():
    answer, decided = await _compose("The chiller is replaceable via the basement route.")
    assert decided is True
    assert answer and "chiller" in answer


@pytest.mark.asyncio
async def test_a_passage_that_does_not_answer_is_declined_not_pasted():
    answer, decided = await _compose("NO_ANSWER_IN_SOURCE")
    assert decided is True, "the model decided — the passage does not answer"
    assert answer is None


@pytest.mark.asyncio
async def test_an_outage_decides_nothing_and_falls_back():
    """A degraded model must not silently switch this lane off.

    Without this distinction the document lane answered NOTHING whenever the LLM was
    unavailable — which three existing tests caught, and which is BUG-177's lesson: a
    degraded model's fallback text read like an answer and the harness scored it.
    """
    with patch.object(
        _manager, "generate", new=AsyncMock(side_effect=RuntimeError("circuit open"))
    ):
        answer, decided = await CapabilityAgent._answer_from_passages("anything", HITS)
    assert (answer, decided) == (None, False)


@pytest.mark.asyncio
async def test_an_empty_completion_decides_nothing():
    """An empty completion is an outage symptom, not a refusal (BUG-188)."""
    answer, decided = await _compose("")
    assert (answer, decided) == (None, False)


@pytest.mark.asyncio
async def test_no_passages_decides_nothing():
    answer, decided = await CapabilityAgent._answer_from_passages("anything", [])
    assert (answer, decided) == (None, False)


@pytest.mark.asyncio
async def test_the_refusal_token_is_recognised_case_insensitively():
    answer, decided = await _compose("no_answer_in_source")
    assert (answer, decided) == (None, True)
