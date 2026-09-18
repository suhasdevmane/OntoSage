# -*- coding: utf-8 -*-
"""The model fills a schema; code does not repair free text (ARCH-A1).

WHAT THIS IS FOR
----------------
Every lane that wants JSON from the model asks in prose, slices the first ``{``..``}``
out of the answer and repairs what it finds. BUG-631 is the worst thing that shape
produces: every floor-scoped SPARQL query was rejected as malformed, a fallback answered
about a DIFFERENT floor with a plausible number, and three verification layers saw
nothing. A repair is invisible; a typed failure is not.

WHAT IS ACTUALLY PROVED HERE, AND WHAT IS NOT
---------------------------------------------
These tests run entirely offline against FABRICATED provider responses — there are no
recorded compiles or classifications in this repository to replay, which is itself worth
saying. So they prove the control flow: a valid response is returned unchanged, a
malformed one is retried EXACTLY once with the validation error attached, and a second
failure raises rather than repairs.

They do NOT prove that the local model obeys the schema. Only a live run can, and that
run is owed: 40 questions x3 with the flag on, zero parse failures, identical
`plan_fingerprint` — and it must run with the compile cache OFF, or it measures the cache
(CAVEAT-327, and BUG-662 one lane over).
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
import json
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

llm_mod = importlib.import_module("orchestrator.llm_manager")
compiler = importlib.import_module("orchestrator.services.deliberation.compiler")

pytestmark = pytest.mark.unit


# ── a manager whose provider is a list of canned answers ─────────────────────


class FakeManager(llm_mod.LLMManager):
    """An LLMManager with no client at all.

    ``__init__`` is overridden rather than patched: the real one builds a langchain
    client, and a test that needs a client to prove a control flow is a test that will
    one day need a server.
    """

    def __init__(self, responses: List[Any], provider: str = "ollama") -> None:
        self.provider = provider
        self.config = {}
        self.client = None
        self.client_fast = None
        self.calls: List[Dict[str, Any]] = []
        self._responses = list(responses)

    async def generate(  # type: ignore[override]
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: Optional[float] = None,
        task_type: Optional[Any] = None,
        provider_kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        self.calls.append({"prompt": prompt, "provider_kwargs": provider_kwargs})
        nxt = self._responses.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["select_one", "rank_all"]},
        "count": {"type": ["number", "null"]},
    },
    "required": ["decision"],
}


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean_metrics():
    llm_mod.reset_structured_metrics()
    yield
    llm_mod.reset_structured_metrics()


# ── the happy path is unchanged ──────────────────────────────────────────────


def test_a_valid_response_is_returned_unchanged_and_not_retried():
    mgr = FakeManager(['{"decision": "rank_all", "count": 3}'])
    out = _run(mgr.generate_structured("q", SCHEMA, schema_name="s"))
    assert out == {"decision": "rank_all", "count": 3}
    assert len(mgr.calls) == 1, "a valid response must not cost a second generation"
    stats = llm_mod.structured_metrics()["s"]
    assert (stats["calls"], stats["valid_first_try"], stats["retried"], stats["failed"]) == (
        1,
        1,
        0,
        0,
    )


def test_nothing_is_coerced_or_filled_in():
    """The object that comes back is the object the model sent, not a normalised copy."""
    payload = {"decision": "select_one", "count": None, "extra": ["kept"]}
    mgr = FakeManager([json.dumps(payload)])
    assert _run(mgr.generate_structured("q", SCHEMA, schema_name="s")) == payload


# ── one retry, then a TYPED failure ──────────────────────────────────────────


def test_a_malformed_response_is_retried_once_then_fails_typed():
    mgr = FakeManager(["I'm afraid I can't do that.", "still not JSON"])
    with pytest.raises(llm_mod.StructuredGenerationError) as excinfo:
        _run(mgr.generate_structured("q", SCHEMA, schema_name="s"))
    err = excinfo.value
    assert err.stage == "decode"
    assert err.schema_name == "s"
    assert err.attempts == 2
    assert len(mgr.calls) == 2, "exactly one retry — not zero, not a repair loop"
    stats = llm_mod.structured_metrics()["s"]
    assert (stats["valid_first_try"], stats["retried"], stats["failed"]) == (0, 1, 1)


def test_a_schema_violation_is_retried_once_then_fails_typed():
    bad = '{"decision": "teleport"}'
    mgr = FakeManager([bad, bad])
    with pytest.raises(llm_mod.StructuredGenerationError) as excinfo:
        _run(mgr.generate_structured("q", SCHEMA, schema_name="s"))
    assert excinfo.value.stage == "schema"
    assert "decision" in excinfo.value.detail


def test_the_retry_carries_the_validation_error_back_to_the_model():
    """A retry that repeats the same prompt is a retry that asks for the same mistake."""
    mgr = FakeManager(['{"decision": "teleport"}', '{"decision": "rank_all"}'])
    out = _run(mgr.generate_structured("ORIGINAL PROMPT", SCHEMA, schema_name="s"))
    assert out == {"decision": "rank_all"}
    first, second = mgr.calls
    assert first["prompt"] == "ORIGINAL PROMPT"
    assert second["prompt"].startswith("ORIGINAL PROMPT")
    assert "rejected" in second["prompt"]
    assert "decision" in second["prompt"], "the retry must name the field that was wrong"
    stats = llm_mod.structured_metrics()["s"]
    assert (stats["valid_first_try"], stats["retried"], stats["failed"]) == (0, 1, 0)


def test_a_provider_outage_is_a_different_stage_from_a_schema_failure():
    """An outage is an availability fact. Counting it as a schema failure would make the
    honesty metric move whenever the GPU was busy."""
    mgr = FakeManager([TimeoutError("provider timed out")])
    with pytest.raises(llm_mod.StructuredGenerationError) as excinfo:
        _run(mgr.generate_structured("q", SCHEMA, schema_name="s"))
    assert excinfo.value.stage == "provider"
    assert len(mgr.calls) == 1, "generate() already retried; this layer must not retry again"


def test_prose_around_the_json_is_counted_not_absorbed():
    """Stripping an envelope is still tolerated, but it is REPORTED — a provider that is
    really honouring the schema never needs it, so this count is the tell."""
    mgr = FakeManager(['Here you go:\n{"decision": "rank_all"}\nHope that helps!'])
    assert _run(mgr.generate_structured("q", SCHEMA, schema_name="s"))["decision"] == "rank_all"
    assert llm_mod.structured_metrics()["s"]["stripped_envelope"] == 1


# ── what each installed client is actually handed ────────────────────────────


def test_the_local_client_is_handed_the_schema_as_format():
    """`ollama` 0.6.1 types generate(format=) as Literal['','json'] | JsonSchemaValue, and
    OllamaLLM._generate_params does kwargs.pop("format", self.format) — so a PER-CALL
    kwarg reaches it even though langchain-ollama 0.2.3 still types its own field as
    Literal['','json']."""
    mgr = FakeManager(['{"decision": "rank_all"}'], provider="ollama")
    _run(mgr.generate_structured("q", SCHEMA, schema_name="s"))
    assert mgr.calls[0]["provider_kwargs"] == {"format": SCHEMA}


@pytest.mark.parametrize("provider", ["openai", "ollama_cloud"])
def test_the_openai_compatible_client_is_handed_a_json_schema_response_format(provider):
    mgr = FakeManager(['{"decision": "rank_all"}'], provider=provider)
    _run(mgr.generate_structured("q", SCHEMA, schema_name="cqir_compile"))
    sent = mgr.calls[0]["provider_kwargs"]["response_format"]
    assert sent["type"] == "json_schema"
    assert sent["json_schema"]["name"] == "cqir_compile"
    assert sent["json_schema"]["schema"] is SCHEMA
    assert sent["json_schema"]["strict"] is False, (
        "strict demands a closed schema; ours are permissive so the flag can only ADD "
        "guarantees, never reject what the current path accepts"
    )


def test_an_ordinary_generate_call_is_unchanged():
    """The plumbing must be invisible when nobody uses it: every existing caller passes
    no provider_kwargs and must reach the client exactly as before."""
    sig = inspect.signature(llm_mod.LLMManager.generate)
    assert sig.parameters["provider_kwargs"].default is None
    src = inspect.getsource(llm_mod.LLMManager._generate_once)
    assert "extra = dict(provider_kwargs or {})" in src


# ── the flag ─────────────────────────────────────────────────────────────────


def test_the_flag_exists_and_is_off_by_default():
    from shared.config import Settings

    field = Settings.model_fields["STRUCTURED_PLAN_ENABLED"]
    assert field.default is False, "a demo-day flag defaults OFF"


def test_the_flag_is_documented_in_the_example_exactly_once():
    text = Path(".env.example").read_text(encoding="utf-8")
    assert text.count("STRUCTURED_PLAN_ENABLED=") == 1


# ── the CQ-IR compile call site ──────────────────────────────────────────────


def _set_flag(monkeypatch, value: bool):
    """Set the flag on EVERY settings object the code under test might be holding.

    `tests/test_strict_secrets.py` calls `importlib.reload(shared.config)`, which builds a NEW
    settings instance. Modules that did `from shared.config import settings` keep the OLD one,
    so patching only the freshly imported object left the flag unset in
    `dialogue_agent`/`compiler` and the free-text path ran with the flag nominally ON — a
    failure that appears only in a full-suite run, and only after that reload.
    """
    import importlib

    from shared.config import settings

    targets = [settings]
    for name in ("orchestrator.agents.dialogue_agent", "orchestrator.services.deliberation.compiler"):
        module = importlib.import_module(name)
        held = getattr(module, "settings", None)
        if held is not None and all(held is not t for t in targets):
            targets.append(held)
    for target in targets:
        monkeypatch.setattr(target, "STRUCTURED_PLAN_ENABLED", value, raising=False)


def test_with_the_flag_off_the_compiler_uses_the_free_text_call(monkeypatch):
    _set_flag(monkeypatch, False)
    seen = {}

    class Mgr:
        async def generate(self, prompt, temperature=None, **kw):
            seen["free_text"] = True
            return '{"decision": "rank_all"}'

        async def generate_structured(self, *a, **k):  # pragma: no cover - must not run
            raise AssertionError("structured path ran with the flag OFF")

    monkeypatch.setattr(llm_mod, "llm_manager", Mgr(), raising=False)
    call = compiler._default_llm_call()
    assert _run(call("p")) == '{"decision": "rank_all"}'
    assert seen == {"free_text": True}


def test_with_the_flag_on_the_compiler_asks_for_the_schema_and_returns_text(monkeypatch):
    _set_flag(monkeypatch, True)
    seen = {}

    class Mgr:
        async def generate(self, *a, **k):  # pragma: no cover - must not run
            raise AssertionError("free-text path ran with the flag ON")

        async def generate_structured(self, prompt, schema, *, schema_name, **kw):
            seen["schema"] = schema
            seen["name"] = schema_name
            return {"decision": "rank_all", "constraints": []}

    monkeypatch.setattr(llm_mod, "llm_manager", Mgr(), raising=False)
    call = compiler._default_llm_call()
    out = _run(call("p"))
    assert json.loads(out) == {"decision": "rank_all", "constraints": []}
    assert seen["name"] == compiler.CQIR_SCHEMA_NAME
    assert seen["schema"]["properties"]["decision"]["enum"]


def test_the_two_paths_produce_the_same_plan_from_the_same_payload():
    """The flag changes WHERE the shape is enforced, not what the plan is."""
    payload = {
        "decision": "rank_all",
        "constraints": [
            {"phrase": "stuffy", "modality": "co2", "direction": "minimize", "hardness": "soft"}
        ],
        "spatial": [{"relation": "on_floor", "anchor": "3", "phrase": "on floor 3"}],
        "time": {"basis": "now"},
        "unmapped": [],
    }
    known = {"co2", "temperature"}
    free_text = compiler._parse_compiled("Sure, here it is:\n" + json.dumps(payload), "q", known)
    structured = compiler._parse_compiled(json.dumps(payload), "q", known)
    assert free_text.decision == structured.decision
    assert [c.modality for c in free_text.constraints] == [
        c.modality for c in structured.constraints
    ]
    assert [s.anchor for s in free_text.spatial] == [s.anchor for s in structured.spatial]
    assert free_text.signals == structured.signals


def test_the_compile_cache_key_is_untouched_when_the_flag_is_off(monkeypatch):
    from orchestrator.services.deliberation.coverage_audit import ModalitySpec

    mods = [ModalitySpec("co2", ["CO2_Level_Sensor"])]
    _set_flag(monkeypatch, False)
    off = compiler._compile_cache_key("how stuffy is it", mods)
    _set_flag(monkeypatch, True)
    on = compiler._compile_cache_key("how stuffy is it", mods)
    assert off != on, (
        "a structured compile and a free-text one are different compilers; sharing a cache "
        "entry would let the acceptance run replay the old path's plans"
    )


# ── the schemas are derived from the PARSERS, not from the prompt prose ──────


def _keys_read_via(source: str, receiver: str) -> set:
    """Every literal key read as ``<receiver>.get("k")`` in a function's source."""
    keys = set()
    for node in ast.walk(ast.parse(textwrap.dedent(source))):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == receiver
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
    return keys


