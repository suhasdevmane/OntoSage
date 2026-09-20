# -*- coding: utf-8 -*-
"""An overflowing prompt must not lose its question.

Live, unscripted, 2026-09-18: "How busy is the building right now?" fetched 250 occupancy streams
and sent a 64,436-character narration prompt to a 16,384-token model. Ollama drops from the FRONT
of an overflowing prompt, so the model saw only the tail. It answered with the developer ticket id
in the last rule (`**BUG-606**`); with that stripped, "I'm ready to help". The analytics had run
correctly; the question never reached the model.

Three defences, each tested here: the analytics lane summarises many series in code (as it already
does for series that span floors), the model boundary cuts the MIDDLE of any prompt that still
overflows, and the cut says so.
"""

from __future__ import annotations

import inspect
import logging
from datetime import datetime, timedelta

import pytest

import importlib

lm = importlib.import_module("orchestrator.llm_manager")  # the package attribute is the singleton
from orchestrator.services.series_summary import summarise_latest_overview

pytestmark = pytest.mark.unit


# ── the budget ───────────────────────────────────────────────────────────────────────────────────


def test_the_budget_is_sized_from_the_configured_window(monkeypatch):
    assert lm.prompt_char_budget(16384) == int(16384 * 2.75)
    monkeypatch.setenv("OLLAMA_NUM_CTX", "16384")
    assert lm.prompt_char_budget() == int(16384 * 2.75)
    monkeypatch.setenv("OLLAMA_NUM_CTX", "not-a-number")
    assert lm.prompt_char_budget() == int(8192 * 2.75), "a bad setting falls back, never raises"


def test_a_prompt_within_budget_is_the_same_object():
    p = "x" * 1000
    assert lm.fit_prompt(p, 45_056) is p


def test_the_one_measured_failure_is_caught_and_the_known_good_size_is_not():
    """BUG-474: 45,573 characters failed at a 16k window. 11,125 (the sparql narration) works."""
    budget = lm.prompt_char_budget(16384)
    assert len("x" * 45_573) > budget
    assert len("x" * 11_125) < budget


def test_overflow_keeps_both_ends_and_says_so(caplog):
    head = "You are an analytics assistant. Answer the user's QUESTION. " + "A" * 200
    tail = "10. Is internally consistent.\n\nResponse:"
    prompt = head + ("data line\n" * 8000) + tail
    with caplog.at_level(logging.WARNING):
        out = lm.fit_prompt(prompt, 10_000)
    assert len(out) < 10_400  # budget plus the marker
    assert out.startswith("You are an analytics assistant. Answer the user's QUESTION.")
    assert out.endswith("Response:"), "the closing rule and the answer slot must survive"
    assert "characters of data were left out here" in out
    assert "Answer only from what is shown" in out
    assert any("exceeds" in r.message for r in caplog.records), "an overflow must be logged"


def test_the_measured_narration_prompt_keeps_its_instructions_and_its_closing_rule():
    """The real shape: instructions, 250 sensor lines, 30 KB of output, closing rules."""
    instructions = "You are an expert building analytics assistant.\nUser Query: How busy is the building right now?\n"
    sensors = "".join(
        f"  - UUID {i:08d}-aaaa is 'Occupancy Count Sensor - Room {i}' (unit: count)\n"
        for i in range(250)
    )
    output = "Latest Readings:\n" + ("Sensor: Room 4.67\nValue: 26.00 count\nTime: 2026-09-18 16:29:25\n" * 400)
    closing = "Generate a response that:\n1. Opens with the key finding\n\nResponse:"
    prompt = instructions + sensors + output + closing + ("padding " * 4000)
    assert len(prompt) > 60_000
    out = lm.fit_prompt(prompt, lm.prompt_char_budget(16384))
    assert "How busy is the building right now?" in out, "the question must survive"
    assert "Generate a response that:" in out or out.endswith("padding ")
    assert len(out) < lm.prompt_char_budget(16384) + 400


def test_non_strings_and_disabled_budgets_pass_through():
    assert lm.fit_prompt(None, 100) is None
    assert lm.fit_prompt(["a"], 1) == ["a"]
    p = "y" * 500
    assert lm.fit_prompt(p, 0) is p


