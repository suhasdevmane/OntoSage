# -*- coding: utf-8 -*-
"""A failed verification withholds the claim instead of annotating it (V12-03, R1, B04/B05).

WHAT WENT WRONG
---------------
``verification["grounded"]`` was read once in the entire orchestrator and decided only
which agent-memory bucket the turn went into. BUG-475's fabricated report -- "no CO2
sensor, install one", about a room recording 77,088 readings a day -- was published
carrying ``grounded=False, confidence=0.20``.

WHAT THESE TESTS PIN
--------------------
Not that a gate exists. That it withholds the right things and, just as importantly,
LEAVES ALONE the things it must not touch. The expensive failure mode in this project is
never "the guard did nothing" -- it is "the guard also took something else with it".
BUG-431's first fix corrected "how many CO2 sensors" and started answering it with the
building-wide total; W0-2's inversion was safe only because seventeen probe cases were
written first, one per escape clause.

So the negative cases outnumber the positive ones here, deliberately.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services import publication_gate as pg  # noqa: E402

FAILED = {"grounded": False, "confidence": 0.20, "source": "sql", "missing": ["co2 sensor"]}
PASSED = {"grounded": True, "confidence": 0.91, "source": "sql", "missing": []}

CLAIM = "The average CO2 in Room 5.01 was 745.3 ppm yesterday, peaking at 1,030 ppm."


# ── the thing it exists to stop ──────────────────────────────────────────────


def test_an_unverified_figure_is_withheld_from_the_text():
    d = pg.evaluate(intent="report", final_response=CLAIM, verification=FAILED)
    assert not d.publish
    assert "745.3" not in d.text and "1,030" not in d.text
    assert "withheld" in d.text.lower()


def test_the_withheld_text_does_not_claim_the_figure_was_wrong():
    """Review p.12: a failed check does not establish that the calculation is false."""
    d = pg.evaluate(intent="report", final_response=CLAIM, verification=FAILED)
    low = d.text.lower()
    assert "not a statement that the figures are wrong" in low
    for forbidden in ("is incorrect", "was wrong", "is false", "fabricated"):
        assert forbidden not in low


def test_it_says_what_would_change_the_outcome():
    """A refusal that knows the remedy and withholds it was already a defect here."""
    d = pg.evaluate(intent="report", final_response=CLAIM, verification=FAILED)
    assert "narrower scope" in d.text.lower()


def test_the_chart_and_the_export_are_withheld_too():
    """B04: a chart of a withheld figure is the same claim with better typography, and a
    spreadsheet outlives the caveat that sat beside it on screen."""
    d = pg.evaluate(
        intent="analytics", final_response=CLAIM, verification=FAILED,
        has_chart=True, has_export=True,
    )
    assert d.withhold_chart and d.withhold_export


def test_a_low_confidence_alone_is_enough():
    """BUG-475 carried BOTH signals and neither was consulted; either must suffice."""
    v = {"grounded": True, "confidence": 0.10, "source": "sql", "missing": []}
    assert not pg.evaluate(intent="trend", final_response=CLAIM, verification=v).publish


# ── the things it must NOT take with it ──────────────────────────────────────


def test_a_verified_answer_is_published_untouched():
    d = pg.evaluate(intent="report", final_response=CLAIM, verification=PASSED)
    assert d.publish and d.text == CLAIM and not d.withheld


def test_an_honest_decline_is_never_gated():
    """Turning "I don't have readings for that room" into "I could not verify" replaces a
    clear answer with a vague one, on precisely the questions handled best."""
    for decline in (
        "I don't have the current CO2 readings for each room, so I can't say which are stuffy.",
        "No — radiation is not measured in this building. There is no point of that kind.",
        "There is no accessible toilet recorded on that floor.",
        "I couldn't verify 9.99 against this building's model just now.",
    ):
        d = pg.evaluate(intent="analytics", final_response=decline, verification=FAILED)
        assert d.publish, f"gated an honest decline: {decline!r}"
        assert d.text == decline


def test_a_curly_apostrophe_does_not_defeat_the_decline_check():
    """The W0 meta-answer guard shipped with exactly this hole: the model wrote a right
    single quotation mark and the pattern expected an apostrophe."""
    curly = "I don’t have the readings for that room."
    assert pg.is_decline(curly)
    assert pg.evaluate(intent="report", final_response=curly, verification=FAILED).publish


def test_an_ungated_lane_is_left_alone():
    """Starts narrow on purpose. floor_plan, capability and the register lanes answer
    structural questions where an unverified NUMBER is not the risk."""
    for intent in ("floor_plan", "capability", "register", "spatial_query", "metadata"):
        d = pg.evaluate(intent=intent, final_response=CLAIM, verification=FAILED)
        assert d.publish, f"gated a lane outside the declared scope: {intent}"


def test_an_identifier_is_not_a_measurement():
    """BUG-191: a grader that counted any digit as a sensor reading scored refusals as PASS
    and manufactured a spurious 39/39. Room 5.01 and floor 3 are names."""
    naming = "Room 5.01 is on floor 3, next to zone 3Z01, and is served by AHU_F5."
    assert not pg.has_quantitative_claim(naming)
    assert pg.evaluate(intent="report", final_response=naming, verification=FAILED).publish


def test_a_missing_verification_record_is_not_a_failed_one():
    """The check not running is a different fact from the check failing (V12-19 types it)."""
    for v in (None, {}):
        assert pg.evaluate(intent="report", final_response=CLAIM, verification=v).publish


def test_a_malformed_confidence_does_not_withhold_everything():
    """Fails open: a verifier outage must not become a system-wide outage."""
    v = {"grounded": True, "confidence": "not-a-number", "source": "sql"}
    assert pg.evaluate(intent="report", final_response=CLAIM, verification=v).publish


# ── the record ───────────────────────────────────────────────────────────────


def test_the_decision_records_which_check_failed():
    """An operator has to be able to tell WHY without re-running the turn."""
    d = pg.evaluate(intent="compare", final_response=CLAIM, verification=FAILED)
    assert "grounded=False" in d.checks_failed
    assert any(c.startswith("confidence=") for c in d.checks_failed)
    assert d.reason


# ── the step nobody remembers ────────────────────────────────────────────────


def test_the_gate_is_actually_CALLED_on_the_response_path():
    """A lane once routed correctly, computed the right answer, and the user saw
    "I processed your request, but couldn't generate a response." Adding a thing is three
    steps and the third -- being collected -- is the one that gets missed (V6-T10).

    A module with thirteen passing tests that nothing calls is that failure exactly.
    """
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "orchestrator" / "workflow" / "_orchestrator.py"
    body = src.read_text(encoding="utf-8")
    assert "from orchestrator.services.publication_gate import evaluate" in body, (
        "the publication gate is not imported on the response path"
    )
    assert "_pub_evaluate(" in body, "the publication gate is imported but never called"

    call_at = body.index("_pub_evaluate(")
    append_at = body.index('role="assistant"')
    assert call_at < append_at, (
        "the gate must run BEFORE the answer is appended to the transcript"
    )

    # It must also run after the guards that REWRITE final_response, or it would be
    # judging a string the user never receives.
    absence_at = body.index("absence guard skipped")
    assert absence_at < call_at, "the gate must run after the rewriting guards"


def test_a_withheld_turn_leaves_an_auditable_record():
    """An operator must be able to see that something was withheld, and why, without
    re-running the turn. The incident this prevents was invisible because the failing
    signal was never surfaced anywhere."""
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "orchestrator" / "workflow" / "_orchestrator.py"
    body = src.read_text(encoding="utf-8")
    assert '"publication_decision"' in body, "the decision is not recorded on the bus"
    assert "[publication_gate] WITHHELD" in body, "a withheld answer must be logged loudly"


# ── "not my lane" is not "unsupported" (BUG-508) ─────────────────────────────


def test_a_lane_the_verifier_cannot_assess_is_never_gated():
    """The verifier reads four buses and reports grounded=False for every lane whose
    evidence lives elsewhere. Gating on that withholds every register, floor-plan and
    deliberation answer in the system.

    Caught live: the first deployment withheld a REPORT with 1,000 real rows behind it.
    """
    blind = {"grounded": False, "confidence": 0.20, "source": "none",
             "missing": [], "applicable": False}
    d = pg.evaluate(intent="report", final_response=CLAIM, verification=blind)
    assert d.publish, "an unassessed lane must not be treated as an unsupported one"


def test_an_assessed_lane_that_fails_is_still_gated():
    """The exemption above must not become a way for a real failure to escape."""
    assessed = {"grounded": False, "confidence": 0.20, "source": "sql",
                "missing": ["co2 sensor"], "applicable": True}
    assert not pg.evaluate(intent="report", final_response=CLAIM,
                           verification=assessed).publish


def test_the_verifier_counts_sql_rows_at_the_depth_the_lane_writes_them():
    """BUG-508. `_count_sql_rows` read sql_result["data"]; the sql node writes
    ["results"]["data"]. It returned 0 for every real result, which is how BUG-475's
    report carried sql_rows=0 beside a log line reading "Query returned 1000 rows"."""
    from orchestrator.agents.verifier_agent import _count_sql_rows

    rows = [{"v": 1}, {"v": 2}, {"v": 3}]
    assert _count_sql_rows({"results": {"data": rows}}) == 3, "the shape the lane produces"
    assert _count_sql_rows({"data": rows}) == 3, "the unwrapped shape callers/tests pass"
    assert _count_sql_rows({"results": rows}) == 3, "a bare list under results"
    assert _count_sql_rows({}) == 0 and _count_sql_rows(None) == 0


def test_the_verifier_declares_which_lanes_it_can_assess():
    from orchestrator.agents.verifier_agent import _ASSESSABLE_INTENTS

    for covered in ("sensor_data", "analytics", "compare", "trend"):
        assert covered in _ASSESSABLE_INTENTS
    for not_covered in ("floor_plan", "register", "events", "deliberate", "asset_state"):
        assert not_covered not in _ASSESSABLE_INTENTS, (
            f"{not_covered} answers from a bus the verifier never opens; "
            "claiming to assess it would resurrect BUG-508"
        )


def test_planner_routed_lanes_are_not_claimed_as_assessable(tmp_path):
    """report and export must stay OUT until BUG-509 is fixed.

    This test asserted the opposite when it was written, on the assumption that the
    verifier could see a report's rows. Measurement refuted it: PlannerAgent._execute_step
    writes sparql_result, sql_result and report_result into a LOCAL context that is never
    merged into state.intermediate_results, so a report turn verifies as
    `sensors=0, sql_rows=0, report_rows=0` beside adapter logs showing dozens of successful
    queries.

    Putting them back without fixing the merge re-breaks every report -- the gate withholds
    a good answer because "no evidence visible" is read as "no evidence exists". So the
    assertion carries its own reason, and the fix that lets it be reversed is named.
    """
    from orchestrator.agents.verifier_agent import _ASSESSABLE_INTENTS

    for planner_routed in ("report", "export"):
        assert planner_routed not in _ASSESSABLE_INTENTS, (
            f"{planner_routed} routes via the planner, whose results never reach the bus "
            "(BUG-509). Re-add it only once _planner_node merges the planner's context "
            "into state.intermediate_results -- that is V12-14."
        )

    # And the reason must be documented where the next reader will find it.
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "orchestrator" / "agents" / "verifier_agent.py"
    body = src.read_text(encoding="utf-8")
    assert "BUG-509" in body, "the exclusion must say why, or it reads as an oversight"
