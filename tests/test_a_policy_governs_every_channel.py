# -*- coding: utf-8 -*-
"""V12-17 — a refusal applies to the chart, the export and the dossier too (review B11).

    "An unauthorised room, a restricted occupancy detail and a derived sensitive output are
     each refused before disclosure, checked in text, chart, dossier AND export, with
     identities whose permitted scopes differ. The grader must not count a digit inside a
     building id as a reading."

WHAT B11 IS ABOUT
-----------------
Not whether the decision is made — BUG-195 was the missing decision point and the PDP now
has four chokepoints (sparql, sql, deliberate, events). This is about what happens AFTER a
decision is made: a policy applied to the prose and not to the chart has not been applied,
because a chart of restricted rows IS the restricted rows, and an export outlives every
caveat that sat beside it on screen.

THE DESIGN POINT THESE TESTS PIN HARDEST
-----------------------------------------
`publication_gate` and `disclosure_gate` sit at the same chokepoint and FAIL IN OPPOSITE
DIRECTIONS, on purpose. A verification gate that could not read its inputs must publish —
otherwise a verifier outage becomes a total outage. A disclosure gate that could not read
its inputs must withhold — because publishing is the irreversible half. Merging them, or
adding a `fail_open=` switch, would put one flag between correct and catastrophic; several
tests below exist only to make that merge fail loudly.

IDENTITY
--------
Nothing in the gate reads a role. It propagates the verdict the PDP returned FOR THIS
TURN'S IDENTITY, so two identities diverge because their VERDICTS differed. That is what
makes the >1-identity case meaningful rather than a restatement of the single-identity one.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services import disclosure_gate  # noqa: E402
from orchestrator.services.disclosure_gate import (  # noqa: E402
    DERIVED_KEYS,
    LANE_RESULT_KEYS,
    evaluate,
    note,
)

POLICY = "bldg:OccupancyDetailPolicy"


def _refused_bus(lane="sql_result", **extra):
    """A turn where `lane` was refused by the PDP and everything else was computed."""
    bus = {
        lane: {
            "success": False,
            "denied_by_policy": POLICY,
            "lane": lane.replace("_result", ""),
            "formatted_response": "I can't share per-desk occupancy for that room.",
            "results": {"data": []},
        },
        "visualization_path": "/exports/chart_1.png",
        "export_result": {"download_url": "/exports/rows.csv", "rows": 1000},
        "evidence_dossier": {"ranked": [{"space": "Room 5.01", "score": 0.54}]},
        "evidence_record": {"sources": ["sensor-a"]},
    }
    bus.update(extra)
    return bus


def _allowed_bus():
    return {
        "sql_result": {"success": True, "results": {"data": [{"value": 812.0}]}},
        "visualization_path": "/exports/chart_1.png",
        "export_result": {"download_url": "/exports/rows.csv"},
        "evidence_dossier": {"ranked": []},
    }


# ── every channel, not just the prose ────────────────────────────────────────


def test_a_refused_lane_withholds_the_chart_the_export_and_the_dossier():
    d = evaluate(_refused_bus())
    assert d.refused is True
    assert set(d.withhold) == {
        "visualization_path",
        "export_result",
        "evidence_dossier",
        "evidence_record",
    }


def test_the_refusal_text_itself_is_never_withheld():
    """The lane's refusal message IS the answer. Blanking it would replace a clear
    explanation with silence, which reads as a crash and gets re-asked rather than
    re-phrased."""
    d = evaluate(_refused_bus())
    assert "formatted_response" not in d.withhold
    assert not any(k.endswith("_result") and k in LANE_RESULT_KEYS for k in d.withhold)


@pytest.mark.parametrize("lane", LANE_RESULT_KEYS)
def test_a_refusal_on_any_lane_propagates(lane):
    """Seven lanes can refuse. A propagation wired to one of them protects one question
    shape and leaves the other six exactly as they were."""
    assert evaluate(_refused_bus(lane)).refused is True


def test_nothing_is_withheld_when_no_policy_refused():
    d = evaluate(_allowed_bus())
    assert d.refused is False
    assert d.withhold == []
    assert d.any_withheld is False


def test_only_surfaces_that_exist_are_named_as_withheld():
    """Listing a chart that was never produced would tell a user something was taken away
    from them that never existed."""
    d = evaluate({"sql_result": {"denied_by_policy": POLICY}, "export_result": {"url": "x"}})
    assert d.withhold == ["export_result"]


# ── the failure DIRECTION, which is the whole reason this is its own module ──


def test_a_bus_it_cannot_read_withholds_everything():
    """FAIL CLOSED. If it cannot tell whether a refusal applies, publishing is the
    irreversible outcome."""
    d = evaluate("not a dict at all")  # type: ignore[arg-type]
    assert d.refused is True
    assert set(d.withhold) == set(DERIVED_KEYS)
    assert "cannot be shown that no policy refusal applies" in d.reason


def test_an_absent_bus_is_not_treated_as_a_refusal():
    """Nothing computed is not the same as something refused, and withholding surfaces that
    do not exist would put a policy caveat on every turn that produced no data."""
    d = evaluate(None)
    assert d.refused is False and d.withhold == []


def test_the_two_gates_fail_in_opposite_directions_and_say_so():
    """If someone merges these modules, this is the test that should stop them."""
    import inspect

    from orchestrator.services import publication_gate

    disclosure_src = inspect.getsource(disclosure_gate)
    publication_src = inspect.getsource(publication_gate)
    assert "fails CLOSED" in disclosure_src or "FAIL CLOSED" in disclosure_src
    assert "OPEN" in publication_src
    assert "publication_gate" in disclosure_src, (
        "the disclosure gate does not explain why it is not the publication gate"
    )


def test_the_marker_is_structural_not_a_text_match():
    """BUG-191's lesson. Its grader counted the "2" inside `bldg2` as a sensor reading, so
    refusals scored PASS and a run reported a spurious 39/39. A gate guessing a refusal
    from wording would make the same class of mistake with worse consequences."""
    prose_only = {
        "sql_result": {
            "success": True,
            "formatted_response": "I cannot share that. Policy denied. Access restricted.",
            "results": {"data": [{"value": 812.0}]},
        },
        "export_result": {"url": "x"},
    }
    assert evaluate(prose_only).refused is False, "a refusal was inferred from prose"


def test_a_blank_policy_iri_is_not_a_refusal():
    bus = {"sql_result": {"success": False, "denied_by_policy": "", "results": {}}}
    assert evaluate(bus).refused is False


# ── more than one identity ───────────────────────────────────────────────────


def test_two_identities_diverge_because_their_verdicts_differ():
    """The same question, two accounts, two correct answers.

    The gate reads no role. The facility manager's turn carries no refusal and keeps its
    chart; the visitor's turn carries one and loses it. Divergence comes from the PDP, and
    this module only carries it to the other channels.
    """
    manager_turn = _allowed_bus()
    visitor_turn = _refused_bus()

    assert evaluate(manager_turn).any_withheld is False
    assert evaluate(visitor_turn).any_withheld is True


def test_the_gate_reads_no_role_of_its_own():
    """A disclosure gate with its own opinion about roles is a second policy engine, and
    two policy engines disagree the first time one is edited."""
    import inspect

    src = inspect.getsource(disclosure_gate)
    for forbidden in ("user_role", "admin", "facility_manager", "readonly", "visitor"):
        assert forbidden not in src.replace("# ", "").split('"""')[-1], (
            f"{forbidden} appears in the gate's logic — it is deciding, not propagating"
        )


