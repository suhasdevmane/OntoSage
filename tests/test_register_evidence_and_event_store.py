# -*- coding: utf-8 -*-
"""A register needs a word that NAMES it, is scored fast, and is not declared absent when held.

Three defects, one module (orchestrator/services/record_registry.py):

* BUG-693 — a register was selected on any hit, including a term that only opens a hyphenated
  compound: "a complete post-work test" was a PatrolCheckpoint question ("post"), "warranty-return
  parts" a Warranty question. The exemplars below are real stakeholder-catalogue questions, and
  the verdicts beside them were READ, not assumed: of the 21 selections the rule removes, 1 was
  right, 6 partial and 14 wrong. Blunter floors were measured and rejected — see
  `record_registry._only_modifies`.
* BUG-694 — every lookup compiled ~900 patterns against a 512-entry cache. The precompiled scorer
  must score EXACTLY as the inline one did; a reference copy of the old code is the oracle here.
* BUG-670 — the absent-class decline counted graph instances only, so it could say "this building
  holds no anomaly event records" while the events store held ~185,600 of them.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import random
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.services import record_registry as rr
from orchestrator.services.record_registry import (
    RecordClass,
    absent_record_class,
    event_store_record_classes,
    held_record_class,
)

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]


def _harness():
    name = "_test_register_evidence_harness"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / "register_reach.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def harness():
    return _harness()


@pytest.fixture(scope="module")
def schema(harness):
    return harness.load_schema(harness.SCHEMA)


@pytest.fixture(scope="module")
def guard(harness):
    return harness.read_guard(harness.GUARD)


@pytest.fixture(scope="module")
def bldg(harness, schema, guard):
    """The router's view of the building the guard set was derived on, from files alone."""
    meta, _rows = guard
    return harness.Reach(schema, meta["snapshot"])


# ── BUG-693: the minimum evidence ───────────────────────────────────────────────────────

#: Selections the rule REMOVES, with the verdict from reading them. Every one opens a compound.
REMOVED = [
    # wrong: a test after work, not a patrol post
    "Which authorised maintenance window would cause the least teaching disruption while still "
    "allowing a complete post-work test?",
    # wrong: welfare actions after an incident
    "Which authorised post-incident welfare, support and contact actions remain open, and which "
    "data may be used to manage them?",
    # wrong: a parts custody route, not a warranty
    "What is the authorised custody route for unused, defective, warranty-return and removed parts "
    "after the job?",
    # wrong: an evidence package for a report, not access permissions
    "Can you produce a transparent, permission-controlled evidence package for our project report "
    "that includes relevant building conditions but excludes research content and restricted "
    "operational details?",
    # wrong: social value, not a contract
    "What contract-related social-value outcome is additional, measurable and attributable without "
    "double counting existing or unrelated activity?",
    # wrong: feedback signals, not the timetable
    "Which timetable-feedback signals meet the agreed threshold for owner review, and which still "
    "need more evidence?",
    # wrong: AV capture kit, not a timetabled lecture
    "Is the authorised lecture-capture endpoint technically ready for the next scheduled recording "
    "window?",
]

#: Selections the rule KEEPS and that read right — including compounds whose HEAD is the term.
KEPT = [
    (
        "For each material building cost line, what changed because of unit price, measured "
        "quantity, timing, accounting treatment or authorised scope?",
        "CostLine",
    ),
    (
        "Which current student workspace has verified step-free access, suitable adjustable "
        "furniture, power and a comparatively calm environment for a long writing session?",
        "WorkspaceProfile",
    ),
    (
        "Where are inspection records or monitoring intervals missing, delayed, corrupted or "
        "unavailable, and which decisions or reports must remain open as a result?",
        "ComplianceCheck",
    ),
    (
        "Which tariff periods, mapped loads and verified operating events account for the largest "
        "current electricity, gas, heat and water costs?",
        "Tariff",
    ),
    # compound HEADS: waste points, microphone battery, workspace types
    (
        "Which authorised sharps or clinical-waste points require competent attention based only "
        "on their external status?",
        "WasteCollectionPoint",
    ),
    (
        "Which rooms starting soon need a charged wireless-microphone battery or an approved spare "
        "staged in advance?",
        "AVReadiness",
    ),
    (
        "Using aggregate evidence only, are some staff-workspace types consistently less accessible "
        "or environmentally suitable than others?",
        "WorkspaceProfile",
    ),
]


