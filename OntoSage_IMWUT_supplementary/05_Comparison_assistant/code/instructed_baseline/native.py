"""Native tool-calling loop for the instructed assistant on an OpenAI-compatible provider (default).

WHY NOT ``llm_manager``: measured 2026-10-10, ``gpt-oss:20b`` on the hosted gateway answers a prompt
that lists tools with a NATIVE tool call (finish_reason=tool_calls, empty text content), whatever
response_format asks for. ``llm_manager`` reads only the text content and has no tool-calling path,
so the JSON-step loop (loop.py) failed with empty completions on 2 of 2 smoke runs. A model trained to
call tools is a fairer baseline when it is allowed to, so this loop sends the provider's own
``tools`` parameter to the SAME endpoint, model, temperature (0, as OntoSage's structured calls) and
token budget (``HOSTED_LLM_MAX_TOKENS`` floor, doubled once when reasoning exhausts it, exactly as
``llm_manager._call_with_deadline`` does) and the same reasoning effort. Deviation from spec R1,
recorded in the parity report and the pre-registration addendum.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

import httpx

from .loop import STEP_LIMIT_ANSWER, TIME_LIMIT_ANSWER
from .tools import Toolbox, compact

MAX_STEPS = 8
TIME_LIMIT_S = 300

_STR = {"type": "string"}
TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "resolve_terms",
            "description": "Building concepts and sensor classes that lay words map to.",
            "parameters": {"type": "object", "properties": {"text": _STR}, "required": ["text"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_spaces",
            "description": "Rooms, zones and floors whose name or id contains the text, with the facts the building "
            "model records about each (type, floor, capacity and other properties).",
            "parameters": {
                "type": "object",
                "properties": {"name_or_kind": _STR},
                "required": ["name_or_kind"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_points",
            "description": "Sensor points measuring a quantity in a place, with timeseries ids (uuid) and stores "
            "(stored_at); lists the other points in the place when none match.",
            "parameters": {
                "type": "object",
                "properties": {"place": _STR, "quantity": _STR},
                "required": ["place", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_readings",
            "description": "Readings between start and end (building LOCAL time, YYYY-MM-DDTHH:MM): per point n, first/last "
            "time, min/mean/max, largest gap, and how many of the points asked had data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "points": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"uuid": _STR, "stored_at": _STR},
                            "required": ["uuid", "stored_at"],
                        },
                    },
                    "start": _STR,
                    "end": _STR,
                },
                "required": ["points", "start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_records",
            "description": "Rows of a building register (bookings, maintenance, schedules, inspections, ...), optionally "
            "filtered by text; with no match, the list of registers the building holds.",
            "parameters": {
                "type": "object",
                "properties": {"register": _STR, "contains": _STR},
                "required": ["register"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Passages from the building's uploaded documents, with document names.",
            "parameters": {"type": "object", "properties": {"query": _STR}, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_amenities_or_topics",
            "description": "Facilities and knowledge topics the building describes.",
            "parameters": {"type": "object", "properties": {"text": _STR}, "required": ["text"]},
        },
    },
]


class Provider:
    """The OpenAI-compatible endpoint and settings OntoSage itself uses (inside its container)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        max_tokens: int,
        timeout_s: float,
        reasoning_effort: str = "",
        temperature: float = 0.0,
    ) -> None:
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model
        self.max_tokens, self.timeout_s, self.reasoning_effort, self.temperature = (
            max_tokens,
            timeout_s,
            reasoning_effort,
            temperature,
        )

    @classmethod
    def from_settings(cls) -> "Provider":
        from orchestrator.llm_manager import llm_manager
        from shared.config import settings

        return cls(
            settings.HOSTED_LLM_BASE_URL,
            settings.HOSTED_LLM_API_KEY,
            settings.HOSTED_LLM_MODEL,
            int(settings.HOSTED_LLM_MAX_TOKENS),
            float(settings.HOSTED_LLM_TIMEOUT_S),
            str(llm_manager.config.get("reasoning_effort") or ""),
        )

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        force_answer: bool = False,
    ) -> Dict[str, Any]:
        budget = self.max_tokens
        for attempt in (1, 2):
            body: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": budget,
            }
            if tools:
                body["tools"] = tools
                body["tool_choice"] = "none" if force_answer else "auto"
            if self.reasoning_effort:
                body["reasoning_effort"] = self.reasoning_effort
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                r = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
            r.raise_for_status()
            choice = (r.json().get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            if (
                choice.get("finish_reason") == "length"
                and not msg.get("content")
                and not msg.get("tool_calls")
                and attempt == 1
            ):
                budget *= 2  # reasoning spent the budget: retry once at double, as llm_manager does
                continue
            return {"message": msg, "finish_reason": choice.get("finish_reason")}
        return {"message": {}, "finish_reason": "length"}


async def answer(
    question: str,
    toolbox: Toolbox,
    provider: Provider,
    system_prompt: str,
    today: str,
    max_steps: int = MAX_STEPS,
    time_limit_s: float = TIME_LIMIT_S,
) -> Dict[str, Any]:
    """Answer one question with native tool calls. Same outcome fields as loop.answer."""
    t0 = time.monotonic()
    messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": system_prompt.replace(
                "Respond with one JSON object per step, as specified.",
                "Use the tools to look things up, then answer in plain text.",
            ),
        },
        {"role": "user", "content": f"Today's date: {today}\n\n{question}"},
    ]
    steps: List[Dict[str, Any]] = []
    model_calls = 0
    final: Optional[str] = None
    error: Optional[str] = None
    provider_failure = False
    while True:
        if time.monotonic() - t0 > time_limit_s:
            final = TIME_LIMIT_ANSWER
            break
        force = len(steps) >= max_steps
        model_calls += 1
        try:
            resp = await provider.chat(messages, TOOL_SPECS, force_answer=force)
        except (httpx.HTTPError, ValueError) as exc:
            provider_failure = True
            error = f"{type(exc).__name__}: {str(exc)[:300]}"
            break
        msg = resp["message"]
        calls = msg.get("tool_calls") or []
        if not calls or force:
            final = (msg.get("content") or "").strip()
            if not final:
                provider_failure = resp["finish_reason"] in ("length", None)
                final = "" if provider_failure else "(empty answer)"
                error = f"empty final content (finish_reason={resp['finish_reason']})"
            if force and calls:
                final = final or STEP_LIMIT_ANSWER
            break
        messages.append(
            {"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls}
        )
        for call in calls:
            fn = call.get("function") or {}
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            t_tool = time.monotonic()
            result = (
                await toolbox.call(name, args)
                if len(steps) < max_steps
                else {"error": "step limit reached"}
            )
            text = compact(result)
            steps.append(
                {
                    "action": name,
                    "arguments": args,
                    "result": result,
                    "result_chars": len(text),
                    "truncated": "[TRUNCATED" in text,
                    "tool_seconds": round(time.monotonic() - t_tool, 2),
                }
            )
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": text})
    return {
        "answer": final if final is not None else "",
        "steps": steps,
        "model_calls": model_calls,
        "seconds": round(time.monotonic() - t0, 2),
        "provider_failure": provider_failure,
        "error": error,
        "hit_step_limit": len(steps) >= max_steps,
        "hit_time_limit": final == TIME_LIMIT_ANSWER,
        "mode": "native_tools",
    }