def test_a_hosted_provider_is_left_alone():
    """A hosted model's window is not ours to guess."""
    m = lm.LLMManager.__new__(lm.LLMManager)
    m.provider = "openai"
    big = "z" * 200_000
    assert m._fit_to_context(big) is big
    m.provider = "ollama"
    assert len(m._fit_to_context(big)) < len(big)


def test_all_three_entry_points_cut_after_stripping_and_before_the_breaker():
    for name in ("generate", "generate_structured", "astream_generate"):
        code = inspect.getsource(getattr(lm.LLMManager, name)).split('"""', 2)[-1]
        assert "self._fit_to_context(prompt)" in code, name
        assert code.index("strip_tracker_ids(prompt)") < code.index("self._fit_to_context(prompt)")


# ── the overview ─────────────────────────────────────────────────────────────────────────────────


def _rows(n_sensors: int, per: int = 3, base_value: float = 0.0):
    t0 = datetime(2026, 9, 18, 9, 0, 0)
    rows = []
    for s in range(n_sensors):
        for k in range(per):
            rows.append(
                {
                    "uuid": f"u{s}",
                    "value": base_value + s + k * 0.1,
                    "timestamp": (t0 + timedelta(minutes=k)).isoformat(sep=" "),
                }
            )
    return rows


def _meta(n: int, unit: str = "persons"):
    return {f"u{s}": {"label": f"Room {s} occupancy", "unit": unit} for s in range(n)}


def test_the_overview_reports_spread_extremes_and_never_a_total():
    out = summarise_latest_overview(_rows(250), _meta(250))
    assert "latest reading from each of 250 series" in out
    assert "mean" in out and "range" in out and "of 250 series read zero" in out
    assert "Highest: Room 249 occupancy" in out
    assert "Lowest: Room 0 occupancy" in out
    assert "persons" in out
    assert "Do not add readings from different sensors" in out
    assert "u12" not in out, "no sensor identifier in text a narrator will read"
    assert len(out) < 2500, "a 250-series overview must be a fraction of the 30 KB it replaces"


def test_the_latest_reading_is_chosen_by_timestamp_not_by_row_order():
    rows = [
        {"uuid": "a", "value": 9, "timestamp": "2026-09-18 10:00:00"},
        {"uuid": "a", "value": 1, "timestamp": "2026-09-18 08:00:00"},  # older, listed later
        {"uuid": "b", "value": 5, "timestamp": "2026-09-18 10:00:00"},
    ]
    out = summarise_latest_overview(rows, {"a": {"label": "A"}, "b": {"label": "B"}})
    assert "Highest: A 9" in out, out
    assert "Lowest: B 5" in out


def test_zero_readings_are_counted():
    rows = [{"uuid": str(i), "value": 0 if i < 3 else 2, "timestamp": "2026-09-18 10:00:00"} for i in range(5)]
    out = summarise_latest_overview(rows, {str(i): {"label": f"R{i}"} for i in range(5)})
    assert "3 of 5 series read zero" in out


def test_mixed_units_are_not_given_a_unit():
    meta = {"0": {"label": "a", "unit": "persons"}, "1": {"label": "b", "unit": "degC"}}
    rows = [{"uuid": "0", "value": 1}, {"uuid": "1", "value": 2}]
    out = summarise_latest_overview(rows, meta)
    assert "persons" not in out and "degC" not in out


@pytest.mark.parametrize(
    "rows", [[], [{"uuid": "a", "value": 1}], [{"uuid": "a", "value": "n/a"}, {"uuid": "b", "value": None}]]
)
def test_fewer_than_two_usable_series_returns_none(rows):
    assert summarise_latest_overview(rows, {}) is None


# ── the lane uses it ─────────────────────────────────────────────────────────────────────────────


def test_the_analytics_lane_caps_the_per_sensor_block_and_prefers_the_overview():
    from orchestrator.agents import analytics_agent

    src = inspect.getsource(analytics_agent)
    assert "_MAX_SENSOR_LINES = 40" in src
    assert "summarise_latest_overview" in src
    assert "[:_MAX_SENSOR_LINES]" in src, "the fallback listing must never be unbounded again"
    assert src.index("elif overview:") < src.index("Sensor Information:"), (
        "the overview must be tried before the per-sensor listing"
    )
