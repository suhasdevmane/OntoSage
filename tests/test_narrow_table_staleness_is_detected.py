# -*- coding: utf-8 -*-
"""Stale evidence must not be able to pass as current status (CAVEAT-361).

Eight of bldg1's narrow modality tables — co2, contact, humidity, parking, plant, submeter,
temperature, waterflow — stopped at 2026-08-26 13:36, while seven others stayed current.
Diagnosed 2026-08-31: the data-publisher writes only the tables named in its two UUID maps
(`bldg1_timeseries_extension_uuids.json` -> energy/occupancy/iaq/equipment/water/noise/light,
`bldg1_extended_narrow_uuids.json` -> the two sensor_data_* tables). The eight stale tables
appear in NEITHER map, so nothing has ever topped them up; they were bulk-loaded once and
froze when that load stopped. `pm25_data` holds zero rows although PM2.5 is named directly by
the stakeholder catalogues.

That is a data-availability fact, not a bug in the answer path — and the answer path is what
these tests protect. The freshness gate exists precisely for this shape of failure (its own
docstring cites CAVEAT-207: "one table stopped writing while another kept going, every 'right
now' answer silently came from days-old data"). What must never regress is that the gate
NOTICES. Whether it is advisory or enforcing is a separate, deliberate posture decision.
"""

from datetime import datetime, timedelta, timezone

import pytest

from orchestrator.services.evidence.gates import freshness_gate
from orchestrator.services.evidence.policy import load_policy
from shared.models import AnswerStatus

pytestmark = pytest.mark.unit

#: The real observed gap: 2026-08-26 13:36 to 2026-08-31 17:00.
_REAL_STALENESS_MINUTES = 7390


def _policy():
    # load_policy() is the real loader. `EvidencePolicy()` constructs an EMPTY policy
    # whose every gate defaults to advisory — so a test built on it passes whatever the
    # config says, which is how the earlier staleness tests passed while testing nothing.
    return load_policy()


@pytest.mark.parametrize(
    "modality", ["co2", "temperature", "humidity", "parking", "plant", "submeter", "waterflow"]
)
def test_a_five_day_old_reading_fails_freshness_for_a_current_question(modality):
    now = datetime.now(timezone.utc)
    verdict = freshness_gate(
        _policy(),
        modality,
        now - timedelta(minutes=_REAL_STALENESS_MINUTES),
        now,
        is_current_question=True,
    )
    assert verdict.passed is False, f"{modality}: five-day-old data passed as current status"
    assert verdict.downgrade_to is AnswerStatus.INFERRED
    assert "old" in (verdict.reason or "")


def test_the_reason_states_the_actual_age_rather_than_a_generic_warning():
    """A user has to be able to tell 'six minutes' from 'five days'."""
    now = datetime.now(timezone.utc)
    verdict = freshness_gate(
        _policy(), "co2", now - timedelta(minutes=_REAL_STALENESS_MINUTES), now, True
    )
    assert str(_REAL_STALENESS_MINUTES) in (verdict.reason or "")


def test_an_empty_stream_is_distinguished_from_a_stale_one():
    """pm25_data has zero rows. 'No data' and 'old data' are different answers."""
    now = datetime.now(timezone.utc)
    verdict = freshness_gate(_policy(), "pm25", None, now, True)
    assert verdict.passed is False
    assert verdict.downgrade_to is AnswerStatus.NOT_ASSESSABLE, (
        "an absent stream must not be downgraded to INFERRED — there is no observation to "
        "infer anything from"
    )
    assert "no pm25 observation" in (verdict.reason or "")


def test_a_historical_question_is_not_gated_for_being_about_the_past():
    """Gating last March for being old would be nonsense, and would suppress real answers."""
    now = datetime.now(timezone.utc)
    verdict = freshness_gate(
        _policy(),
        "co2",
        now - timedelta(minutes=_REAL_STALENESS_MINUTES),
        now,
        is_current_question=False,
    )
    assert verdict.passed is True


def test_a_fresh_reading_passes():
    """The safety property: this must not decline everything."""
    now = datetime.now(timezone.utc)
    verdict = freshness_gate(_policy(), "co2", now - timedelta(minutes=2), now, True)
    assert verdict.passed is True
