# -*- coding: utf-8 -*-
"""The deliberative plan trace described the code, not the request (V10 W4-1).

`build_plan_trace` returned this list for every deliberative answer, unconditionally:

    ["compile_cqir", "admission_gate", "enumerate_candidates",
     "fetch_aggregate", "score", "dossier_guard"]

Two of those stages are CONDITIONAL — `plan_executor` times `events_ms` only when event
checks apply and `forecast_ms` only when the top-K are forecast — and neither appeared in
the list at all, so a run that forecast was indistinguishable from one that did not.

The trace sits in the response beside `plan_hash` and `plan_fingerprint`, which are real
evidence (BUG-184 turned on telling those two apart). A constant list next to them borrows
their credibility and returns nothing: it cannot answer "what did this request actually
do?", which is the only question a trace exists for.

Now derived from `timings_ms`, which the executor writes per stage as it runs. The two
pre-executor stages stay unconditional because the dossier is BUILT from their output —
there is no dossier without a compiled CQ-IR that passed admission — and `dossier_guard`
is appended because the dict being read is itself the dossier.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit

from orchestrator.workflow._orchestrator import (  # noqa: E402
    _deliberative_steps,
    build_plan_trace,
)


def _dossier(**timings):
    return {
        "plan_hash": "h",
        "plan_fingerprint": "fp",
        "timings_ms": dict(timings),
    }


def test_a_plain_run_reports_the_stages_it_used():
    steps = _deliberative_steps(_dossier(enumerate_ms=12, fetch_ms=40, score_ms=3))
    assert steps == [
        "compile_cqir",
        "admission_gate",
        "enumerate_candidates",
        "fetch_aggregate",
        "score",
        "dossier_guard",
    ]


def test_a_forecasting_run_says_so():
    """The old list could not distinguish this from the one above."""
    steps = _deliberative_steps(_dossier(enumerate_ms=12, fetch_ms=40, forecast_ms=900, score_ms=3))
    assert "forecast" in steps
    assert steps.index("forecast") == steps.index("score") - 1


def test_an_event_checking_run_says_so():
    steps = _deliberative_steps(_dossier(enumerate_ms=9, events_ms=15, fetch_ms=30, score_ms=2))
    assert "check_events" in steps
    assert steps.index("check_events") < steps.index("fetch_aggregate")


def test_a_run_that_never_reached_the_executor_does_not_claim_it_scored():
    """A plan parked at the admission gate used to report 'score' as done."""
    steps = _deliberative_steps(_dossier())
    assert steps == ["compile_cqir", "admission_gate", "dossier_guard"]
    assert "score" not in steps and "fetch_aggregate" not in steps


def test_the_order_is_execution_order_not_dict_order():
    """Timings arrive in whatever order the executor happened to write them."""
    scrambled = _dossier(score_ms=3, enumerate_ms=1, forecast_ms=2, fetch_ms=4, events_ms=5)
    steps = _deliberative_steps(scrambled)
    assert steps == [
        "compile_cqir",
        "admission_gate",
        "enumerate_candidates",
        "check_events",
        "fetch_aggregate",
        "forecast",
        "score",
        "dossier_guard",
    ]


def test_a_dossier_with_no_timings_key_at_all_does_not_raise():
    """Older serialised dossiers exist; a trace must degrade, not explode."""
    assert _deliberative_steps({"plan_hash": "h"}) == [
        "compile_cqir",
        "admission_gate",
        "dossier_guard",
    ]


# ── the trace as the response carries it ────────────────────────────────────


def test_the_deliberative_trace_keeps_both_hashes():
    """`plan_hash` is provenance; `plan_fingerprint` is the determinism anchor (BUG-184)."""
    trace = build_plan_trace({"evidence_dossier": _dossier(enumerate_ms=1, fetch_ms=2, score_ms=3)})
    assert trace["kind"] == "deliberative"
    assert trace["plan_hash"] == "h" and trace["plan_fingerprint"] == "fp"


def test_a_reflex_answer_is_still_a_reflex_answer():
    """The change must not reclassify every non-deliberative turn."""
    trace = build_plan_trace({"route_decision": {"final_node": "sparql"}}, ["sparql", "sql"])
    assert trace["kind"] == "reflex"
    assert trace["steps"] == ["sparql", "sql"]


def test_the_steps_are_no_longer_a_literal_in_the_trace_builder():
    """The list moved out; it must not quietly move back in."""
    src = inspect.getsource(build_plan_trace)
    assert '"enumerate_candidates"' not in src, (
        "the hardcoded stage list is back inside build_plan_trace, so the trace describes "
        "the code again instead of the request"
    )
    assert "_deliberative_steps(dossier)" in src


def test_the_stage_table_matches_the_keys_the_executor_writes():
    """A rename in plan_executor would silently drop a stage from every trace."""
    from pathlib import Path

    from orchestrator.workflow._orchestrator import _DELIBERATIVE_STAGES

    src = Path("orchestrator/services/deliberation/plan_executor.py").read_text(encoding="utf-8")
    for _name, key in _DELIBERATIVE_STAGES:
        if key is None:
            continue
        assert f'timings["{key}"]' in src, (
            f"the trace watches for {key!r}, which plan_executor no longer records — that "
            f"stage would vanish from every plan trace without a test failing anywhere else"
        )


# ── the lane is described where the reference claims to be complete ─────────
#
# ONTOSAGE.md is "the complete technical reference" and contained ZERO mentions of
# ARBITER, CQ-IR or the dossier — while the lane answers the project's most-cited example
# question. V4-T26 was marked done. An undocumented lane is one nobody can review, and the
# next person to touch it has only the source.


def test_the_reference_describes_the_deliberation_lane():
    from pathlib import Path

    doc = Path("ONTOSAGE.md").read_text(encoding="utf-8")
    for term in ("ARBITER", "CQ-IR", "dossier", "plan_fingerprint", "SATURATE"):
        assert term in doc, f"ONTOSAGE.md no longer mentions {term!r}"


def test_the_reference_states_the_design_claim_not_just_the_parts():
    """A parts list is not a description. The claim is what makes the lane worth having."""
    from pathlib import Path

    doc = Path("ONTOSAGE.md").read_text(encoding="utf-8")
    assert "only generative role" in doc or "ONLY NEURAL STEP" in doc


def test_the_reference_distinguishes_the_two_hashes():
    """Confusing them is BUG-184 and cost a benchmark its conclusion.

    Whitespace-normalised: prose wraps, and "determinism anchor" straddled a line break.
    """
    import re
    from pathlib import Path

    doc = re.sub(r"\s+", " ", Path("ONTOSAGE.md").read_text(encoding="utf-8"))
    i = doc.index("plan_fingerprint` vs `plan_hash")
    window = doc[i : i + 900]
    assert "determinism anchor" in window
    assert "excludes currently-busy rooms" in window, (
        "the reference no longer says WHY plan_hash differs between runs, which is the "
        "half that made BUG-184 look like non-determinism"
    )


def test_the_gating_env_var_is_documented():
    from pathlib import Path

    assert "DELIBERATE_CLARIFY_OFF" in Path("ONTOSAGE.md").read_text(encoding="utf-8")
    assert "DELIBERATE_CLARIFY_OFF" in Path(".env.example").read_text(encoding="utf-8")
