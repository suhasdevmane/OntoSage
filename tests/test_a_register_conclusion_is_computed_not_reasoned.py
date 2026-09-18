# -*- coding: utf-8 -*-
"""BUG-709: the conclusion over a register is computed, not reasoned to in prose.

The largest class in the 2026-09-17 hand read of 147 live stakeholder answers — 20 rows, one
weird answer in five. In every one the lane fetched the RIGHT records and the narration
invented the verdict:

* "Which permission groups or zones are orphaned because no current owner, purpose or mapped
  opening can be evidenced?" -> "Each of the 20 records contains a mapped opening and a granted
  role, so none lack the basic evidence of ownership, purpose" (row 3).
* "…containment and isolation details…" -> "assets list probable containment features that
  would limit damage from a leak" — no field records containment (row 11).
* An escorted contractor's one-off lab permit reported as a "verified starter" package (row 5);
  chiller, generator and sprinkler handovers used to answer whether an EVENT-SPACE handover is
  complete (row 34); `recordStatus` relabelled "Condition" and a capital value band
  "Whole-life cost" (row 36); an inspection interval offered to an engineer as a trend sampling
  rate (row 55); "cancelled" read as "no-show" (row 78); a static "degraded" read as running
  outside a schedule "right now" (row 113).
* Two due dates computed wrong in one answer (row 54); rooms 2.15, 4.11 and 4.12 filed under
  floor 3 (rows 60, 92); a cleaner told to fill a clinical sharps bin to its threshold
  (row 19); a role assumed and an instruction issued to the wrong staff group (row 63); a day
  plan that decided which timetabled sessions were the student's (row 90).

Each of those is an OPERATION over the fetched rows, performed in prose. The rows below are the
shapes the record-document lifter produces for the registers that answered those questions —
camelCase predicate local names, every cell a `{"value": …}` binding — and the assertions are
that the operation now comes out of the code, including where the honest output is "no field
records this".
"""

from __future__ import annotations

from datetime import date

import pytest

from orchestrator.services.register_facts import register_facts

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 17)

#: The line naming the question's words that the register holds nowhere. Named once, because
#: its wording has to keep changing: it reached 23 readers verbatim in the run-5 measurement.
ABSENT = "VOCABULARY NOTE, NOT A FINDING"


def _row(**kw):
    return {k: {"value": v} for k, v in kw.items()}


def _line(facts: str, needle: str) -> str:
    for line in facts.splitlines():
        if needle in line:
            return line
    raise AssertionError(f"no line containing {needle!r} in:\n{facts}")


# ── the access permission register (rows 3 and 5) ──────────────────────────────────────

PERMISSIONS = [
    _row(
        recordId=f"APG-{i:03d}",
        label=f"Permission group {i}",
        controlsOpening="Main entrance turnstile",
        grantedToRole="All staff",
        timeProfile="CORE",
        approvalRoute="Security Systems",
        effectiveFrom="2026-01-01",
        recordStatus="active",
        recordOwner="Access Control Administrator",
    )
    for i in range(1, 20)
] + [
    _row(
        recordId="APG-013",
        label="Instrument recalibration - one-off",
        controlsOpening="Room 3.06 laboratory door",
        grantedToRole="External contractor",
        timeProfile="ESCORTED",
        approvalRoute="Laboratory Manager",
        effectiveFrom="2026-09-02",
        effectiveTo="2026-09-30",
        recordStatus="exception",
        recordOwner="Access Control Administrator",
    )
]


def test_a_concept_no_field_and_no_value_holds_is_named_as_unrecorded():
    """Row 3: an orphan verdict was reasoned from the fields that happened to be present."""
    facts = register_facts(
        PERMISSIONS,
        "Which permission groups or zones are orphaned because no current owner, purpose or "
        "mapped opening can be evidenced?",
        TODAY,
        register_label="Access permission",
    )
    absent = _line(facts, ABSENT)
    assert '"orphaned"' in absent and '"purpose"' in absent
    # And the field that DOES exist is named as the way in, so this is not a blanket denial.
    assert '"opening": RECORDED — answer this part from controlsOpening' in facts


def test_the_register_owner_stamp_is_not_offered_as_each_records_owner():
    """`recordOwner` says who keeps the register. The question asked who owns each grant."""
    facts = register_facts(
        PERMISSIONS,
        "Which permission groups are orphaned because no owner can be evidenced?",
        TODAY,
        register_label="Access permission",
    )
    assert "matches only the register's own stamp" in _line(facts, '"owner"')


def test_a_term_the_register_never_uses_is_not_matched_to_the_nearest_record():
    """Row 5: an escorted contractor's one-off permit reported as a 'verified starter'."""
    facts = register_facts(
        PERMISSIONS,
        "Which minimum approved permission package should be prepared for this verified "
        "starter on the authorised effective date?",
        TODAY,
        register_label="Access permission",
    )
    absent = _line(facts, ABSENT)
    for word in ('"starter"', '"package"', '"minimum"'):
        assert word in absent
    assert "never treat a similar-sounding field as the same thing" in absent


# ── the asset engineering register (rows 11, 36, 54, 55) ───────────────────────────────

