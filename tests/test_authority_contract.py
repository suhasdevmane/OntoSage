# -*- coding: utf-8 -*-
"""Source precedence (V6-T21) and the never-infer-permission rule set (V6-T22).

Rule R-7: bookings, access events, timetables and alarms come from authorised systems, never
from environmental inference. Rule R-8, the four chains the PhD catalogue lists:

    empty is not available · open is not accessible · quiet is not private ·
    presence is not permission

These are the errors a fluent assistant makes most naturally, and each is a real-world harm —
telling someone a booked room is free, or that a conversation cannot be overheard. That is why
the guard matches the QUESTION rather than the answer: BUG-213 showed what happens when a
safety property depends on model output being well-formed.

Both gates are ADVISORY. The permission guard is the strongest candidate in V6 for early
enforcement, and that decision belongs to the impact report rather than to a default — but the
verdict already carries the full route, so flipping the switch changes only whether the answer
is replaced. Asserted below so that a later change to enforcing is a deliberate act with a
failing test to update, not a silent one.

Everything here goes through `build_evidence_record` or the pure modules' real API — never a
mock of the thing under test.
"""

from datetime import datetime, timezone

import pytest

from orchestrator.services.evidence.assemble import build_evidence_record
from orchestrator.services.evidence.permission_guard import assess, detect_claim, unlicensed_kinds
from orchestrator.services.evidence.precedence import SourceClaim, resolve, tier_for_kind
from shared.models import AnswerStatus

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)


# ── T21: the ordering itself ─────────────────────────────────────────────────


def test_a_system_of_record_outranks_a_sensor():
    v = resolve(
        [
            SourceClaim("booking-1", "authoritative", value=1.0, label="Booking system"),
            SourceClaim("occ-1", "measurement", value=0.0, label="Occupancy sensor"),
        ],
        tolerance=0.5,
    )
    assert v.winning_tier == "authoritative"
    assert v.has_authority
    assert v.disagreement, "an empty room against a live booking is a disagreement worth stating"


def test_the_disagreement_is_reported_not_resolved():
    """Silent agreement is the subtler error. A booking that says occupied over a room that is
    empty is a no-show — dropping the sensor hides a fact worth knowing."""
    v = resolve(
        [
            SourceClaim("booking-1", "authoritative", value=1.0, label="Booking"),
            SourceClaim("occ-1", "measurement", value=0.0, label="Occupancy"),
        ],
        tolerance=0.5,
    )
    text = v.describe()
    assert "Booking" in text and "Occupancy" in text
    assert "cannot overrule" in text or "not resolved" in text.lower() or "stated" in text


def test_agreeing_tiers_are_not_narrated_as_conflict():
    v = resolve(
        [
            SourceClaim("booking-1", "authoritative", value=1.0),
            SourceClaim("occ-1", "measurement", value=1.0),
        ],
        tolerance=0.5,
    )
    assert not v.disagreement
    assert v.describe() == ""


def test_an_undeclared_tolerance_reports_rather_than_judges():
    """Same rule the conflict module follows: without a declared tolerance nobody has said how
    close is close enough, so two different numbers are surfaced, not silently reconciled."""
    v = resolve(
        [
            SourceClaim("b", "authoritative", value=1.0),
            SourceClaim("s", "measurement", value=1.05),
        ],
        tolerance=None,
    )
    assert v.disagreement


def test_an_unknown_source_kind_can_never_outrank_anything():
    """Conservative by construction — a kind nobody classified must not acquire authority."""
    assert tier_for_kind("some_new_integration") == "unknown"
    v = resolve(
        [
            SourceClaim("x", tier_for_kind("some_new_integration"), value=9.0),
            SourceClaim("s", "measurement", value=1.0),
        ],
        tolerance=0.5,
    )
    assert v.winning_tier == "measurement", "an unclassified source outranked a measurement"


def test_policy_can_declare_a_kind_without_touching_code():
    assert tier_for_kind("turnstile", {"turnstile": "authoritative"}) == "authoritative"


def test_the_winning_tier_reaches_the_record():
    rec = build_evidence_record(
        {
            "sql_result": {
                "results": {"data": [{"uuid": "s-1", "datetime": NOW.isoformat(), "value": 1.0}]}
            },
            "_prov_stores": [
                {"source_id": "s-1", "kind": "sensor"},
                {"source_id": "reg-1", "kind": "register"},
            ],
        },
        now=NOW,
    )
    assert rec.source_tier == "authoritative", (
        "the record must state WHAT KIND of source answered — a reader cannot tell from a "
        "number alone"
    )


# ── T22: the four inference chains ───────────────────────────────────────────


