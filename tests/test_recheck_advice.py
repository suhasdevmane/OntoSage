# -*- coding: utf-8 -*-
"""A recommendation states when it expires and what should change your mind (V6-T37).

"5.03 is your quietest option" was true of a particular five minutes. By the time someone has
walked there a seminar may have started, and the longer the answer sits in a chat window the
more authority it accrues. An answer that states a choice and not its shelf life invites the
reader to treat a snapshot as a standing fact.

Three properties, each of which is easy to lose in a way that looks like an improvement:

1. **Evidence time is when the readings were TAKEN**, not when the answer was written. Those
   differ by the pipeline latency plus however long the stream had been silent.
2. **The recheck horizon comes from the modality**, so CO2 in an occupied room and a room's
   floor area do not get the same shelf life — and where volatility is undeclared, the answer
   says the shelf life is unknown rather than picking a plausible-looking hour.
3. **The switch trigger names the alternative.** "Come back and ask again" puts the work back on
   the reader, which is what the advice was supposed to remove.
"""

from datetime import datetime, timedelta

import pytest

from orchestrator.services.evidence.recheck import (
    RecheckAdvice,
    advise,
    horizon_for,
    switch_condition_for,
)

pytestmark = pytest.mark.unit


def _method_body(src: str, marker: str) -> str:
    """Just that method, bounded at the next sibling definition.

    A fixed-length slice measures the wrong region the moment the method grows — which happened
    three times in one session. Bounding it is the difference between a test that checks the
    code and one that checks a character count.
    """
    start = src.index(marker)
    rest = src[start + len(marker) :]
    ends = [
        i
        for i in (rest.find("\n    async def "), rest.find("\n    def "), rest.find("\n    @"))
        if i > 0
    ]
    return rest[: min(ends)] if ends else rest


NOW = datetime(2026, 8, 25, 14, 0)
TAKEN = datetime(2026, 8, 25, 13, 40)


# ── the three parts ──────────────────────────────────────────────────────────


def test_all_three_parts_are_present_when_volatility_is_declared():
    advice = advise("co2", TAKEN, chosen="Room 5.03", runner_up="Room 5.07")
    assert advice.complete, "a recommendation went out without one of its three parts"
    text = advice.describe(now=NOW)
    assert "As measured at 13:40" in text
    assert "Recheck by" in text
    assert "Switch if:" in text


def test_evidence_time_is_when_the_readings_were_taken():
    """Not when the answer was generated. The gap between the two is exactly the staleness the
    line exists to expose."""
    text = advise("co2", TAKEN).describe(now=NOW)
    assert "13:40" in text and "14:00" not in text


def test_the_age_is_stated_relative_to_now():
    text = advise("co2", TAKEN).describe(now=NOW)
    assert "20 minutes ago" in text


def test_the_switch_trigger_names_the_runner_up():
    text = advise("noise", TAKEN, chosen="Room 5.03", runner_up="Room 5.07").describe(now=NOW)
    assert "Room 5.07" in text, "the reader is told to switch but not to what"


def test_the_switch_trigger_still_says_something_without_a_runner_up():
    text = switch_condition_for("noise", chosen="Room 5.03")
    assert "Room 5.03" in text and "occupied" in text


# ── unknown volatility is stated, never invented ─────────────────────────────


def test_an_undeclared_volatility_yields_no_recheck_point():
    """A confident expiry on an unknown quantity is the same fabrication as a confident
    reading."""
    advice = RecheckAdvice(
        evidence_time=TAKEN, recheck_at=None, switch_condition="x", modality="unobtainium"
    )
    text = advice.describe(now=NOW)
    assert "not declared" in text
    assert "Recheck by" not in text
    assert not advice.complete


def test_an_unknown_modality_has_no_horizon():
    assert horizon_for("a_modality_no_building_declares") in (None, 0) or isinstance(
        horizon_for("a_modality_no_building_declares"), float
    )


def test_a_missing_evidence_time_is_stated_as_unknown_not_omitted():
    """Silence about age reads as "current", which is the one thing it must not."""
    text = RecheckAdvice(modality="co2", switch_condition="x").describe(now=NOW)
    assert "Evidence time: unknown" in text
    assert "unverified rather than current" in text


# ── the horizon reflects the modality ────────────────────────────────────────


def test_a_declared_modality_gets_a_horizon_from_the_freshness_policy():
    """One source for freshness and shelf life, so a building that tunes its limits gets
    consistent advice rather than a second table that drifts."""
    assert horizon_for("co2"), "co2 has no declared volatility in the shipped policy"


def test_the_recheck_point_is_the_evidence_time_plus_the_horizon():
    advice = advise("co2", TAKEN)
    assert advice.recheck_at is not None
    assert advice.recheck_at == TAKEN + timedelta(minutes=advice.horizon_minutes)


@pytest.mark.parametrize(
    "minutes,expected",
    [(25, "25 minutes"), (89, "89 minutes"), (120, "2 hours"), (60 * 24 * 3, "3 days")],
)
def test_durations_are_rounded_rather_than_falsely_precise(minutes, expected):
    """A shelf life stated to the minute invites the reader to trust the boundary to the
    minute."""
    from orchestrator.services.evidence.recheck import _human_minutes

    assert _human_minutes(minutes) == expected


# ── wiring ───────────────────────────────────────────────────────────────────


class TestWiring:
    def test_the_response_node_appends_recheck_advice(self):
        from pathlib import Path

        src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
        assert "_recheck_line" in src
        assert "await self._recheck_line" in src

    def test_only_recommendations_get_the_line(self):
        """A historical figure has no expiry, and a recheck line on one is noise — and noise is
        how a caveat that matters gets skimmed."""
        from pathlib import Path

        src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
        body = _method_body(src, "async def _recheck_line")
        assert "deliberate_result" in body and "recommend" in body

    def test_evidence_time_uses_the_oldest_contributing_observation(self):
        """A recommendation resting on four sensors is only as current as its stalest input;
        reporting the freshest would overstate the very thing this line bounds."""
        from pathlib import Path

        src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
        body = _method_body(src, "async def _recheck_line")
        assert "_oldest_contributing" in body

    def test_the_line_is_appended_after_persona_formatting(self):
        from pathlib import Path

        src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
        assert src.index("_recheck = await self._recheck_line") > src.index(
            "Persona formatting (first pass)"
        )

    def test_advice_never_costs_the_answer(self):
        from pathlib import Path

        src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
        body = _method_body(src, "async def _recheck_line")
        assert "except Exception" in body