ASSETS = [
    _row(
        recordId="AEP-001",
        label="Air Handling Unit - Floor 0",
        locationText="Room 0.04 - Mechanical Plant Room",
        onFloor="0",
        designDuty="2.4 m3/s supply at 250 Pa",
        commissionedDuty="2.35 m3/s at 250 Pa",
        criticality="high",
        valueBand="100k-250k",
        isolationPoint="MCC-0 way 3",
        isolationProvenOn="2026-06-16",
        servicesInVoid="Confirmed: chilled water flow and return. Probable: data containment.",
        lastVisited="2026-06-16",
        inspectionIntervalDays="90",
        recordStatus="active",
    ),
    _row(
        recordId="AEP-014",
        label="Sump pump",
        locationText="Room 0.06 - Basement",
        onFloor="0",
        criticality="medium",
        valueBand="10k-50k",
        isolationPoint="Local isolator LI-SP-01",
        lastVisited="2026-08-26",
        inspectionIntervalDays="7",
        recordStatus="active",
    ),
    _row(
        recordId="AEP-016",
        label="Sub-meter - Level 4",
        locationText="Room 4.02 - Riser",
        onFloor="4",
        criticality="medium",
        valueBand="1k-10k",
        isolationProvenOn="2026-04-01",
        lastVisited="2025-10-15",
        inspectionIntervalDays="365",
        recordStatus="active",
    ),
]


def test_a_word_that_appears_only_inside_a_note_is_not_a_recorded_property():
    """Row 11: "assets list probable containment features" — from a note about a ceiling void."""
    facts = register_facts(
        ASSETS,
        "Which water-supply, drainage, containment and isolation details minimise the "
        "consequence of leaks?",
        TODAY,
        register_label="Asset engineering profile",
    )
    text_only = _line(facts, '"containment"')
    assert "AEP-001" in text_only
    # The record carrying the word is NAMED, so it can be quoted rather than only regretted.
    assert "THOSE RECORDS ARE THE ANSWER" in facts
    assert "call one of these words a category the register tracks" in facts
    # isolation IS a field, and saying so is what keeps the answer from a blanket denial.
    assert "isolationPoint" in _line(facts, '"isolation": RECORDED')
    assert '"drainage"' in _line(facts, ABSENT)


def test_a_field_is_not_relabelled_as_the_thing_the_question_asked_for():
    """Row 36: `recordStatus` presented as "Condition", `valueBand` as "Whole-life cost"."""
    facts = register_facts(
        ASSETS,
        "Which assets should receive survey, maintenance, refurbishment or replacement funding "
        "first when criticality, condition, risk and whole-life cost are combined?",
        TODAY,
        register_label="Asset engineering profile",
    )
    absent = _line(facts, ABSENT)
    for word in ('"condition"', '"risk"', '"cost"'):
        assert word in absent
    assert '"criticality": RECORDED — answer this part from criticality' in facts


def test_the_next_due_date_is_arithmetic_the_system_does():
    """Row 54: "last visited 2026-09-16, interval 7 days -> overdue" and "2025-10-15, interval
    365 days -> overdue" — 23 September and 15 October, neither of them past."""
    facts = register_facts(
        ASSETS,
        "Which M&E asset-register records must be reconciled before they can support design, "
        "maintenance or lifecycle decisions?",
        TODAY,
        register_label="Asset engineering profile",
    )
    past = _line(facts, "are PAST it on")
    assert "AEP-014 (due 2026-09-02)" in past
    assert "AEP-016" not in past
    not_due = _line(facts, "NOT yet due")
    assert "AEP-016 on 2026-10-15" in not_due
    assert "A record inside its interval is not overdue" in not_due


def test_an_inspection_interval_is_not_offered_as_a_sampling_rate():
    """Row 55: "Suggested sampling interval (from inspectionIntervalDays) | 90 days"."""
    facts = register_facts(
        ASSETS,
        "Which points and sampling rates should be trended so this commissioning or diagnostic "
        "test can observe the expected behaviour?",
        TODAY,
        register_label="Asset engineering profile",
    )
    absent = _line(facts, ABSENT)
    assert '"sampling"' in absent and '"trended"' in absent


def test_nothing_is_computed_from_an_interval_without_a_date_to_apply_it_to():
    rows = [_row(recordId="X-1", recordStatus="active", inspectionIntervalDays="90")]
    assert "next due date" not in register_facts(rows, "which are overdue?", TODAY)


# ── the handover register (row 34) ─────────────────────────────────────────────────────

HANDOVERS = [
    _row(
        recordId="HO-AHU01-OM",
        label="AHU-01 - roof plant",
        documentKind="O&M manual",
        issuedBy="Meridian Mechanical Ltd",
        recordStatus="held",
    ),
    _row(
        recordId="HO-CHILL-OM",
        label="Chiller - roof plant",
        documentKind="O&M manual",
        issuedBy="Meridian Mechanical Ltd",
        recordStatus="outstanding",
    ),
    _row(
        recordId="HO-SPRINK-OM",
        label="Sprinkler system",
        documentKind="O&M manual",
        issuedBy="Meridian Fire Ltd",
        recordStatus="outstanding",
    ),
]


