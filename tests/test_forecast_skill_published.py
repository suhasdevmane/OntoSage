# -*- coding: utf-8 -*-
"""Measured forecast skill, published and read back (CAVEAT-324, 2026-08-27).

``ontosage:ForecastSkill`` declared backtestMAE, backtestMAPE, ciCoverage80 and
horizonHours, and the schema said what they were for: "Cited in every forecast
answer; makes 'how good are your forecasts?' SPARQL-answerable."

Half was already true -- the forecast agent cites measured skill from the grader's
JSON registry. The other half was not: nothing wrote the numbers into the graph and
nothing read them back, so asking how accurate the forecasts are got no answer.

The numbers are TRANSCRIBED, never computed here. A modality nobody backtested gets
no triple and is reported as unmeasured, because inventing a plausible MAE is
exactly the fabrication the evidence discipline exists to prevent.
"""

import pytest

from orchestrator.services.forecast_skill import (
    NOMINAL_COVERAGE_80,
    SkillRecord,
    format_skill,
    is_skill_question,
    records_from_rows,
)

pytestmark = pytest.mark.unit


# -- telling the two questions apart -----------------------------------------
@pytest.mark.parametrize(
    "question",
    [
        "How accurate are your forecasts?",
        "How good are your predictions for CO2?",
        "Can I trust the forecast?",
        "How reliable is the humidity forecast at 24h?",
        "What is the forecast accuracy?",
        "Show me the backtest results",
    ],
)
def test_a_question_about_accuracy_is_recognised(question):
    assert is_skill_question(question) is True, question


@pytest.mark.parametrize(
    "question",
    [
        "What will the CO2 be tomorrow in room 5.01?",
        "Forecast the temperature for floor 5",
        "Predict occupancy next week",
        "What is the temperature now?",
    ],
)
def test_a_request_for_a_forecast_is_not(question):
    """Asking FOR a forecast wants a number; asking how good they are wants the
    track record behind the numbers."""
    assert is_skill_question(question) is False, question


# -- reading the published triples -------------------------------------------
def test_rows_become_records():
    rows = [
        {
            "m": "co2",
            "h": "24.0",
            "mae": "120.84",
            "mape": "16.34",
            "ci": "0.8588",
            "at": "2026-08-19T02:07:52",
            "note": "Measured over 6 walk-forward fit(s).",
        }
    ]
    (r,) = records_from_rows(rows)
    assert r.modality == "co2" and r.horizon_h == 24.0
    assert r.mae == 120.84 and r.ci80 == 0.8588 and r.n_fits == 6


def test_a_row_without_a_modality_or_horizon_is_skipped():
    assert records_from_rows([{"m": "", "h": "1"}, {"m": "co2", "h": "not-a-number"}]) == []


# -- what the answer says ----------------------------------------------------
def test_nothing_measured_says_so_and_does_not_guess():
    out = format_skill([])
    assert "No forecast skill has been measured" in out
    assert "will not guess" in out


def test_an_unmeasured_modality_is_not_reported_as_bad():
    """ "Nobody has backtested occupancy" and "occupancy forecasts badly" are
    different statements, and only one of them was measured."""
    out = format_skill([SkillRecord("co2", 24, mae=1.0)], modality="occupancy")
    assert "has not been backtested" in out
    assert "not the same as it forecasting badly" in out
    assert "co2" in out


def test_coverage_below_nominal_is_flagged_plainly():
    """An 80% interval that covered 64% is miscalibrated. Softening that would
    defeat the point of measuring it."""
    out = format_skill([SkillRecord("humidity", 1, mae=3.1, ci80=0.6388, n_fits=6)])
    assert "⚠" in out
    assert "optimistic" in out
    assert "64%" in out


def test_coverage_at_or_above_nominal_is_not_flagged():
    out = format_skill([SkillRecord("noise", 6, mae=0.98, ci80=0.9768, n_fits=6)])
    assert "⚠" not in out


def test_the_fit_count_is_reported_with_the_coverage():
    """0.83 over six fits is a different claim from 0.83 over six hundred."""
    out = format_skill([SkillRecord("co2", 1, mae=112.4, ci80=0.8333, n_fits=6)])
    assert "| 6 |" in out
    assert "Sample size is small" in out


def test_the_measurement_date_is_carried_through():
    """A figure is only as current as the data it was measured on."""
    out = format_skill([SkillRecord("co2", 1, mae=1.0, measured_at="2026-08-19T02:07:52")])
    assert "2026-08-19" in out


def test_the_nominal_is_named_once():
    assert NOMINAL_COVERAGE_80 == 0.80


# -- and it is actually reachable --------------------------------------------
def test_the_observability_lane_calls_it():
    """The defect IS a vocabulary with no reader. Adding a second unread one would
    be the joke telling itself."""
    import inspect

    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator)
    assert "published_skill(_sx_skill)" in src
    assert "is_skill_question(question)" in src


def test_the_publisher_transcribes_and_does_not_measure():
    """It must never compute an error itself: the grader measures, this copies."""
    import importlib.util
    import inspect
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "publish_forecast_skill.py"
    spec = importlib.util.spec_from_file_location("_pub_skill", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    src = inspect.getsource(mod)
    for computed in ("mean(", "np.", "sqrt", "abs(actual"):
        assert computed not in src, computed
    # a registry that does not exist must publish nothing rather than default
    assert "must not appear in the graph" in src


def test_unparseable_cells_are_skipped_not_guessed():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "publish_forecast_skill.py"
    spec = importlib.util.spec_from_file_location("_pub_skill2", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rows = mod.cells({"co2": {"1h": {"mae": 1.0}, "soon": {"mae": 2.0}}})
    assert [r["horizon_h"] for r in rows] == [1.0]
