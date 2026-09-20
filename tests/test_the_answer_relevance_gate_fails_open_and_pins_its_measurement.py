# -*- coding: utf-8 -*-
"""The answer relevance gate (2D-16 wave 8): what it may replace, what it may never touch."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.services import answer_relevance_gate as g

pytestmark = pytest.mark.unit

Q = "What is the temperature in room 5.01 right now?"
A = (
    "The building has 234 rooms across six floors, and the library holds 12 study areas on "
    "level two with quiet seating for around 80 students."
)


class _Fake:
    """Stands in for llm_manager: returns a scripted object, raises, or hangs."""

    def __init__(self, result=None, exc=None, hang=False):
        self.result, self.exc, self.hang, self.calls = result, exc, hang, []

    async def generate(self, prompt, **kw):
        """The one-line reply the gate asks for; a dict result is rendered as 'LABEL | reason'."""
        self.calls.append((prompt, None, kw))
        if self.hang:
            await asyncio.sleep(30)
        if self.exc:
            raise self.exc
        if isinstance(self.result, dict):
            return f"{self.result.get('label', '')} | {self.result.get('reason', '')}"
        return self.result


@pytest.fixture
def fake(monkeypatch):
    def install(**kw):
        f = _Fake(**kw)
        monkeypatch.setattr(g, "_client", lambda: f)
        return f

    return install


def _run(question=Q, answer=A, lane="sensor_data", **kw):
    return asyncio.run(g.relevance_verdict(question, answer, lane, **kw))


# ── each label ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("label", ["OFF_TOPIC", "GARBLED", "ACTION_MISFIRE"])
def test_every_non_addressing_label_is_a_replacement(fake, label):
    fake(result={"label": label, "reason": "wrong quantity"})
    v = _run()
    assert v.judged and v.replace and v.label == label and v.reason == "wrong quantity"


def test_addresses_keeps_the_answer(fake):
    fake(result={"label": "ADDRESSES", "reason": "ok"})
    v = _run()
    assert v.judged and not v.replace


def test_a_contradictory_verdict_is_judged_and_logged_but_never_replaces_an_answer(fake):
    """Live 2026-09-20: a correct two-sensor TVOC answer was called 'conflicting average values' and
    replaced with a decline in the scripted demo. The label fired on 2 of 372 labelled answers, so
    dropping it from the replacing set costs nothing measurable."""
    fake(result={"label": "CONTRADICTORY", "reason": "two averages"})
    v = _run()
    assert v.judged and v.label == "CONTRADICTORY" and not v.replace
    assert "CONTRADICTORY" not in g.REPLACING_LABELS


def test_the_call_uses_plain_generation_with_the_measured_prompt(fake):
    """Plain `generate`, not `generate_structured`: the schema path returned an EMPTY completion on
    every call with the local reasoning model, so the first build failed open on all 32 answers of a
    live run. The fake has no generate_structured, so calling it would raise and fail this test."""
    f = fake(result={"label": "ADDRESSES", "reason": ""})
    _run()
    prompt, _none, kw = f.calls[0]
    assert kw["temperature"] == 0
    assert kw["system_message"] == g.SYSTEM and "ADDRESSES" in g.SYSTEM
    assert "ONE line" in g.SYSTEM
    assert prompt.startswith("QUESTION: ") and "\n\nANSWER: " in prompt


def test_the_question_label_never_stands_alone_on_a_line(fake):
    """`QUESTION:` alone on a line is what the client's empty-slot check warns about."""
    f = fake(result={"label": "ADDRESSES", "reason": ""})
    _run(question="line one\nline two")
    assert "QUESTION:\n" not in f.calls[0][0]
    assert f.calls[0][0].startswith("QUESTION: line one line two")


def test_inputs_are_truncated_as_the_experiment_did(fake):
    f = fake(result={"label": "ADDRESSES", "reason": ""})
    _run(question="q" * 5000, answer="word " * 3000)
    prompt = f.calls[0][0]
    q, a = prompt.split("\n\nANSWER: ")
    assert len(q) - len("QUESTION: ") <= g.MAX_QUESTION_CHARS and len(a) <= g.MAX_ANSWER_CHARS


@pytest.mark.parametrize(
    "raw, label",
    [
        ("OFF_TOPIC | shows lighting data, not noise", "OFF_TOPIC"),
        ("OFF_TOPIC: different quantity", "OFF_TOPIC"),
        ("**OFF_TOPIC** - lists tariffs", "OFF_TOPIC"),
        ("off_topic | lower case", "OFF_TOPIC"),
        ("ADDRESSES", "ADDRESSES"),
        ('{"label": "GARBLED", "reason": "fragment"}', "GARBLED"),
        ("\n\nCONTRADICTORY | two totals", "CONTRADICTORY"),
    ],
)
def test_the_one_line_reply_is_parsed_in_the_forms_a_model_writes_it(raw, label):
    assert g.parse_verdict(raw)[0] == label