def test_a_register_about_one_subject_does_not_answer_a_question_about_another():
    """Row 34: "No - the handover evidence is not yet complete for … the event-space handover",
    concluded from a chiller, a generator and a sprinkler."""
    facts = register_facts(
        HANDOVERS,
        "Is the evidence complete enough for organiser and service owners to review "
        "event-space handover?",
        TODAY,
        register_label="Handover record",
    )
    absent = _line(facts, ABSENT)
    assert '"event-space"' in absent and '"evidence"' in absent
    # The status split still answers what IS recorded, so this is a limit, not a refusal.
    assert "outstanding 2" in facts and "held 1 (HO-AHU01-OM)" in facts


# ── the waste collection register (row 19) ─────────────────────────────────────────────

WASTE = [
    _row(
        recordId="WCP-001",
        label="Reception mixed recycling",
        wasteStream="Mixed recycling",
        labelledStream="Mixed recycling",
        apertureKind="Wide opening",
        fillPercent="55",
        approvedFillThreshold="80",
        nextDue="2026-09-19",
        recordStatus="active",
    ),
    _row(
        recordId="WCP-002",
        label="Level 1 mixed recycling",
        wasteStream="Mixed recycling",
        labelledStream="Mixed recycling",
        apertureKind="Wide opening",
        fillPercent="60",
        approvedFillThreshold="80",
        nextDue="2026-09-19",
        recordStatus="active",
    ),
    _row(
        recordId="WCP-003",
        label="Reception paper",
        wasteStream="Paper and card",
        labelledStream="Paper only",
        apertureKind="Narrow slot",
        fillPercent="90",
        approvedFillThreshold="80",
        nextDue="2026-09-19",
        recordStatus="active",
    ),
    _row(
        recordId="WCP-004",
        label="Level 2 paper",
        wasteStream="Paper and card",
        labelledStream="Paper and card",
        apertureKind="Narrow slot",
        fillPercent="30",
        approvedFillThreshold="80",
        nextDue="2026-09-22",
        recordStatus="active",
    ),
    _row(
        recordId="WCP-022",
        label="Event general waste",
        wasteStream="General waste",
        labelledStream="General waste",
        apertureKind="Bulk container",
        fillPercent="10",
        approvedFillThreshold="80",
        nextDue="2026-09-22",
        recordStatus="active",
    ),
    _row(
        recordId="WCP-023",
        label="Laboratory sharps",
        wasteStream="Clinical sharps",
        labelledStream="Clinical sharps",
        apertureKind="Restricted opening",
        fillPercent="55",
        approvedFillThreshold="60",
        nextDue="2026-09-18",
        recordStatus="active",
    ),
]


def test_a_threshold_is_compared_and_never_turned_into_an_instruction():
    """Row 19: "Bins must be at or above the approved fill threshold … WCP-023: fill 55 %
    (threshold 60 %) - below threshold - should be filled" — to a cleaner, about a sharps bin."""
    facts = register_facts(
        WASTE,
        "When is the next authorised waste collection, and what needs to be ready before the "
        "contractor arrives?",
        TODAY,
        register_label="Waste collection point",
    )
    line = _line(facts, "against approvedFillThreshold")
    assert "1 record(s) are AT OR ABOVE their threshold (WCP-003)" in line
    assert "5 are below it" in line
    assert "never turn it into an instruction to anyone" in line


def test_a_register_that_disagrees_with_itself_says_so_instead_of_choosing():
    """The waste register keeps the recorded stream and the labelled stream apart on purpose."""
    facts = register_facts(
        WASTE, "Which bins are labelled correctly?", TODAY, register_label="Waste collection point"
    )
    line = _line(facts, "THE RECORDS DISAGREE WITH EACH OTHER")
    assert "Paper and card" in line and "Paper only" in line and "WCP-003" in line


# ── the accessible route register (rows 26 and 72) ─────────────────────────────────────

ROUTES = [
    _row(
        recordId="RTE-001",
        label="Accessible drop-off to Reception",
        routeFrom="Accessible drop-off - Senghennydd Road north",
        routeTo="Room 0.01 - Main Reception",
        isStepFree="True",
        doorOperation="Automatic",
        recordStatus="open",
    ),
    _row(
        recordId="RTE-004",
        label="Reception to Level 1 Atrium",
        routeFrom="Room 0.01 - Main Reception",
        routeTo="Room 1.04 - Common Area / Atrium",
        isStepFree="True",
        doorOperation="Automatic",
        servedByLift="Lift A",
        liftStatus="in_service",
        recordStatus="open",
    ),
    _row(
        recordId="RTE-005",
        label="Reception to Level 1 Computer Laboratory",
        routeFrom="Room 0.01 - Main Reception",
        routeTo="Room 1.06 - Computer Laboratory",
        isStepFree="True",
        doorOperation="Assisted",
        servedByLift="Lift A",
        liftStatus="in_service",
        recordStatus="open",
    ),
    _row(
        recordId="RTE-007",
        label="Reception to Level 3 laboratories",
        routeFrom="Room 0.01 - Main Reception",
        routeTo="Room 3.01 - Research Laboratory",
        isStepFree="True",
        doorOperation="Assisted",
        servedByLift="Lift A",
        liftStatus="in_service",
        recordStatus="open",
    ),
    _row(
        recordId="RTE-010",
        label="Quiet arrival route",
        routeFrom="Accessible drop-off - Senghennydd Road north",
        routeTo="Room 1.09 - Quiet Room",
        isStepFree="True",
        doorOperation="Automatic",
        servedByLift="Lift B",
        liftStatus="in_service",
        recordStatus="open",
    ),
    _row(
        recordId="RTE-013",
        label="Evacuation route - Level 1 refuge",
        routeFrom="Room 1.04 - Common Area / Atrium",
        routeTo="Fire Exit - Floor 1 North",
        isStepFree="True",
        doorOperation="Assisted",
        recordStatus="open",
    ),
    _row(
        recordId="RTE-016",
        label="Lift B route to Level 3",
        routeFrom="Room 0.01 - Main Reception",
        routeTo="Room 3.06 - Research Laboratory",
        isStepFree="True",
        doorOperation="Assisted",
        servedByLift="Lift B",
        liftStatus="out_of_service",
        recordStatus="closed",
    ),
]