@pytest.mark.parametrize(
    "question,kind",
    [
        ("Is room 2.14 free right now?", "availability"),
        ("Which meeting rooms are available this afternoon?", "availability"),
        ("Can I get into the server room?", "access"),
        ("Is the route to Room 3.02 step-free?", "access"),
        ("Is the small pod private enough for a confidential call?", "privacy"),
        ("Can anyone overhear me in the phone booth?", "privacy"),
        ("Am I allowed in the plant room?", "permission"),
        ("Who is authorised to access the roof?", "permission"),
    ],
)
def test_each_chain_is_recognised(question, kind):
    claim = detect_claim(question)
    assert claim is not None, f"no entitlement detected in {question!r}"
    assert claim.kind == kind


@pytest.mark.parametrize(
    "question",
    [
        "What is the temperature in room 2.14?",
        "How many people are on floor 5 right now?",
        "Is the corridor clear of obstructions?",
        "When was the fire alarm last tested?",
    ],
)
def test_ordinary_questions_are_not_entitlement_claims(question):
    """The guard must not intercept physical questions that happen to share vocabulary —
    'is the corridor clear' is about obstructions, not about permission."""
    assert detect_claim(question) is None, f"false entitlement on {question!r}"


def test_sensor_only_evidence_never_licenses_an_entitlement_claim():
    finding = assess(
        "Is room 2.14 free right now?",
        has_authoritative_source=False,
        available_tiers=["measurement"],
    )
    assert finding is not None
    assert finding["kind"] == "availability"
    assert "booking" in finding["remedy"].lower(), (
        "the decline must name the route — 'I can't tell you' is unhelpful and tells the "
        "estate nothing about what to connect"
    )


def test_an_authoritative_source_satisfies_the_claim():
    assert assess("Is room 2.14 free?", has_authoritative_source=True) is None


def test_a_question_about_the_record_itself_is_not_intercepted():
    """'Is 2.14 booked this afternoon?' is a booking-system question. Refusing it would
    decline the very question the authority can answer."""
    assert assess("Is room 2.14 booked this afternoon?", has_authoritative_source=False) is None


def test_the_guard_reaches_the_record_and_stays_advisory():
    rec = build_evidence_record(
        {
            "original_query": "Is room 2.14 free right now?",
            "sql_result": {
                "results": {"data": [{"uuid": "occ-1", "datetime": NOW.isoformat(), "value": 0}]}
            },
            "_prov_stores": [{"source_id": "occ-1", "kind": "sensor"}],
        },
        now=NOW,
    )
    assert rec.entitlement_claim == "availability"
    hits = [g for g in rec.gates_advisory if "permission" in g]
    assert hits, "an availability claim on sensor-only evidence raised no verdict"
    assert rec.status == AnswerStatus.OBSERVED, (
        "the permission gate is ADVISORY today; making it enforcing is a decision for the "
        "impact report, and this assertion exists so that change cannot happen silently"
    )


def test_the_chains_are_claim_types_not_building_facts():
    """Building-agnostic by construction: every building has availability and access
    questions, and no building's layout appears in the guard."""
    from pathlib import Path

    src = Path("orchestrator/services/evidence/permission_guard.py").read_text(encoding="utf-8")
    for literal in ("abacws", "bldg1", "Room2.14", "floor 5"):
        assert literal.lower() not in src.lower(), f"building literal {literal!r} in the guard"


def test_a_question_can_trigger_only_the_chain_it_asks_for():
    """Overlapping vocabulary must not fire several chains — a multi-chain match would make
    the reported remedy arbitrary."""
    kinds = unlicensed_kinds("Is room 2.14 free right now?")
    assert kinds == ["availability"], kinds


# ── the recurring heredoc hazard ─────────────────────────────────────────────


def test_no_regex_source_contains_a_control_character():
    """`\b` written through a bash heredoc collapses to a literal backspace (chr(8)).

    Five times in this project. The pattern compiles, reads correctly in a diff, and can never
    match — most recently in the report-intake space resolver, where it was caught only by a
    live probe showing every report unbound. A grep-level assertion costs nothing and fails at
    the commit rather than in production.
    """
    from pathlib import Path as _P

    roots = [_P("orchestrator/services/evidence"), _P("orchestrator/services")]
    checked = 0
    for root in roots:
        for f in root.glob("*.py"):
            text = f.read_text(encoding="utf-8")
            checked += 1
            for ch in ("", "", "", ""):
                assert ch not in text, (
                    f"{f} contains {ch!r} — almost certainly a backslash escape collapsed by a "
                    "heredoc; the pattern will compile and never match"
                )
    assert checked > 20, f"only {checked} files scanned; the glob is wrong"
