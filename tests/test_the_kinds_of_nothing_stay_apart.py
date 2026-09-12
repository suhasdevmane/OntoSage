# -*- coding: utf-8 -*-
"""Absence, failure and refusal are different facts (V12-05, R3/T04, cases A03-A06).

    "Absence in a graph, absence in a time window, failed retrieval and forbidden access
     are different facts."   — architecture review, p. 8

THE INCIDENT THESE PIN
----------------------
BUG-475. Room 5.01 has a CO2 sensor and records about 77,088 readings a day. Its
`ref:storedAt` reference was missing, so the fetch returned nothing, and the report said:

    "No CO2 sensor was active or present in Room 5.01" … "a critical monitoring gap"
    … "deploy a secondary CO2 device"

A retrieval failure narrated as physical absence, ending in a recommendation to install
equipment that was already installed. Two point repairs followed (BUG-475, BUG-487); the
review's judgement is that the distinction is systemic, which is what this module is.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.retrieval_outcome import (  # noqa: E402
    RetrievalOutcome,
    SeriesResolution,
    classify,
    describe,
)


# ── A03: a removed reference is never physical absence ───────────────────────


def test_a_missing_reference_is_not_a_missing_sensor():
    r = classify(declared=True, has_reference=False, subject="the CO2 sensor in Room 5.01")
    assert r.outcome is RetrievalOutcome.REFERENCE_MISSING
    assert not r.is_absence_of_data
    assert "NOT telling you the sensor is absent" in r.external


def test_a_missing_reference_can_never_recommend_installing_one():
    """The exact sentence BUG-475 produced, made unreachable."""
    r = classify(declared=True, has_reference=False, subject="a CO2 sensor")
    assert not r.may_recommend_installation


def test_only_an_undeclared_sensor_may_suggest_installation():
    assert classify(declared=False, subject="a radon sensor").may_recommend_installation
    for kwargs in (
        {"declared": True, "has_reference": False},
        {"declared": True, "store_registered": False},
        {"declared": True, "backend_reachable": False},
        {"declared": True, "series": SeriesResolution.CONFIRMED},
        {"declared": True, "series": SeriesResolution.UNKNOWN},
        {"declared": True, "access_permitted": False},
    ):
        assert not classify(subject="x", **kwargs).may_recommend_installation, kwargs


# ── A04: an unregistered store names its cause and substitutes nothing ───────


def test_an_unregistered_store_is_a_named_configuration_failure():
    r = classify(declared=True, store_registered=False, subject="the lift vibration sensor")
    assert r.outcome is RetrievalOutcome.BACKEND_UNAVAILABLE
    assert "not registered" in r.internal
    assert "no substitute backend" in r.internal
    assert not r.is_absence_of_data


# ── A05 / A06: the C08 qualification — unknown is a verdict ──────────────────


def test_zero_rows_with_an_unresolved_series_does_not_claim_absence():
    """Review C08: an empty result does not establish that a series is missing. Without a
    catalogue the store cannot tell a broken identifier from a quiet period."""
    r = classify(declared=True, series=SeriesResolution.UNKNOWN, rows=0, subject="that sensor")
    assert r.outcome is RetrievalOutcome.SERIES_UNRESOLVED
    assert not r.is_absence_of_data
    assert "will not guess" in r.external


def test_zero_rows_with_a_confirmed_series_is_a_genuinely_empty_window():
    """The one case where "nothing was recorded" is a fact about the building."""
    r = classify(declared=True, series=SeriesResolution.CONFIRMED, rows=0, subject="Room 5.01")
    assert r.outcome is RetrievalOutcome.NO_OBSERVATIONS
    assert r.is_absence_of_data
    assert "connected and working" in r.external


def test_the_two_empty_cases_do_not_share_wording():
    """If they read the same, the taxonomy has achieved nothing."""
    unknown = classify(declared=True, series=SeriesResolution.UNKNOWN, rows=0, subject="X")
    confirmed = classify(declared=True, series=SeriesResolution.CONFIRMED, rows=0, subject="X")
    assert unknown.external != confirmed.external


# ── precedence: an earlier failure is not overruled by a later fact ──────────


def test_an_unreachable_store_says_nothing_about_rows():
    """A store that was never reached cannot establish that a period was empty."""
    r = classify(
        declared=True, backend_reachable=False,
        series=SeriesResolution.CONFIRMED, rows=0, subject="X",
    )
    assert r.outcome is RetrievalOutcome.BACKEND_UNAVAILABLE


def test_policy_beats_everything():
    """A refusal must not leak that the thing exists, or that it has no data."""
    r = classify(
        declared=True, has_reference=False, access_permitted=False, subject="that room",
    )
    assert r.outcome is RetrievalOutcome.ACCESS_RESTRICTED
    assert "incomplete" not in r.external and "absent" not in r.external


def test_an_undeclared_sensor_beats_a_missing_reference():
    r = classify(declared=False, has_reference=False, subject="X")
    assert r.outcome is RetrievalOutcome.NOT_DECLARED


# ── every state is distinct, worded, and remediable ─────────────────────────


def test_all_seven_states_exist_and_none_shares_wording():
    """The acceptance is "seven internal states with authorised external wording each"."""
    assert len(list(RetrievalOutcome)) == 7
    seen = {}
    for kwargs in (
        {"declared": False},
        {"declared": True, "has_reference": False},
        {"declared": True, "series": SeriesResolution.UNKNOWN},
        {"declared": True, "backend_reachable": False},
        {"declared": True, "series": SeriesResolution.CONFIRMED},
        {"declared": True, "rows": 5, "quality_ok": False},
        {"declared": True, "access_permitted": False},
    ):
        r = classify(subject="the thing", **kwargs)
        assert r.external, r.outcome
        assert r.external not in seen, (
            f"{r.outcome} shares wording with {seen.get(r.external)} — the distinction "
            "exists internally and vanishes for the reader"
        )
        seen[r.external] = r.outcome
    assert len(seen) == 7, f"only {len(seen)} distinct wordings for 7 states"


def test_every_state_that_can_be_remedied_says_how():
    """A refusal that knows the remedy and withholds it was already a defect here."""
    for kwargs in (
        {"declared": False},
        {"declared": True, "has_reference": False},
        {"declared": True, "series": SeriesResolution.UNKNOWN},
        {"declared": True, "backend_reachable": False},
        {"declared": True, "series": SeriesResolution.CONFIRMED},
    ):
        r = classify(subject="X", **kwargs)
        assert r.remedy, f"{r.outcome} offers no way forward"
        assert r.remedy in describe(r)


def test_a_restricted_answer_offers_no_remedy_on_purpose():
    """Telling someone how to get around a policy is not a remedy."""
    assert classify(declared=True, access_permitted=False, subject="X").remedy == ""


def test_the_subject_is_the_only_thing_interpolated():
    """A wording that absorbs arbitrary text is one that can absorb a fabrication."""
    r = classify(declared=False, subject="a radon sensor")
    assert "a radon sensor" in r.external
    assert "{" not in r.external and "}" not in r.external


def test_a_usable_result_is_a_programming_error_not_an_outcome():
    """This classifier describes a retrieval that produced nothing. Handing it good rows
    means the caller has confused "no answer" with "an answer"."""
    with pytest.raises(ValueError):
        classify(declared=True, rows=10, quality_ok=True, subject="X")


# ── the step nobody remembers: is it CALLED? ─────────────────────────────────


def _report_no_data(sensor_count: int) -> str:
    from orchestrator.agents.report_agent import ReportAgent

    return ReportAgent._no_data_narrative(
        "q", {"overview": {"sensor_count": sensor_count, "data_points": 0}}
    )


def test_the_report_lane_classifies_instead_of_narrating_generically():
    """A module with fifteen passing tests that nothing calls is the V6-T10 failure.

    BUG-475's room had sensors identified and zero rows — the SERIES_UNRESOLVED case — so
    the report must say absence was not established, not that nothing is there.
    """
    with_sensors = _report_no_data(3)
    assert "will not guess" in with_sensors, "the lane did not classify the empty result"
    assert "3 sensor(s) were identified" in with_sensors

    none_declared = _report_no_data(0)
    assert with_sensors != none_declared, (
        "the two kinds of nothing still read identically in a report"
    )


def test_the_report_lane_still_refuses_to_blame_the_building():
    """The original guarantee must survive the added specificity."""
    for count in (0, 3):
        text = _report_no_data(count).lower()
        for claim in ("monitoring gap", "system failure", "sensor malfunction",
                      "deploy a secondary", "data void"):
            assert claim not in text, f"{claim!r} came back for sensor_count={count}"


def test_a_report_with_sensors_but_no_rows_never_recommends_installing_one():
    """The BUG-475 sentence, made unreachable in the lane that produced it."""
    assert "install" not in _report_no_data(3).lower()