def test_a_universal_claim_is_a_count_and_the_count_is_taken():
    """Row 26: "All of these routes start at a public entrance", over a table whose own rows
    give one starting at a common area and ending at a fire exit."""
    facts = register_facts(
        ROUTES,
        "Which boundary-to-door route is currently evidenced for ambulance crews on foot, "
        "including step-free constraints?",
        TODAY,
        register_label="Accessible route",
    )
    line = _line(facts, "routeFrom (route from) across the records")
    assert 'Room 1.04 - Common Area / Atrium" 1 (RTE-013)' in line
    assert "all of these" in line


def test_one_thing_recorded_in_two_states_is_reported_as_both():
    """Row 72: "RTE-010 | … | Lift B | open" two lines after saying Lift B is out of service."""
    facts = register_facts(
        ROUTES,
        "The lift on my usual route is unavailable. What current step-free alternative is "
        "officially verified?",
        TODAY,
        register_label="Accessible route",
    )
    line = _line(facts, "THE RECORDS DISAGREE WITH EACH OTHER")
    assert 'servedByLift "Lift B"' in line
    assert '"in_service" (RTE-010)' in line and '"out_of_service" (RTE-016)' in line


def test_two_independent_descriptions_are_not_reported_as_a_contradiction():
    """A guard on the rule above: it fired on `powerAccess` and `accessClassification`, two
    unrelated columns sharing the word "access", in a register that contradicts itself nowhere."""
    rows = [
        _row(
            recordId="WS-01",
            powerAccess="at every seat",
            accessClassification="Bookable",
            recordStatus="active",
        ),
        _row(
            recordId="WS-02",
            powerAccess="at every seat",
            accessClassification="Open when not timetabled",
            recordStatus="active",
        ),
    ]
    assert "DISAGREE" not in register_facts(rows, "Which workspaces have power?", TODAY)


# ── the workspace profile register (rows 60, 64, 92) ───────────────────────────────────

WORKSPACES = [
    _row(
        recordId="WS-12",
        label="Seminar room 2.15",
        locationText="Room 2.15 - Seminar Room",
        onFloor="2",
        workspaceKind="bookable room",
        seatCount="20",
        suitableForCalls="True",
        groupFriendly="True",
        openingHours="Mon-Fri 08:00-18:00",
        setupMinutes="8.0",
        recoveryMinutes="26.0",
        recordStatus="active",
    ),
    _row(
        recordId="WS-22",
        label="Meeting room 4.11",
        locationText="Room 4.11 - Meeting Room",
        onFloor="4",
        workspaceKind="bookable room",
        seatCount="8",
        suitableForCalls="True",
        groupFriendly="True",
        openingHours="Mon-Fri 08:00-18:00",
        setupMinutes="5.0",
        recoveryMinutes="17.6",
        recordStatus="active",
    ),
    _row(
        recordId="WS-23",
        label="Meeting room 4.12",
        locationText="Room 4.12 - Meeting Room",
        onFloor="4",
        workspaceKind="bookable room",
        seatCount="8",
        suitableForCalls="True",
        groupFriendly="True",
        openingHours="Mon-Fri 08:00-20:00",
        setupMinutes="5.0",
        recoveryMinutes="17.6",
        recordStatus="active",
    ),
]


def test_the_floor_of_a_record_is_grouped_by_the_system():
    """Rows 60 and 92: "Floor 3 • WS-12 - Seminar room 2.15" and "| 3 | WS-22, WS-23 |", then
    "for the two rooms on floor 3" — for rooms 2.15, 4.11 and 4.12."""
    facts = register_facts(
        WORKSPACES,
        "Which room is suitable for a meeting space for our team?",
        TODAY,
        register_label="Workspace profile",
    )
    line = _line(facts, "By onFloor")
    assert "2: WS-12" in line and "4: WS-22, WS-23" in line
    assert "never a rank, a row number, a seat count or a name" in line


def test_a_column_called_level_that_holds_no_floors_is_not_grouped_as_one():
    """`sensoryLevel` holds "moderate", "busy", "quiet". Grouping an answer by it and calling
    it the record's floor would be a fabrication in the system's own voice."""
    rows = [
        _row(recordId="RTE-001", sensoryLevel="moderate", recordStatus="open"),
        _row(recordId="RTE-002", sensoryLevel="busy", recordStatus="open"),
    ]
    assert "By sensoryLevel" not in register_facts(rows, "Which route, on which floor?", TODAY)


