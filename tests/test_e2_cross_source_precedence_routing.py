# -*- coding: utf-8 -*-
"""E2 (QA-trial plan, 2026-10-04): "which source is right?" routes to the fact-conflict lane.

``scripts/fact_conflicts.py`` is a complete, standing-tested cross-source fact-conflict
capability with no orchestrator caller. A tester asking "the reception hours differ depending
on who I ask — which is right?" reached nothing, while the scanner that answers it already
ran in CI. This adds one parse-stage rule, appended LAST, and the lane it routes to.

What these tests pin:

* the rule fires on the motivating phrasing and on a handful of equivalent "which is
  right/correct/accurate/true" and "differs depending on who" constructions;
* it does NOT fire on the bare register_projection._CROSS_SOURCE_RE vocabulary alone — that
  vocabulary over-matches physical/scheduling conflicts (fire-door conflicts, delivery-route
  conflicts) that have nothing to do with two STATED facts disagreeing, which is exactly why
  the Approach warned against reusing it unguarded;
* measured over the full 4,060-question bank: 0 moves, reported rather than inflated;
* the lane itself (``fact_conflict_lane.answer_precedence_question``) names every value and
  source when a match is found, declines honestly when nothing overlaps, and never silently
  resolves a disagreement.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from orchestrator.services import routing_contract as rc
from orchestrator.services.fact_conflict_lane import (
    _best_match,
    _keywords,
    answer_precedence_question,
)

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent


def _fires(query: str) -> bool:
    ctx = rc._Ctx(query=query, ql=query.lower(), normalized={"intent": None}, sr=None)
    return rc._r_cross_source_precedence(ctx) == "fact_conflict"


# ── the routing rule ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "The reception hours differ depending on who I ask -- which is right?",
        "Which record is accurate -- the one on the website or the one you just gave me?",
        "Which answer is correct?",
        "Which figure is true, the 24-hour one or the 9-to-5 one?",
        "It depends on who you ask, which source is right?",
    ],
)
def test_the_rule_fires_on_the_precedence_shape(query):
    assert _fires(query), query


@pytest.mark.parametrize(
    "query",
    [
        # register_projection._CROSS_SOURCE_RE vocabulary alone, with no "which is right"
        # framing -- the over-match the Approach explicitly warned against reusing unguarded.
        "Is this evening session likely to conflict with closure or maintenance?",
        "Which delivery routes avoid conflict with public movement?",
        "Which door leaf choices create fire-door conflicts?",
        "Are these denials consistent with anti-passback logic?",
        "Reconcile the last 12 electricity invoices against metered consumption.",
        # ordinary data/comparison questions that happen to contain "which"
        "Which floor has the highest CO2 right now?",
        "Which room is quietest?",
        "What is the temperature in room 2.14?",
    ],
)
def test_the_rule_does_not_fire_on_ordinary_or_vocabulary_only_questions(query):
    assert not _fires(query), query


def test_the_rule_is_last_in_the_parse_stage():
    assert rc.PARSE_STAGE_RULES[-1].name == "cross_source_precedence"


def test_measured_over_the_full_bank_zero_moves():
    """Measured, not assumed: the bank's own synthetic phrasing does not happen to use this
    construction. Reported honestly at 0 rather than inflated with a looser pattern that
    would also catch the physical/scheduling conflicts the previous test pins as excluded."""
    corpus = REPO / "docs" / "smart_building_questions.csv"
    if not corpus.exists():  # pragma: no cover - the file is tracked
        pytest.skip("catalogue corpus not present")
    questions = []
    with corpus.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            for key in ("question", "Question", "text", "Query"):
                if row.get(key):
                    questions.append(row[key].strip())
                    break
    assert len(questions) > 3000, "corpus looks truncated; the measurement would be hollow"
    fired = [q for q in questions if _fires(q)]
    assert fired == [], fired


# ── the lane itself ─────────────────────────────────────────────────────────────────


def test_keywords_strips_the_question_shape_not_the_content():
    kws = _keywords("The reception hours differ depending on who I ask -- which is right?")
    assert "reception" in kws
    assert "hours" in kws
    assert "which" not in kws
    assert "right" not in kws
    assert "depend" not in kws


def test_best_match_picks_the_highest_word_overlap():
    found = {
        ("reception", "hours"): {"07:30-18:00": [], "09:00-16:30": []},
        ("cleaning", "provider"): {"ACME": [], "Nova": []},
    }
    match = _best_match(found, ["reception", "hours"])
    assert match == ("reception", "hours")


def test_best_match_is_none_on_zero_overlap():
    found = {("cleaning", "provider"): {"ACME": [], "Nova": []}}
    assert _best_match(found, ["unrelated", "words"]) is None


async def test_the_lane_declines_honestly_when_the_building_root_cannot_be_found(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "orchestrator.services.fact_conflict_lane._scan_root", lambda building_id: None
    )
    result = await answer_precedence_question("which is right?", "bldg_nonexistent")
    assert result["success"] is False
    assert result["fact_conflict_matches"] == 0


async def test_the_lane_names_every_value_and_source_on_a_real_match(tmp_path, monkeypatch):
    class _FakeFact:
        def __init__(self, source, line):
            self.source = source
            self.line = line

    facts = ["fact-placeholder"]  # scan() is mocked; its return value just needs to exist

    def _fake_scan(root):
        return facts

    def _fake_conflicts(facts_in):
        return {
            ("reception", "hours"): {
                "07:30-18:00": [_FakeFact("documents/reception.md", 12)],
                "09:00-16:30": [_FakeFact("bldg1_capabilities.ttl", 88)],
            }
        }

    def _fake_split_accepted(found):
        return found, {}

    monkeypatch.setattr(
        "orchestrator.services.fact_conflict_lane._scan_root", lambda building_id: tmp_path
    )
    monkeypatch.setattr("scripts.fact_conflicts.scan", _fake_scan)
    monkeypatch.setattr("scripts.fact_conflicts.conflicts", _fake_conflicts)
    monkeypatch.setattr("scripts.fact_conflicts.split_accepted", _fake_split_accepted)

    result = await answer_precedence_question(
        "The reception hours differ -- which is right?", "bldg1"
    )
    assert result["success"] is True
    assert result["fact_conflict_matches"] == 2
    assert "07:30-18:00" in result["formatted_response"]
    assert "09:00-16:30" in result["formatted_response"]
    assert "documents/reception.md:12" in result["formatted_response"]
    assert "resolved" in result["formatted_response"].lower()  # names it as unresolved


async def test_the_lane_declines_honestly_when_nothing_overlaps(tmp_path, monkeypatch):
    def _fake_scan(root):
        return []

    def _fake_conflicts(facts_in):
        return {}

    def _fake_split_accepted(found):
        return found, {}

    monkeypatch.setattr(
        "orchestrator.services.fact_conflict_lane._scan_root", lambda building_id: tmp_path
    )
    monkeypatch.setattr("scripts.fact_conflicts.scan", _fake_scan)
    monkeypatch.setattr("scripts.fact_conflicts.conflicts", _fake_conflicts)
    monkeypatch.setattr("scripts.fact_conflicts.split_accepted", _fake_split_accepted)

    result = await answer_precedence_question("which is right?", "bldg1")
    assert result["success"] is True
    assert result["fact_conflict_matches"] == 0
    assert "did not find" in result["formatted_response"].lower()


# ── wiring ──────────────────────────────────────────────────────────────────────────


def test_the_node_method_exists_and_the_intent_is_declared():
    from orchestrator.intents.registry import get_intent_registry
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    assert hasattr(WorkflowOrchestrator, "_fact_conflict_node")
    registry = get_intent_registry()
    names = {i.name for i in registry.intents}
    assert "fact_conflict" in names


def test_fact_conflict_result_is_cleared_between_turns():
    from orchestrator.workflow._orchestrator import _PER_TURN_LANE_KEYS

    assert "fact_conflict_result" in _PER_TURN_LANE_KEYS
