"""The instructed assistant's action loop (spec §2): structured output, at most 8 steps.

``llm_manager`` offers JSON-schema-validated generation but no native tool calling, so each step asks
for one JSON object naming an action. A tool result goes back into the transcript (compacted to a
fixed budget, the cut stated); ``final_answer`` ends the loop. A provider failure (gateway down, empty
completion) is recorded as an outcome, exactly as an OntoSage turn's would be.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from .tools import TOOL_CATALOGUE, TOOL_NAMES, Toolbox, compact

MAX_STEPS = 8
TIME_LIMIT_S = 300  # the same per-question budget as an OntoSage turn (requirement R8)

STEP_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["action"],
    "properties": {
        "thought": {"type": "string"},
        "action": {"type": "string", "enum": list(TOOL_NAMES) + ["final_answer"]},
        "arguments": {"type": "object"},
        "answer": {"type": "string"},
    },
}

STEP_LIMIT_ANSWER = "I could not finish within the step limit."
TIME_LIMIT_ANSWER = "I could not finish within the time limit."


def render(question: str, transcript: List[Dict[str, Any]], today: str) -> str:
    """The prompt for the next step: catalogue, question, and every step so far with its result."""
    lines = [TOOL_CATALOGUE, "", f"Today's date: {today}", "", f"Question: {question}", ""]
    for i, s in enumerate(transcript, 1):
        lines.append(
            f"Step {i}: action={s['action']} arguments={json.dumps(s.get('arguments') or {}, ensure_ascii=False)}"
        )
        lines.append(f"Result {i}: {s['result_text']}")
    remaining = MAX_STEPS - len(transcript)
    lines.append("")
    lines.append(
        f"You have {remaining} step(s) left. Respond with ONE JSON object: "
        '{"thought": ..., "action": ..., "arguments": {...}} or {"action": "final_answer", "answer": ...}.'
        + (" This is your LAST step: give the final_answer now." if remaining == 1 else "")
    )
    return "\n".join(lines)


def _is_provider_failure(exc: BaseException) -> bool:
    name = type(exc).__name__
    return (
        name in ("GatewayUnreachable", "EmptyCompletionError", "CircuitBreakerOpenError")
        or "unreachable" in str(exc).lower()
    )


async def answer(
    question: str,
    toolbox: Toolbox,
    llm: Any,
    system_prompt: str,
    today: str,
    max_steps: int = MAX_STEPS,
    time_limit_s: float = TIME_LIMIT_S,
) -> Dict[str, Any]:
    """Answer one question. Returns the answer, the full trace, and the outcome fields."""
    t0 = time.monotonic()
    transcript: List[Dict[str, Any]] = []
    model_calls = 0
    error: Optional[str] = None
    provider_failure = False
    final: Optional[str] = None
    for _ in range(max_steps):
        left = time_limit_s - (time.monotonic() - t0)
        if left <= 0:
            final = TIME_LIMIT_ANSWER
            break
        prompt = render(question, transcript, today)
        model_calls += 1
        t_step = time.monotonic()
        try:
            step = await asyncio.wait_for(
                llm.generate_structured(
                    prompt,
                    STEP_SCHEMA,
                    schema_name="instructed_baseline_step",
                    system_message=system_prompt,
                    temperature=0.0,
                ),
                timeout=left,
            )
        except asyncio.TimeoutError:
            final = TIME_LIMIT_ANSWER
            break
        except Exception as exc:  # noqa: BLE001 - every failure is an outcome, recorded
            provider_failure = _is_provider_failure(exc)
            error = f"{type(exc).__name__}: {str(exc)[:300]}"
            break
        action = step.get("action")
        if action == "final_answer":
            final = (step.get("answer") or "").strip() or "(empty answer)"
            transcript.append(
                {
                    "action": action,
                    "seconds": round(time.monotonic() - t_step, 2),
                    "thought": (step.get("thought") or "")[:500],
                    "result_text": "",
                }
            )
            break
        args = step.get("arguments") or {}
        t_tool = time.monotonic()
        result = await toolbox.call(str(action), args)
        text = compact(result)
        transcript.append(
            {
                "action": action,
                "arguments": args,
                "thought": (step.get("thought") or "")[:500],
                "result": result,
                "result_text": text,
                "result_chars": len(text),
                "truncated": "[TRUNCATED" in text,
                "tool_seconds": round(time.monotonic() - t_tool, 2),
                "seconds": round(time.monotonic() - t_step, 2),
            }
        )
    else:
        final = STEP_LIMIT_ANSWER
    return {
        "answer": final if final is not None else "",
        "steps": [{k: v for k, v in s.items() if k != "result_text"} for s in transcript],
        "model_calls": model_calls,
        "seconds": round(time.monotonic() - t0, 2),
        "provider_failure": provider_failure,
        "error": error,
        "hit_step_limit": final == STEP_LIMIT_ANSWER,
        "hit_time_limit": final == TIME_LIMIT_ANSWER,
    }