def test_no_contradiction_is_invented_between_a_floor_and_a_room_number():
    """The asset register records the floor a unit SERVES against a plant room on another
    floor — the register working as designed. A cross-check called it a contradiction on six
    records, and a finding that is wrong about a correct register is worse than the defect."""
    facts = register_facts(
        ASSETS,
        "Which asset is on which floor, in which room?",
        TODAY,
        register_label="Asset engineering profile",
    )
    assert "DISAGREE" not in facts
    assert "By onFloor" in facts


def test_a_question_with_no_place_word_gets_no_floor_grouping():
    assert "By onFloor" not in register_facts(
        WORKSPACES, "How many are bookable?", TODAY, register_label="Workspace profile"
    )


def test_no_record_is_claimed_as_the_readers_own():
    """Row 64: "Access and workspace are confirmed for the evening in WS-01", from a room's
    opening hours. Row 63: a role assumed, and an instruction issued to it. Row 90: a day plan
    that decided which three timetabled sessions were the student's."""
    facts = register_facts(
        WORKSPACES,
        "I may need to work here this evening. Are my access, workspace and lone-working "
        "requirements officially confirmed for that period?",
        TODAY,
        register_label="Workspace profile",
    )
    line = _line(facts, "THE QUESTION IS ABOUT THE READER")
    assert "None of the 3 records names the person asking" in line
    assert "do not confirm an entitlement" in line
    absent = _line(facts, ABSENT)
    assert '"evening"' in absent and '"lone-working"' in absent


def test_a_role_column_is_reported_with_its_values_when_one_exists():
    rows = [
        _row(
            recordId="EI-001",
            grantedToRole="Mechanical Technician",
            instructionText="Inspect the damper",
            recordStatus="current",
        ),
        _row(
            recordId="EI-002",
            grantedToRole="Reception staff",
            instructionText="Direct visitors to the assembly point",
            recordStatus="current",
        ),
    ]
    line = _line(
        register_facts(rows, "What is the latest instruction for my location and role?", TODAY),
        "The records are scoped by grantedToRole",
    )
    assert '"Mechanical Technician"' in line and '"Reception staff"' in line
    assert "The question names none of them" in line


def test_a_question_that_is_not_about_the_reader_gets_no_such_line():
    assert "ABOUT THE READER" not in register_facts(
        WORKSPACES, "Which workspaces are bookable?", TODAY, register_label="Workspace profile"
    )


# ── the room booking register (row 78) and the operating regime register (row 113) ─────

BOOKINGS = [
    _row(
        recordId="BK-2026-0005",
        label="BK-2026-0005",
        locationText="Room 5.01 - Seminar Room",
        effectiveFrom="2026-08-30T09:00:00",
        bookedByRole="Graduate School",
        expectedAttendees="12",
        recordStatus="cancelled",
    ),
    _row(
        recordId="BK-2026-0011",
        label="BK-2026-0011",
        locationText="Room 5.01 - Seminar Room",
        effectiveFrom="2026-09-02T14:00:00",
        bookedByRole="Teaching Team",
        expectedAttendees="8",
        recordStatus="cancelled",
    ),
    _row(
        recordId="BK-2026-0001",
        label="BK-2026-0001",
        locationText="Room 5.15 - Meeting Room",
        effectiveFrom="2026-09-04T09:00:00",
        bookedByRole="Industry Liaison",
        expectedAttendees="30",
        recordStatus="confirmed",
    ),
]


def test_a_cancellation_is_not_reported_as_a_no_show():
    """Row 78: "Room 5.01 is the only space with more than one cancelled booking - a clear sign
    of repeated no-shows". A cancellation is a cancellation."""
    facts = register_facts(
        BOOKINGS,
        "Which room and time categories show repeated no-shows strongly enough to justify a "
        "review of release rules?",
        TODAY,
        register_label="Room booking",
    )
    assert '"no-shows"' in _line(facts, ABSENT)
    assert "cancelled 2" in facts and "confirmed 1 (BK-2026-0001)" in facts


REGIMES = [
    _row(
        recordId="REG-001",
        label="AHU regime",
        operatingWindow="Mon-Fri 07:00-19:00",
        recordStatus="active",
    ),
    _row(
        recordId="REG-004",
        label="Parking ventilation regime",
        operatingWindow="continuous",
        recordStatus="degraded",
    ),
    _row(
        recordId="REG-005",
        label="Chilled water regime",
        operatingWindow="Mon-Fri 06:00-20:00",
        recordStatus="degraded",
    ),
]


def test_a_recorded_state_is_not_a_statement_about_what_is_happening_now():
    """Row 113: "two plant items are currently operating outside their normal schedule - they
    are marked as degraded"."""
    facts = register_facts(
        REGIMES,
        "Which plant items are running outside their normal schedule right now?",
        TODAY,
        register_label="Operating regime",
    )
    assert '"schedule"' in _line(facts, ABSENT)
    assert "degraded 2" in facts and "active 1 (REG-001)" in facts


# ── the guards: an honest census must not invent an absence either ─────────────────────