# ── what the user is told ────────────────────────────────────────────────────


def test_a_withheld_chart_is_stated_not_silently_missing():
    """A chart that silently does not appear reads as a bug, and a user who thinks the
    system is broken asks again rather than asking differently."""
    text = note(evaluate(_refused_bus()))
    assert "withheld" in text
    assert "every form this answer could take" in text


def test_nothing_is_said_when_nothing_was_withheld():
    assert note(evaluate(_allowed_bus())) == ""


def test_a_single_withheld_surface_reads_as_singular():
    d = evaluate({"sql_result": {"denied_by_policy": POLICY}, "export_result": {"u": 1}})
    assert "was withheld" in note(d) and "were withheld" not in note(d)


# ── the step nobody remembers ────────────────────────────────────────────────


def test_the_gate_runs_on_the_response_path_before_the_answer_is_transcribed():
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent / "orchestrator/workflow/_orchestrator.py"
    ).read_text(encoding="utf-8")
    assert "disclosure_gate" in src, "the disclosure gate is never consulted"

    call_at = src.index("_disclose.evaluate")
    append_at = src.index('role="assistant"')
    assert call_at < append_at, "the gate runs after the answer was already transcribed"


def test_it_runs_before_the_publication_gate():
    """Order matters: the publication gate rewrites `final_response` wholesale on a
    withheld answer. Running the disclosure note after that would append a policy caveat to
    a verification message about a different problem."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent / "orchestrator/workflow/_orchestrator.py"
    ).read_text(encoding="utf-8")
    assert src.index("_disclose.evaluate") < src.index("_pub_evaluate(")


def test_the_decision_does_not_survive_into_the_next_turn():
    """A stale decision would attribute this turn's answer to a policy refusal that
    governed the previous question AND a different identity."""
    from orchestrator.workflow._orchestrator import _PER_TURN_LANE_KEYS

    assert "disclosure_decision" in _PER_TURN_LANE_KEYS
    assert "evidence_dossier" in _PER_TURN_LANE_KEYS


def test_the_pdp_still_has_its_chokepoints():
    """This module propagates; it does not decide. If the consults disappeared there would
    be no verdict to propagate and every one of the tests above would still pass."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent / "orchestrator/workflow/_orchestrator.py"
    ).read_text(encoding="utf-8")
    assert src.count("_protect.consult(") >= 4, (
        "fewer PDP chokepoints than the four this system is documented to have"
    )