@pytest.mark.parametrize("question", REMOVED)
def test_a_term_that_only_opens_a_compound_selects_no_register(bldg, question):
    assert bldg.register(question)["held"] is None


@pytest.mark.parametrize("question, cls", KEPT)
def test_a_term_that_names_the_thing_still_selects_it(bldg, question, cls):
    assert bldg.register(question)["held"] == cls


def test_the_guard_set_does_not_move(harness, bldg, guard):
    """Probe, demo-script and documented-trap questions keep the register they pass on."""
    _meta, rows = guard
    hard = [v for v in harness.guard_violations(bldg, rows) if v["status"] == "VIOLATION"]
    assert not hard, json.dumps(hard, indent=1)


def _patrol():
    return [RecordClass("PatrolCheckpoint", "Patrol checkpoint", 18, ("post", "posts"))]


def test_the_compound_rule_is_about_position_not_about_hyphens():
    held = _patrol()
    assert held_record_class("allow a complete post-work test", held) is None
    assert held_record_class("if the command-post must move", held) is not None, "head of compound"
    assert held_record_class("which posts are unstaffed?", held) is not None, "standalone"


def test_one_standalone_occurrence_is_enough():
    held = _patrol()
    assert held_record_class("after the post-work check, is the post staffed?", held) is not None


def test_a_modifier_hit_still_adds_to_a_class_another_word_names():
    """Discounted, not rejected (`_COMPOUND_WEIGHT`): it counts once something names the class."""
    contract = RecordClass("Contract", "Contract", 8, ("contract", "supplier"))
    alone = rr.rank_record_classes("a contract-fixed line", [contract])
    both = rr.rank_record_classes("a contract-fixed line with this supplier", [contract])
    assert alone == []
    assert both and both[0][0] == pytest.approx(8 * 1.0 + 8 * rr._COMPOUND_WEIGHT)


def test_the_documented_contract_fixed_trap_still_reaches_costline():
    classes = [
        RecordClass("Contract", "Contract", 8, ("contract", "contracts")),
        RecordClass("CostLine", "Cost line", 24, ("spend", "cost line")),
    ]
    q = "what proportion of spend is planned, reactive, statutory, contract-fixed or demand-led"
    assert held_record_class(q, classes).local_name == "CostLine"


# ── BUG-694: precompiled, and scoring exactly as before ────────────────────────────────


def _old_term_score(term: str, low: str) -> float:
    """record_registry._term_score as it was before precompilation — the oracle."""
    best = 0.0
    for m in re.finditer(rf"\b{re.escape(term)}\b", low):
        weight = float(len(term)) * (2.0 if " " in term else 1.0)
        before = low[m.start() - 1] if m.start() else " "
        after = low[m.end()] if m.end() < len(low) else " "
        if before == "-" or after == "-":
            weight *= 0.25
        best = max(best, weight)
    return best


def _old_qualifier_score(term: str, low: str) -> float:
    best = 0.0
    for m in re.finditer(rf"\b{re.escape(term)}\b", low):
        following = re.match(r"[\s\"'(]*([a-z][a-z0-9]*)", low[m.end() :])
        if following and following.group(1) not in rr._FUNCTION_WORDS:
            continue
        best = max(best, _old_term_score(term, low[m.start() - 1 : m.end() + 1]))
    return best


def _old_absent(query, held):
    held_names = {r.local_name for r in held}
    low = f" {(query or '').lower()} "

    def _longest_hit(terms):
        best = 0
        for term in terms:
            if len(term) > best and re.search(rf"\b{re.escape(term)}\b", low):
                best = len(term)
        return best

    best_held = max((_longest_hit(r.terms) for r in held), default=0)
    best_name, best_len = None, 0
    for name, terms in rr._ALL_CLASS_TERMS.items():
        if name in held_names:
            continue
        hit = _longest_hit(terms)
        if hit > best_len or (hit and hit == best_len and name < (best_name or "￿")):
            best_name, best_len = name, hit
    return best_name if best_len and best_len > best_held else None