def test_a_word_recorded_as_a_status_value_is_never_called_unrecorded():
    rows = [
        _row(recordId="CP-001", recordStatus="verified"),
        _row(recordId="CP-005", recordStatus="overdue"),
    ]
    facts = register_facts(rows, "Which provisions are overdue?", TODAY)
    assert '"overdue"' not in facts.split(ABSENT)[-1]


def test_a_word_the_register_is_named_for_is_not_reported_as_missing():
    rows = [_row(recordId="CT-001", taskKind="Daily clean", recordStatus="active")]
    facts = register_facts(
        rows, "Which cleaning tasks are open?", TODAY, register_label="Cleaning task"
    )
    assert "cleaning" not in facts.lower().split("what the question names")[-1].split("\n")[0]


def test_half_a_compound_is_not_reported_as_missing_on_its_own():
    """ "whole-life cost" is one idea; announcing that "whole" and "life" are unrecorded is
    noise, and it drowned the finding that "cost" is."""
    facts = register_facts(
        ASSETS, "What is the whole-life cost?", TODAY, register_label="Asset engineering profile"
    )
    absent = _line(facts, ABSENT)
    assert '"whole"' not in absent and '"life"' not in absent


def test_records_that_lack_a_field_are_named_when_the_question_asks_which_lack_it():
    facts = register_facts(
        ASSETS,
        "Which assets have no proven isolation date?",
        TODAY,
        register_label="Asset engineering profile",
    )
    line = _line(facts, "isolationProvenOn (isolation proven on) is NOT recorded on")
    assert "1 of 3 records: AEP-014" in line
    assert "the other 2 DO record it" in line
    assert "UNKNOWN, never satisfactory" in line


def test_a_question_not_about_absence_does_not_list_the_empty_records():
    facts = register_facts(ASSETS, "Where is each isolation point?", TODAY)
    assert "is NOT recorded on" not in facts


# ── the census bounds a claim; it does not veto an answer (measured 2026-09-18) ────────

DEPARTMENTS = [
    _row(
        recordId="DEP-01",
        label="Estates Operations",
        departmentFunction="Runs the building day to day and owns the fabric",
        serviceScope="Building fabric, doors, windows, floors, ceilings, roofs, signage",
        respondsWithinHours="24",
        contactEmail="estates-ops@example.ac.uk",
        contactPhone="029 2087 0001",
        recordStatus="active",
    ),
    _row(
        recordId="DEP-06",
        label="Fire Safety",
        departmentFunction="Maintains fire precautions and evacuation readiness",
        serviceScope="Fire alarm, detection, extinguishers, doors, compartmentation, drills",
        respondsWithinHours="8",
        contactEmail="fire.safety@example.ac.uk",
        contactPhone="029 2087 0006",
        recordStatus="active",
    ),
    _row(
        recordId="DEP-02",
        label="Mechanical and Electrical Maintenance",
        departmentFunction="Maintains plant, HVAC, electrical distribution and controls",
        serviceScope="AHUs, chillers, boilers, pumps, distribution boards, BMS field devices",
        respondsWithinHours="8",
        contactEmail="me-maintenance@example.ac.uk",
        contactPhone="029 2087 0002",
        recordStatus="active",
    ),
]

_DOOR_QUESTION = "Who do I contact about a broken door closer, and how quickly should they respond?"


def test_one_unrecorded_word_does_not_suppress_the_two_recorded_ones():
    """Measured live 2026-09-18, the whole answer: "The records do not record a specific
    department responsible for broken door closers; they do record contactEmail, contactPhone,
    and respondsWithinHours for each department." True, and the register answers the question:
    Estates Operations owns doors in its recorded scope and responds within 24 hours."""
    facts = register_facts(DEPARTMENTS, _DOOR_QUESTION, TODAY, register_label="Department")
    header = _line(facts, "WHAT THE QUESTION NAMES")
    assert "IT IS NOT A REASON TO DECLINE" in header
    assert "Answer from the fields and records named below FIRST" in header
    # The recorded words are an instruction to answer, not a list of what exists.
    assert "RECORDED — answer this part from" in _line(facts, '"contact"')
    assert "RECORDED — answer this part from" in _line(facts, '"respond"')


def test_the_records_carrying_an_unrecorded_word_are_named_not_merely_counted():
    """A count described the one path to the answer and withheld it: the two records whose
    recorded scope covers doors were never named, so they could not be used."""
    facts = register_facts(DEPARTMENTS, _DOOR_QUESTION, TODAY, register_label="Department")
    line = _line(facts, '"door"')
    assert "2 record(s) — DEP-01, DEP-06" in line
    assert "THOSE RECORDS ARE THE ANSWER" in facts
    assert "DEP-02" not in line


def test_every_field_is_given_in_ordinary_words_as_well_as_its_own_name():
    """The handover table's headers are internal names, so the answer read one off and printed
    `contactEmail` and `respondsWithinHours` at a stakeholder."""
    facts = register_facts(DEPARTMENTS, _DOOR_QUESTION, TODAY, register_label="Department")
    assert "contact email, contact phone" in _line(facts, '"contact"')
    assert "responds within hours" in _line(facts, '"respond"')
    assert "The field names above are internal identifiers" in facts


