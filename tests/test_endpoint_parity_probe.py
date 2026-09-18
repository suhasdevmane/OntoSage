# -*- coding: utf-8 -*-
"""Offline tests for the endpoint-parity harness.

These test the HARNESS's logic, never the server: divergence classification, the
co-reference verdict the BUG-524 hunt turns on, marker evaluation, the multi-turn message
array, and the rule that keeps building literals out of the conversations. Every one runs
with nothing listening on port 8000.

A harness whose comparison logic is only ever exercised against a live stack is a harness
whose findings cannot be trusted — this project's own history is that the measuring
apparatus was wrong more often than the system was (lessons.md #20-22).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

pytestmark = pytest.mark.unit


def _load_harness():
    spec = importlib.util.spec_from_file_location(
        "_endpoint_parity_probe", REPO / "scripts" / "endpoint_parity_probe.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_endpoint_parity_probe"] = mod
    spec.loader.exec_module(mod)
    return mod


H = _load_harness()


def _matches(answer: str, marker: str) -> bool:
    """The regression probe's marker semantics, imported rather than re-implemented.

    Loaded lazily inside the helper so a change to the probe is picked up here, and so a
    broken probe fails these tests loudly instead of silently swapping in a weaker rule.
    """
    spec = importlib.util.spec_from_file_location(
        "_probe_for_tests", REPO / "scripts" / "regression_probe.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._matches(answer, marker)


# ── divergence classification ───────────────────────────────────────────────────
def test_verdict_names_all_four_outcomes():
    assert H.verdict(True, True) == H.BOTH_PASS
    assert H.verdict(False, False) == H.BOTH_FAIL
    assert H.verdict(True, False) == H.CHAT_ONLY
    assert H.verdict(False, True) == H.V1_ONLY


def test_only_one_sided_verdicts_count_as_divergence():
    """Both-fail is a bad case or a broken system, and says nothing about the wiring."""
    assert H.CHAT_ONLY in H.DIVERGENT and H.V1_ONLY in H.DIVERGENT
    assert H.BOTH_PASS not in H.DIVERGENT and H.BOTH_FAIL not in H.DIVERGENT


# ── the co-reference verdict (BUG-524) ──────────────────────────────────────────
def test_coreference_correct_when_only_the_new_referent_is_named():
    answer = "Room 3.27 is currently 21.4 °C."
    assert H.coreference_verdict(answer, "3.27", "5.01", _matches) == H.CO_CORRECT


def test_coreference_carried_is_the_bug_524_shape():
    """The user asked about B; the answer is about A and never mentions B."""
    answer = "Room 5.01 is currently 21.4 °C, based on 288 readings."
    assert H.coreference_verdict(answer, "3.27", "5.01", _matches) == H.CO_CARRIED


def test_coreference_both_named_is_not_reported_as_carried():
    """'B is warmer than A' is a good answer and must not be scored as a defect."""
    answer = "Room 3.27 is 22.1 °C, about a degree warmer than room 5.01."
    assert H.coreference_verdict(answer, "3.27", "5.01", _matches) == H.CO_BOTH


def test_coreference_neither_named_is_its_own_outcome():
    answer = "I do not have readings for that room."
    assert H.coreference_verdict(answer, "3.27", "5.01", _matches) == H.CO_NEITHER


def test_check_turn_fails_a_carried_referent_and_passes_a_correct_one():
    turn = {"question": "What about room 3.27?", "coref": ["3.27", "5.01"]}
    ok, why, outcome = H.check_turn(turn, "Room 5.01 is 21.4 °C.", _matches)
    assert ok is False and outcome == H.CO_CARRIED and "5.01" in why
    ok, why, outcome = H.check_turn(turn, "Room 3.27 is 22.0 °C.", _matches)
    assert ok is True and outcome == H.CO_CORRECT and why == ""


def test_check_turn_fails_an_empty_answer():
    ok, why, _ = H.check_turn({"question": "q"}, "   ", _matches)
    assert ok is False and "empty" in why


def test_check_turn_without_a_coref_is_scored_on_markers_alone():
    turn = {"question": "q", "expect_any": ["°c", "degrees"]}
    ok, _, outcome = H.check_turn(turn, "It is 21.4 °C.", _matches)
    assert ok is True and outcome == ""
    ok, why, _ = H.check_turn(turn, "I cannot answer that.", _matches)
    assert ok is False and "none of" in why


# ── marker evaluation on a case ─────────────────────────────────────────────────
def test_evaluate_case_honours_expect_forbid_and_expect_any():
    case = {
        "expect": ["estates operations", "24"],
        "forbid": ["documents do not answer"],
        "expect_any": ["dep-01", "estates"],
    }
    ok, why = H.evaluate_case(
        case, "Estates Operations, DEP-01, within 24 hours.", "", [], _matches
    )
    assert ok is True and why == ""
    ok, why = H.evaluate_case(case, "Estates Operations, within 8 hours.", "", [], _matches)
    assert ok is False and "missing" in why
    ok, why = H.evaluate_case(
        case, "Estates Operations, 24 hours. The documents do not answer this.", "", [], _matches
    )
    assert ok is False and "forbidden" in why


def test_evaluate_case_fails_an_empty_answer_even_with_no_markers():
    ok, why = H.evaluate_case({}, "", "", [], _matches)
    assert ok is False and "empty" in why


def test_evaluate_case_checks_the_lane_when_the_endpoint_reports_one():
    case = {"expect_intent": "metadata"}
    ok, why = H.evaluate_case(case, "12 sensors.", "capability", [], _matches)
    assert ok is False and "expected 'metadata'" in why
    ok, _ = H.evaluate_case(case, "12 sensors.", "metadata", [], _matches)
    assert ok is True


def test_a_lane_assertion_is_skipped_not_assumed_when_intent_is_unreported():
    """/v1 reports no intent. Passing the case there anyway would flatter the demo endpoint.

    So the assertion is skipped — the case is scored on text alone — and the run is
    REQUIRED to say so, which is what `case_checks_intent` marks.
    """
    case = {"expect_intent": "metadata"}
    ok, why = H.evaluate_case(case, "12 sensors.", None, [], _matches)
    assert ok is True and why == ""
    assert H.case_checks_intent(case) is True
    assert H.case_checks_intent({"expect": ["x"]}) is False


def test_a_live_graph_expectation_that_could_not_run_fails_the_case():
    """A check that could not be evaluated must never report green (the probe's own rule)."""
    ok, why = H.evaluate_case(
        {}, "206 sensors are overdue.", "", ["<graph query failed>"], _matches
    )
    assert ok is False and "missing" in why


# ── figures one endpoint states and the other does not ──────────────────────────
def test_numbers_in_normalises_separators_and_ignores_word_internal_digits():
    assert "2728" in H.numbers_in("There are 2,728 sensors.")
    assert "21.4" in H.numbers_in("It is 21.4 °C right now.")
    assert H.numbers_in("room5b has no figure") == set()


def test_numeric_divergence_reports_both_directions():
    out = H.numeric_divergence("21.4 °C from 288 readings", "21.4 °C from 144 readings")
    assert out["shared"] == ["21.4"]
    assert out["only_chat"] == ["288"] and out["only_v1"] == ["144"]


def test_numeric_divergence_is_empty_when_the_figures_agree():
    out = H.numeric_divergence("21.4 °C over 288 readings", "Roughly 21.4 degrees (288 readings).")
    assert out["only_chat"] == [] and out["only_v1"] == []


# ── building vocabulary ─────────────────────────────────────────────────────────
def test_marker_token_drops_the_prose_qualifier():
    assert H.marker_token("Room 2.01 — Research Laboratory") == "2.01"
    assert H.marker_token("Room 0.10 (Building Management Office)") == "0.10"


def test_marker_token_keeps_the_whole_phrase_for_a_bare_small_number():
    """'3' alone would match the 3 in '3 sensors' and invent a defect."""
    assert H.marker_token("Floor 3 (Third Floor)") == "floor 3"
    assert H.marker_token("Floor 0 (Ground Floor)") == "floor 0"


def test_distinguishable_refuses_a_marker_contained_in_the_other():
    assert H.distinguishable("2.01", "3.27") is True
    assert H.distinguishable("0.1", "0.10") is False
    assert H.distinguishable("floor 3", "floor 3") is False


def test_pick_distinguishable_pair_skips_the_confusable_pair():
    pair = H.pick_distinguishable_pair(["Room 0.1 — A", "Room 0.10 — B", "Room 4.22 — C"])
    assert pair == ("Room 0.1 — A", "Room 4.22 — C")


def test_pick_distinguishable_pair_returns_none_when_nothing_separates():
    assert H.pick_distinguishable_pair(["Room 0.1 — A", "Room 0.10 — B"]) is None


# ── the conversations carry no building literal ─────────────────────────────────
_ROOM_LIKE = re.compile(r"\b\d+\.\d+\b")


def test_no_conversation_template_names_a_room_or_a_floor():
    """Would this run unchanged for bldg2? Only if every place is a placeholder."""
    for conv in H.CONVERSATIONS:
        for turn in conv["turns"]:
            blob = " ".join(
                [turn["question"]]
                + list(turn.get("expect_any") or [])
                + list(turn.get("coref") or [])
            )
            stripped = re.sub(r"\{[a-z_]+\}", "", blob)
            assert not _ROOM_LIKE.search(stripped), f"{conv['id']}: literal place in {blob!r}"
            assert "floor " not in stripped.lower(), f"{conv['id']}: literal floor in {blob!r}"


def test_render_conversations_substitutes_every_placeholder():
    vocab = {
        "floor_a": "Floor 3",
        "floor_b": "Floor 4",
        "floor_a_token": "floor 3",
        "floor_b_token": "floor 4",
        "room_a": "Room 3.27",
        "room_b": "Room 4.11",
        "room_a_token": "3.27",
        "room_b_token": "4.11",
    }
    rendered = H.render_conversations(H.CONVERSATIONS, vocab)
    assert len(rendered) == len(H.CONVERSATIONS)
    for conv in rendered:
        for turn in conv["turns"]:
            assert "{" not in turn["question"]
            for marker in list(turn.get("expect_any") or []) + list(turn.get("coref") or []):
                assert "{" not in marker


def test_render_conversations_raises_on_an_unknown_placeholder():
    """A leftover placeholder would be asked, answered and scored as if it meant something."""
    with pytest.raises(KeyError):
        H.render_conversations([{"id": "x", "why": "", "turns": [{"question": "{nope}"}]}], {})


def test_every_negative_conversation_switches_the_referent():
    """The whole point of the negative cases: turn 2 must name the OTHER place."""
    negatives = [c for c in H.CONVERSATIONS if c["id"].startswith("negative-")]
    assert negatives, "the BUG-524 hunt needs at least one negative conversation"
    for conv in negatives:
        first, second = conv["turns"][0], conv["turns"][1]
        assert "{room_a}" in first["question"]
        assert "{room_b}" in second["question"]
        assert second["coref"] == ["{room_b_token}", "{room_a_token}"]


def test_conversations_are_genuinely_multi_turn():
    assert all(len(c["turns"]) >= 2 for c in H.CONVERSATIONS)
    assert any(len(c["turns"]) >= 3 for c in H.CONVERSATIONS), "need a three-turn conversation"


# ── the /v1 message array ───────────────────────────────────────────────────────
def test_v1_messages_on_a_first_turn_is_just_the_question():
    assert H.v1_messages([], "How warm is it?") == [{"role": "user", "content": "How warm is it?"}]


def test_v1_messages_replays_history_in_order():
    """Open WebUI sends the whole exchange. A harness that did not would measure no client."""
    msgs = H.v1_messages([("q1", "a1"), ("q2", "a2")], "q3")
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant", "user"]
    assert [m["content"] for m in msgs] == ["q1", "a1", "q2", "a2", "q3"]


def test_v1_messages_puts_the_current_question_last():
    msgs = H.v1_messages([("q1", "a1")], "q2")
    assert msgs[-1] == {"role": "user", "content": "q2"}


# ── the corpus is reused, not forked ────────────────────────────────────────────
def test_the_harness_reads_the_regression_probe_s_own_case_file():
    """A second corpus would drift from the first and the comparison would mean nothing."""
    assert H.CASES_PATH == REPO / "scripts" / "regression_cases.json"
    assert H.CASES_PATH.exists()
    source = (REPO / "scripts" / "endpoint_parity_probe.py").read_text(encoding="utf-8")
    assert "regression_cases.json" in source
    # No case question is copied into the harness: the only question text it holds is its
    # own conversation templates, every one of which carries a placeholder.
    import json

    questions = {c["question"] for c in json.loads(H.CASES_PATH.read_text(encoding="utf-8"))}
    for conv in H.CONVERSATIONS:
        for turn in conv["turns"]:
            assert turn["question"] not in questions


# ── the report ──────────────────────────────────────────────────────────────────
def test_report_puts_divergent_cases_first():
    single = [
        {
            "group": "g",
            "question": "boring",
            "chat_ok": True,
            "v1_ok": True,
            "chat_why": "",
            "v1_why": "",
            "verdict": H.BOTH_PASS,
            "intent_check_skipped": False,
            "numbers": {"shared": [], "only_chat": [], "only_v1": []},
        },
        {
            "group": "g",
            "question": "interesting",
            "chat_ok": True,
            "v1_ok": False,
            "chat_why": "",
            "v1_why": "missing ['x']",
            "verdict": H.CHAT_ONLY,
            "intent_check_skipped": False,
            "numbers": {"shared": [], "only_chat": [], "only_v1": []},
        },
    ]
    text = "\n".join(H.report_lines(single, [], {}))
    assert text.index("interesting") < text.index("boring")
    assert "1 divergent" in text


def test_report_states_when_a_lane_assertion_could_not_be_checked_on_v1():
    single = [
        {
            "group": "g",
            "question": "q",
            "chat_ok": True,
            "v1_ok": True,
            "chat_why": "",
            "v1_why": "",
            "verdict": H.BOTH_PASS,
            "intent_check_skipped": True,
            "numbers": {"shared": [], "only_chat": [], "only_v1": []},
        }
    ]
    text = "\n".join(H.report_lines(single, [], {}))
    assert "does not report one" in text