@pytest.mark.parametrize("raw", ["", None, "I think this answer is fine", "MAYBE | unsure", "[]"])
def test_a_reply_with_no_label_is_not_a_verdict(raw):
    assert g.parse_verdict(raw)[0] not in g.LABELS


def test_the_module_never_talks_to_a_provider_directly():
    src = inspect.getsource(g)
    for banned in ("requests.post", "11434", "httpx", "ollama."):
        assert banned not in src.replace("`", "")


# ── fail open ────────────────────────────────────────────────────────────────


def test_a_timeout_leaves_the_answer_standing(fake):
    fake(hang=True)
    v = _run(timeout_s=0.05)
    assert not v.judged and not v.replace and "timed out" in v.skipped


def test_a_provider_error_leaves_the_answer_standing(fake):
    fake(exc=RuntimeError("provider down"))
    v = _run()
    assert not v.judged and not v.replace and v.skipped.startswith("error")


@pytest.mark.parametrize(
    "garbage", [None, [], {}, {"label": "MAYBE"}, {"reason": "x"}, "no label here"]
)
def test_an_unparsed_or_unknown_verdict_leaves_the_answer_standing(fake, garbage):
    fake(result=garbage)
    v = _run()
    assert not v.judged and not v.replace


def test_a_lower_case_label_is_read(fake):
    fake(result={"label": "off_topic", "reason": "x"})
    assert _run().replace


# ── skip rules ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "answer",
    [
        "I did not find any occupancy record in the records I searched for that room today.",
        "I could not find a maintenance schedule for the lift in the building's records at all.",
        "I couldn't answer that from Abacws Building's records this time, but here is what I hold.",
        "**Abacws Building's documents do not answer this.** I searched Department Directory and "
        "Stakeholder Group Register; none of them contains the answer.",
        "Which room do you mean, and for which day would you like the reading given to you now?",
        "I've filed your report about the leaking tap on floor 3 and the team will be told soon.",
        "Room 5.01 is 21 degrees.",
    ],
)
def test_answers_that_need_no_judging_cost_no_call(fake, answer):
    f = fake(result={"label": "OFF_TOPIC", "reason": "x"})
    v = _run(answer=answer)
    assert not v.judged and not v.replace and v.skipped and not f.calls


def test_the_footer_does_not_count_towards_the_length():
    assert g.skip_reason("Room 5.01 is 21.\n\n---\n*Sources: a b c d e f g h i j k l m n*", "x")


# ── lanes ────────────────────────────────────────────────────────────────────

WRITES = (
    "maintenance",
    "complaint",
    "safety_report",
    "suggestion",
    "preference_management",
    "alert",
    "control",
    "lab_booking",
)


@pytest.mark.parametrize("lane", WRITES)
def test_a_lane_that_writes_state_or_a_file_is_never_judged(fake, lane):
    f = fake(result={"label": "OFF_TOPIC", "reason": "x"})
    assert not _run(lane=lane).judged and not f.calls
    assert not g.judges_lane(lane) and not g.judges_lane(lane, lane)
    assert lane not in g.lanes(",".join(WRITES) + ",sensor_data")


def test_only_the_configured_lanes_are_judged():
    assert g.judges_lane("sensor_data") and g.judges_lane("events")
    assert not g.judges_lane("metadata") and not g.judges_lane("capability")
    assert not g.judges_lane("sensor_data", "events") and g.judges_lane("events", "events, trend")
    assert not g.judges_lane(None) and not g.judges_lane("")


def test_the_setting_defaults_match_the_module():
    from shared.config import Settings

    fields = Settings.model_fields
    assert fields["ANSWER_RELEVANCE_GATE"].default is True
    assert fields["ANSWER_RELEVANCE_GATE_LANES"].default == g.DEFAULT_LANES
    assert fields["ANSWER_RELEVANCE_TIMEOUT_S"].default == 8.0
    for name in (
        "ANSWER_RELEVANCE_GATE",
        "ANSWER_RELEVANCE_GATE_LANES",
        "ANSWER_RELEVANCE_TIMEOUT_S",
    ):
        assert name in (Path(__file__).resolve().parents[1] / ".env.example").read_text("utf-8")


# ── the response node ────────────────────────────────────────────────────────