def test_an_unrecorded_word_is_said_to_be_answerable_around():
    rows = [
        _row(
            recordId="DEP-01",
            label="Estates Operations",
            respondsWithinHours="24",
            recordStatus="active",
        ),
        _row(
            recordId="DEP-02",
            label="M and E Maintenance",
            respondsWithinHours="8",
            recordStatus="active",
        ),
    ]
    line = _line(
        register_facts(rows, _DOOR_QUESTION, TODAY, register_label="Department"),
        ABSENT,
    )
    assert '"door"' in line
    assert "DO NOT WRITE A SENTENCE ABOUT IT" in line
    assert "THE QUESTION IS ANSWERED ABOVE, from respond" in line


def test_the_reader_line_says_to_answer_before_it_says_what_not_to_claim():
    """The same shape one level down: three prohibitions and no permission read as a decline."""
    line = _line(
        register_facts(DEPARTMENTS, "Who do I contact, and how fast?", TODAY), "ABOUT THE READER"
    )
    assert line.index("Answer it anyway") < line.index("do not select a record")


def test_an_absence_count_carries_the_records_that_do_hold_the_field():
    rows = list(DEPARTMENTS) + [_row(recordId="DEP-09", label="Portering", recordStatus="reduced")]
    line = _line(
        register_facts(rows, "Which departments have no recorded contact phone?", TODAY),
        "contactPhone (contact phone) is NOT recorded on",
    )
    assert "1 of 4 records: DEP-09" in line
    assert "the other 3 DO record it" in line


# ── run 5: the block is internal, and every group is named (2026-09-18) ────────────────
#
# The census reached the reader verbatim on 23 of 147 answers (0 in four earlier runs), and six
# of the run's eight regressions were "compute something correct, then write a sentence the
# computation contradicts". The rows below are those six.


def test_the_block_says_in_its_first_line_that_it_is_not_for_the_reader():
    """23 answers quoted it. "X: recorded, in fieldName" is a note to whoever is composing the
    answer; it was printed at stakeholders as prose."""
    facts = register_facts(DEPARTMENTS, _DOOR_QUESTION, TODAY, register_label="Department")
    first = facts.splitlines()[0]
    assert "NOT FOR THE READER" in first
    assert "NEVER quote it" in first and "never write one of the field names" in first


def test_every_group_names_its_records_including_the_largest():
    """Row 36: "high — 9 assets" above a table of 8, "medium — 7" above 6, AEP-009 and AEP-014
    in no table at all. The largest group used to be a bare count, so the writer had to work
    out its membership and got it wrong."""
    assets = [
        _row(recordId=f"AEP-{i:03d}", criticality="high", recordStatus="active")
        for i in range(1, 10)
    ] + [
        _row(recordId=f"AEP-{i:03d}", criticality="medium", recordStatus="active")
        for i in range(10, 17)
    ]
    facts = register_facts(assets, "Which assets get funding first by criticality?", TODAY)
    line = _line(facts, "criticality (criticality) across the records")
    assert '"high" 9 (AEP-001, AEP-002' in line and "AEP-009)" in line
    assert '"medium" 7 (AEP-010' in line and "AEP-016)" in line
    assert "EVERY GROUPING BELOW IS A PARTITION" in facts


def test_a_record_may_not_be_placed_under_two_kinds():
    """Row 59: WS-15 and WS-16 under both "Bookable room" and "Computer lab", WS-01 under both
    "Common room" and "Open study" — 31 placements for 28 records."""
    rows = [
        _row(recordId="WS-12", workspaceKind="bookable room", recordStatus="active"),
        _row(recordId="WS-15", workspaceKind="computer lab", recordStatus="active"),
        _row(recordId="WS-16", workspaceKind="computer lab", recordStatus="active"),
        _row(recordId="WS-01", workspaceKind="open study", recordStatus="active"),
    ]
    facts = register_facts(rows, "Which workspace kind is each?", TODAY)
    header = _line(facts, "By workspaceKind (workspace kind)")
    assert "belongs to exactly ONE kind" in header
    assert "listing it under two is an error" in facts
    # Each kind names its own members, so there is nothing left to assign by hand.
    assert "computer lab: active 2 (WS-15, WS-16)" in facts
    assert "open study: active 1 (WS-01)" in facts


def test_a_heading_naming_a_status_may_hold_only_that_status():
    """Row 61: a table headed "Step-free routes that are open" containing RTE-006 (restricted)
    and RTE-016 (closed)."""
    line = _line(
        register_facts(ROUTES, "Which step-free routes are open?", TODAY), "By recorded status"
    )
    assert "open 6 (RTE-001" in line and "closed 1 (RTE-016)" in line
    assert "a heading naming a status may contain only the records listed beside it" in line