@pytest.fixture(scope="module")
def sample_questions(harness):
    questions = [q for _, q in harness.recall_questions()]
    return random.Random(694).sample(questions, 300)


def test_precompiled_scores_equal_the_inline_scorer(bldg, sample_questions):
    checked = 0
    for question in sample_questions:
        low = f" {question.lower()} "
        for record in bldg.held:
            for term in record.terms:
                assert rr._term_score(term, low) == _old_term_score(term, low), (term, question)
                assert rr._qualifier_score(term, low) == _old_qualifier_score(term, low)
                checked += 1
    assert checked > 100_000


def test_precompiled_absent_decline_equals_the_inline_one(bldg, sample_questions):
    for question in sample_questions + ["Show me the anomaly events", "any alarms this week?"]:
        assert absent_record_class(question, bldg.held, stored_elsewhere=()) == _old_absent(
            question, bldg.held
        ), question


def test_a_term_is_compiled_once_and_the_cache_clears():
    rr.clear_cache()
    first = rr._term_pattern("permit to work")
    assert rr._term_pattern("permit to work") is first
    rr.clear_cache()
    assert "permit to work" not in rr._TERM_PATTERNS


def test_no_scoring_path_builds_a_pattern_inline():
    """The regression this guards: one `re.finditer(rf"...")` in a scorer brings BUG-694 back."""
    import inspect

    for fn in (rr._term_score, rr._qualifier_score, rr._only_modifies, rr.absent_record_class):
        src = inspect.getsource(fn)
        assert "re.finditer(" not in src and "re.search(" not in src, fn.__name__
        assert "re.match(" not in src, fn.__name__


# ── BUG-670: records held in a registered events store are not absent ───────────────────

EVENT_KINDS = ("anomaly_summary", "workorder_summary", "access_summary", "bookings_list")


def test_the_kinds_the_events_service_answers_name_their_classes():
    names = [
        "AnomalyEvent",
        "AlarmEvent",
        "AccessEvent",
        "AccessPermission",
        "WorkOrder",
        "Booking",
        "PublicEvent",
        "EventActivity",
    ]
    assert event_store_record_classes(names, EVENT_KINDS) == {
        "AnomalyEvent",
        "AccessEvent",
        "WorkOrder",
        "Booking",
    }
    assert event_store_record_classes(names, ()) == frozenset()


def test_the_join_uses_the_services_real_kind_names():
    """Not a copy: if the service renames a kind, this is where the join breaks."""
    from orchestrator.services.event_query_service import _KIND_RES

    kinds = [kind for kind, _ in _KIND_RES]
    assert "AnomalyEvent" in event_store_record_classes(["AnomalyEvent"], kinds)


@pytest.fixture
def absent_vocabulary(monkeypatch):
    monkeypatch.setattr(
        rr,
        "_ALL_CLASS_TERMS",
        {
            "AlarmEvent": ("alarm", "alarms"),
            "AnomalyEvent": ("anomaly", "anomalies", "anomaly events"),
            "UnusualThing": ("anomal",),
        },
    )


def test_a_kind_the_store_holds_is_not_declared_absent(absent_vocabulary):
    q = "Show me the anomaly events"
    assert absent_record_class(q, [], stored_elsewhere=()) == "AnomalyEvent"
    assert absent_record_class(q, [], stored_elsewhere=["AnomalyEvent"]) is None


def test_a_kind_the_store_does_not_answer_is_still_declined(absent_vocabulary):
    assert absent_record_class("any alarms this week?", [], ["AnomalyEvent"]) == "AlarmEvent"


def test_a_store_held_kind_outranks_a_shorter_absent_match_like_a_held_one(monkeypatch):
    monkeypatch.setattr(
        rr, "_ALL_CLASS_TERMS", {"AnomalyEvent": ("anomaly events",), "Shorter": ("events",)}
    )
    assert absent_record_class("show the anomaly events", [], ["AnomalyEvent"]) is None