def _node(monkeypatch, lane="sensor_data", enabled=True, lanes=None, result=None, exc=None):
    from orchestrator.workflow import _orchestrator as mod

    monkeypatch.setattr(g, "_client", lambda: _Fake(result=result, exc=exc))
    monkeypatch.setattr(mod.settings, "ANSWER_RELEVANCE_GATE", enabled, raising=False)
    monkeypatch.setattr(
        mod.settings, "ANSWER_RELEVANCE_GATE_LANES", lanes or g.DEFAULT_LANES, raising=False
    )

    async def _decline(state, ctx):
        return "DECLINE"

    monkeypatch.setattr(mod, "_unanswered_response", _decline)
    state = SimpleNamespace(current_intent=lane, user_message=Q, intermediate_results={})
    return mod, state


def test_a_non_responsive_answer_is_replaced_and_recorded(monkeypatch):
    mod, state = _node(monkeypatch, result={"label": "OFF_TOPIC", "reason": "other quantity"})
    out = asyncio.run(mod._relevance_gated(state, None, A))
    assert out == "DECLINE"
    assert state.intermediate_results["relevance_gate"] == {
        "label": "OFF_TOPIC",
        "reason": "other quantity",
        "replaced": True,
        "lane": "sensor_data",
    }


def test_a_responsive_answer_stands_and_is_still_recorded(monkeypatch):
    mod, state = _node(monkeypatch, result={"label": "ADDRESSES", "reason": "ok"})
    assert asyncio.run(mod._relevance_gated(state, None, A)) == A
    assert state.intermediate_results["relevance_gate"]["replaced"] is False


def test_the_node_fails_open_and_honours_both_switches(monkeypatch):
    mod, state = _node(monkeypatch, exc=RuntimeError("down"))
    assert asyncio.run(mod._relevance_gated(state, None, A)) == A
    mod, state = _node(monkeypatch, enabled=False, result={"label": "OFF_TOPIC", "reason": "x"})
    assert asyncio.run(mod._relevance_gated(state, None, A)) == A
    mod, state = _node(monkeypatch, lane="metadata", result={"label": "OFF_TOPIC", "reason": "x"})
    assert asyncio.run(mod._relevance_gated(state, None, A)) == A
    mod, state = _node(
        monkeypatch,
        lane="maintenance",
        lanes="maintenance,sensor_data",
        result={"label": "OFF_TOPIC", "reason": "x"},
    )
    assert asyncio.run(mod._relevance_gated(state, None, A)) == A


def test_the_gate_sits_after_the_shape_guard_and_before_the_meta_guard_and_before_emission():
    from orchestrator.workflow import _orchestrator as mod

    src = inspect.getsource(mod.WorkflowOrchestrator._response_node)
    assert (
        src.index("answer-shape check skipped")
        < src.index("_relevance_gated(state, ctx, final_response)")
        < src.index("meta-answer check skipped")
    )
    # Both endpoints emit the FINAL STATE's message, which this node sets: nothing is streamed early.
    main_src = (Path(__file__).resolve().parents[1] / "orchestrator" / "main.py").read_text("utf-8")
    assert "assistant_message = (\n                    final_state.messages[-1].content" in main_src


# ── the measurement, pinned ──────────────────────────────────────────────────

RECORDED = Path(__file__).resolve().parents[1] / "docs" / "phase0" / "answer_judge_experiment.jsonl"


@pytest.mark.skipif(not RECORDED.exists(), reason="the recorded experiment is not in this checkout")
def test_the_default_lanes_replace_almost_no_good_answer_and_catch_the_weird_ones():
    """Recomputed from the RECORDED verdicts with the gate's own lane and skip rules.

    A prompt, lane-list or skip-rule edit that changes this fails here; the numbers are a
    measurement taken on the same answers the lane list was chosen from, and must be confirmed
    on a fresh set.
    """
    rows = [json.loads(x) for x in RECORDED.read_text("utf-8").splitlines() if x.strip()]
    assert len(rows) == 372
    weird = good = 0
    for r in rows:
        if not g.judges_lane(r["lane"]) or g.skip_reason(r["answer"], r["lane"]):
            continue
        if r["judge"]["label"] == g.ADDRESSES:
            continue
        if r["verdict"] == "WEIRD":
            weird += 1
        elif r["verdict"] == "GOOD_ANSWER":
            good += 1
    assert good <= 2, f"{good} GOOD answers would be replaced"
    assert weird >= 45, f"only {weird} WEIRD answers would be caught"


@pytest.mark.skipif(not RECORDED.exists(), reason="the recorded experiment is not in this checkout")
def test_the_lanes_the_measurement_found_noisy_are_not_in_the_default():
    for lane in ("metadata", "capability"):
        assert not g.judges_lane(lane)