def test_the_cqir_schema_covers_every_field_the_parser_reads():
    source = inspect.getsource(compiler._parse_compiled)
    read = _keys_read_via(source, "data")
    schema = compiler._cqir_schema()
    missing = sorted(read - set(schema["properties"]))
    assert not missing, (
        f"_parse_compiled reads {missing} and the schema does not declare them — a schema "
        f"that omits a consumed field tells the model that field does not matter"
    )


def test_the_cqir_schema_enums_come_from_the_ir_not_from_the_prompt():
    schema = compiler._cqir_schema()
    props = schema["properties"]
    assert set(props["decision"]["enum"]) == compiler._DECISIONS
    assert (
        set(props["constraints"]["items"]["properties"]["direction"]["enum"])
        == compiler._DIRECTIONS
    )
    assert set(props["spatial"]["items"]["properties"]["relation"]["enum"]) == compiler._RELATIONS
    assert set(props["time"]["properties"]["basis"]["enum"]) == compiler._BASES


def test_the_cqir_schema_leaves_building_specific_vocabulary_open():
    """`modality` and `anchor` are the ACTIVE BUILDING's vocabulary. An enum here would be
    a building literal in shared code, and would take away the model's `unmapped` escape."""
    props = compiler._cqir_schema()["properties"]
    assert "enum" not in props["constraints"]["items"]["properties"]["modality"]
    assert "enum" not in props["spatial"]["items"]["properties"]["anchor"]