class _EventsAdapter:
    def build_overlap_window(self, *args, **kwargs):  # pragma: no cover - never called
        return ""


def _registry(monkeypatch, adapter):
    import orchestrator.services.adapters.registry as registry

    monkeypatch.setattr(
        registry, "adapter_registry", SimpleNamespace(get=lambda _key=None: adapter)
    )


@pytest.fixture
def fresh(monkeypatch, absent_vocabulary):
    monkeypatch.setattr(rr, "_EVENT_STORE_CLASSES", frozenset())
    monkeypatch.setattr(rr, "_LAY_LOADED", True)  # vocabulary already loaded: no graph call
    yield
    rr._EVENT_STORE_CLASSES = frozenset()


async def test_a_registered_events_store_is_read_from_configuration(monkeypatch, fresh):
    _registry(monkeypatch, _EventsAdapter())
    await rr.load_lay_terms()
    assert "AnomalyEvent" in rr._EVENT_STORE_CLASSES
    assert absent_record_class("Show me the anomaly events", []) is None


async def test_no_registered_store_keeps_the_decline(monkeypatch, fresh):
    _registry(monkeypatch, None)
    await rr.load_lay_terms()
    assert rr._EVENT_STORE_CLASSES == frozenset()
    assert absent_record_class("Show me the anomaly events", []) == "AnomalyEvent"


async def test_the_registrys_default_fallback_is_not_an_events_store(monkeypatch, fresh):
    """`adapter_registry.get` falls back to the DEFAULT adapter for a missing key."""
    _registry(monkeypatch, SimpleNamespace(execute_query=None))
    await rr.load_lay_terms()
    assert absent_record_class("Show me the anomaly events", []) == "AnomalyEvent"


def _write_config(tmp_path, listed: bool, db_type: str):
    storage = "    - events_data\n" if listed else "    - database1\n"
    (tmp_path / "building.yaml").write_text(
        "building_id: x\nstorage:\n  databases:\n" + storage, encoding="utf-8"
    )
    (tmp_path / "database_registry.yaml").write_text(
        f"databases:\n  events_data:\n    type: {db_type}\n    table: events\n", encoding="utf-8"
    )


def test_the_harness_reads_registration_from_both_configs(harness, tmp_path):
    key, kinds = harness.declared_event_kinds()
    assert key.endswith("events_data") and "anomaly_summary" in kinds
    _write_config(tmp_path, listed=True, db_type="mysql_events")
    assert harness.events_store_registered(tmp_path, key)
    _write_config(tmp_path, listed=False, db_type="mysql_events")
    assert not harness.events_store_registered(tmp_path, key)
    _write_config(tmp_path, listed=True, db_type="mysql_narrow")
    assert not harness.events_store_registered(tmp_path, key)
    assert not harness.events_store_registered(tmp_path / "missing", key)


def test_catalogue_anomaly_questions_are_no_longer_declined(harness, schema, guard):
    """Measured: 6 catalogue questions were declined as AnomalyEvent; with the store, none."""
    meta, rows = guard
    stored = ("AccessEvent", "AnomalyEvent", "Booking", "WorkOrder")
    without = harness.Reach(schema, meta["snapshot"])
    with_store = harness.Reach(schema, meta["snapshot"], stored)
    questions = [
        "Is this humidity or particulate anomaly local, outdoor-driven or shared across a verified "
        "ventilation zone?",
        "Before escalating an anomaly, what independent evidence corroborates it, and what "
        "plausible sensor, context or data-processing explanations remain?",
    ]
    for q in questions:
        assert without.register(q)["absent"] == "AnomalyEvent"
        assert with_store.register(q)["absent"] is None
    hard = [v for v in harness.guard_violations(with_store, rows) if v["status"] == "VIOLATION"]
    assert not hard, json.dumps(hard, indent=1)


def test_the_catalogue_file_holds_these_questions(harness):
    """The exemplars are catalogue questions, not paraphrases."""
    with harness.CORPUS.open(encoding="utf-8-sig", newline="") as handle:
        corpus = {row["Question"] for row in csv.DictReader(handle)}
    for q in REMOVED + [q for q, _ in KEPT]:
        assert q in corpus, q