def test_an_absence_note_points_at_the_records_that_answer_instead():
    """Rows 111, 45 and 23: "the register does not record whether the building is
    pushchair-friendly from the car park", above its own three step-free routes from the
    drop-off; "no continuity information is available for a communications room", four lines
    under a row reading "secondary comms room"; "the register does not record any open
    actions", over five records the same answer lists as requiring a decision."""
    facts = register_facts(
        ROUTES,
        "Is the building pushchair-friendly from the car park?",
        TODAY,
        register_label="Accessible route",
    )
    note = _line(facts, ABSENT)
    assert '"pushchair-friendly"' in note
    assert "DO NOT WRITE A SENTENCE ABOUT IT" in note
    assert "Never tell the reader something is not recorded when your own answer shows" in note
    # THE NOTE NEVER AUTHORISES A DECLINE. This question names no column at all — nobody
    # writing "pushchair" writes "step free" — and an earlier draft told it to say the
    # register does not cover this and stop, which is row 111 exactly.
    assert "does not cover this, and stop" not in note
    assert "Answer from the counts and lists above" in note


# ── BUG-783: a field every record satisfies cannot say which record is best ────────────

#: The real workspace register's bookable rooms, as the lifter produces them. 18 records, all
#: `suitableForCalls = True`; exactly two recorded `silent`, and the same two the only ones
#: recorded not group-friendly.
BOOKABLE = [
    _row(
        recordId=f"WS-{i:02d}",
        label=f"Meeting room {i}",
        workspaceKind="bookable room",
        accessClassification="Bookable",
        isBookable="True",
        suitableForCalls="True",
        groupFriendly="False" if i in (27, 28) else "True",
        noiseProfile="silent" if i in (27, 28) else "quiet",
        networkRating="adequate" if i in (12, 20, 21) else "strong",
        recordStatus="active",
    )
    for i in (6, 7, 10, 11, 12, 15, 16, 17, 18, 20, 21, 22, 23, 24, 25, 26, 27, 28)
] + [
    _row(
        recordId=f"WS-{i:02d}",
        label=f"Computer lab {i}",
        workspaceKind="computer lab",
        accessClassification="Open when not timetabled",
        isBookable="False",
        suitableForCalls="False",
        groupFriendly="False",
        noiseProfile="quiet",
        networkRating="strong",
        recordStatus="active",
    )
    for i in (2, 3, 4, 5, 8, 9, 13, 14)
]

_CONFIDENTIAL = "Which bookable rooms are suitable for a confidential call?"


def test_a_boolean_true_on_every_record_in_scope_is_not_offered_as_the_answer():
    """Measured live 2026-09-18: "All 18 of those are also marked as suitable for calls
    (calls_ok = true) … Therefore every bookable room in the building is suitable for a call",
    over a table of 18. Nothing fabricated, and nothing separated either."""
    facts = register_facts(BOOKABLE, _CONFIDENTIAL, TODAY, register_label="Workspace profile")
    line = _line(facts, "CANNOT RANK THESE RECORDS")
    assert "the 18 records where" in line
    assert 'suitableForCalls (suitable for calls) is "True" on every one' in line
    assert "a PRECONDITION, not an answer to which is best" in line
    assert "never conclude that every record therefore qualifies" in line


def test_the_fields_that_do_separate_them_are_computed_and_name_their_records():
    """The register records a noise profile on which exactly two of those rooms are silent."""
    facts = register_facts(BOOKABLE, _CONFIDENTIAL, TODAY, register_label="Workspace profile")
    line = _line(facts, "FIELDS THAT DO SEPARATE THEM")
    assert 'noiseProfile (noise profile): "silent" 2 (WS-27, WS-28)' in line
    assert 'groupFriendly (group friendly): "False" 2 (WS-27, WS-28)' in line
    # Smallest distinguished group first, so the two-record splits come before the three.
    assert line.index("WS-27") < line.index("networkRating")
    # And the answer must say which property it ranked on, in ordinary words.
    assert "say in your answer which recorded property you used" in line
    assert "never the field's own name" in line


def test_the_scope_is_what_makes_the_uniformity_visible():
    """`suitableForCalls` is true on 18 of the register's 26 records, which looks
    discriminating. Inside the 18 the question asked about, it separates nothing."""
    facts = register_facts(
        BOOKABLE,
        "Which rooms are suitable for a call?",
        TODAY,
        register_label="Workspace profile",
    )
    # No scope word, so the whole register is in scope and the field is NOT uniform there.
    assert "CANNOT RANK THESE RECORDS" not in facts


def test_a_field_negative_on_every_record_in_scope_is_reported_as_an_absence():
    """The same shape with the boolean the other way up: all eight computer labs record
    group-friendly as false, and "a value shared by all of them is a precondition" is the
    wrong sentence entirely — none of them records it."""
    line = _line(
        register_facts(
            BOOKABLE,
            "Which computer lab is best for a group?",
            TODAY,
            register_label="Workspace profile",
        ),
        "IS NEGATIVE ON EVERY ONE",
    )
    assert 'groupFriendly (group friendly) is "False" on every one' in line
    assert "Say plainly that none of them records it" in line


def test_a_question_that_does_not_ask_which_is_best_gets_no_ranking_lines():
    facts = register_facts(
        BOOKABLE, "Which bookable rooms are there?", TODAY, register_label="Workspace profile"
    )
    assert "CANNOT RANK THESE RECORDS" not in facts
    assert "FIELDS THAT DO SEPARATE THEM" not in facts


def test_rows_without_a_recorded_status_still_produce_nothing():
    assert register_facts([_row(label="x", onFloor="3")], "which floor?", TODAY) == ""