def test_a_schema_valid_payload_is_one_the_parser_accepts():
    """The two halves must agree: anything the schema permits must compile without
    becoming an ambiguity signal about its own vocabulary."""
    from jsonschema import Draft202012Validator

    schema = compiler._cqir_schema()
    for direction in sorted(compiler._DIRECTIONS):
        payload = {
            "decision": "list_matching",
            "constraints": [
                {"modality": "co2", "direction": direction, "hardness": "soft", "threshold": 800}
            ],
            "time": {"basis": "now"},
        }
        Draft202012Validator(schema).validate(payload)
        cqir = compiler._parse_compiled(json.dumps(payload), "q", {"co2"})
        assert [s for s in cqir.signals if s.kind == "vague"] == [], direction


# ── the dialogue classification call site ────────────────────────────────────


def test_the_intent_schema_covers_every_field_the_parser_reads():
    dialogue = importlib.import_module("orchestrator.agents.dialogue_agent")
    source = inspect.getsource(dialogue.DialogueAgent._parse_llm_response)
    read = _keys_read_via(source, "result")
    schema = dialogue.DialogueAgent._intent_schema(None)
    missing = sorted(read - set(schema["properties"]))
    assert not missing, f"_parse_llm_response reads {missing}; the schema declares neither"


def test_the_intent_enum_is_the_buildings_own_registry_not_a_literal():
    dialogue = importlib.import_module("orchestrator.agents.dialogue_agent")
    from orchestrator.intents.registry import get_intent_registry

    schema = dialogue.DialogueAgent._intent_schema(None)
    enum = schema["properties"]["intent"].get("enum")
    assert enum, "the intent field should enumerate the registry when it can be read"
    assert set(enum) == set(get_intent_registry(None).names())
    src = inspect.getsource(dialogue.DialogueAgent._intent_schema)
    assert "get_intent_registry" in src and '"sensor_data"' not in src


