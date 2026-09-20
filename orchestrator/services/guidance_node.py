# -*- coding: utf-8 -*-
"""The workflow node for labelled general guidance (owner policy 2026-09-19).

The routing contract sends a building-knowledge question that needs no building data here
(``guidance_shape`` decides). The answer itself is written by ``general_guidance.general_guidance``
(question, persona) -> text; this module only connects it to the workflow and guarantees the two
things the policy promises:

* the answer is LABELLED as general guidance, not as something this building's records say -- if
  the writer's text does not already carry the label, it is added, so no path can ship an
  unlabelled textbook answer;
* a writer that is missing, slow to fail or empty never costs the turn: the reader gets an honest
  sentence that says what happened and what to ask instead, not a blank and not a guess.

Nothing here reads a sensor, so the fetch-budget refusal ("that question reaches N sensors") is
unreachable from this lane by construction.
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Optional, Union

from shared.utils import get_logger

logger = get_logger(__name__)

#: The intent this node serves.
GUIDANCE_INTENT = "general_guidance"

#: The label every guidance answer carries.
LABEL = "General guidance (not from this building's records):"

GuidanceFn = Callable[[str, Optional[str]], Union[str, Awaitable[str]]]


def labelled(text: str) -> str:
    """``text`` with the general-guidance label at the front, added only when it is missing."""
    body = (text or "").strip()
    if not body:
        return ""
    if body.lower().startswith("general guidance"):
        return body
    return f"{LABEL} {body}"


def unavailable_text() -> str:
    """What the reader is told when no guidance could be written."""
    return (
        "I couldn't write general guidance for that just now. If you tell me which room or system "
        "you mean, I can look at this building's own readings instead."
    )


async def general_guidance_node(state: Any, guidance_fn: Optional[GuidanceFn] = None) -> Any:
    """Answer a building-knowledge question as labelled general guidance."""
    question = state.messages[-1].content if getattr(state, "messages", None) else ""
    persona = getattr(state, "persona", None)
    logger.info(f"[general_guidance] persona={persona!r} q={question[:60]!r}")

    text = ""
    try:
        if guidance_fn is None:
            from orchestrator.services.general_guidance import general_guidance as guidance_fn
        result = guidance_fn(question, persona)
        if inspect.isawaitable(result):
            result = await result
        text = labelled(str(result or ""))
    except Exception as exc:
        logger.warning(f"[general_guidance] writer unavailable: {exc}")

    state.intermediate_results["dialogue_response"] = text or unavailable_text()
    state.intermediate_results["general_guidance"] = {"written": bool(text)}
    state.current_intent = GUIDANCE_INTENT
    return state