def test_only_intent_is_required_so_the_flag_can_only_add_guarantees():
    dialogue = importlib.import_module("orchestrator.agents.dialogue_agent")
    schema = dialogue.DialogueAgent._intent_schema(None)
    assert schema["required"] == ["intent"]
    assert "additionalProperties" not in schema


def test_with_the_flag_off_the_classifier_call_is_the_old_one(monkeypatch):
    dialogue = importlib.import_module("orchestrator.agents.dialogue_agent")
    _set_flag(monkeypatch, False)
    seen = {}

    class Mgr:
        async def generate(self, prompt, task_type=None, **kw):
            seen["task_type"] = task_type
            return '{"intent": "sensor_data"}'

        async def generate_structured(self, *a, **k):  # pragma: no cover
            raise AssertionError("structured path ran with the flag OFF")

    monkeypatch.setattr(dialogue, "llm_manager", Mgr(), raising=False)
    agent = dialogue.DialogueAgent()
    out = _run(agent._classify_llm_call("p", building_id=None))
    assert out == '{"intent": "sensor_data"}'
    assert seen["task_type"] is dialogue.TaskType.INTENT


def test_with_the_flag_on_the_classifier_returns_the_validated_object_as_text(monkeypatch):
    dialogue = importlib.import_module("orchestrator.agents.dialogue_agent")
    _set_flag(monkeypatch, True)
    seen = {}

    class Mgr:
        async def generate(self, *a, **k):  # pragma: no cover
            raise AssertionError("free-text path ran with the flag ON")

        async def generate_structured(self, prompt, schema, *, schema_name, task_type=None):
            seen["name"] = schema_name
            seen["task_type"] = task_type
            return {"intent": "sensor_data", "entities": ["5.01"]}

    monkeypatch.setattr(dialogue, "llm_manager", Mgr(), raising=False)
    agent = dialogue.DialogueAgent()
    out = _run(agent._classify_llm_call("p", building_id=None))
    assert json.loads(out) == {"intent": "sensor_data", "entities": ["5.01"]}
    assert seen["name"] == dialogue.DialogueAgent.INTENT_SCHEMA_NAME
    assert seen["task_type"] is dialogue.TaskType.INTENT


def test_a_structured_failure_reaches_the_classification_failed_fallback():
    """The typed error must land in `detect_intent`'s handler, which does NOT cache and
    still runs the routing contract — a malformed generation costs the turn its
    classifier, not its honesty."""
    dialogue = importlib.import_module("orchestrator.agents.dialogue_agent")
    source = inspect.getsource(dialogue.DialogueAgent.detect_intent)
    assert "_classify_llm_call" in source
    assert "except Exception as e:" in source
    assert '"classification_failed": True' in source
