# -*- coding: utf-8 -*-
"""Stale evidence may no longer pass as current status (CAVEAT-361, enforced 2026-09-02).

Eight of bldg1's stores stopped receiving rows on 2026-08-26 and 728 of its 2,861 connected
points read from them. In advisory mode the freshness gate noticed every single time — it
returns passed=False with the measured age against a 15-minute limit — and changed nothing.
"What is the CO2 in here right now" could still be answered from a five-day-old reading with
nothing in the text saying so.

Enforcing applies the gate's own downgrade rather than a refusal:

* a stale reading is reported as the LAST RECORDED OBSERVATION (INFERRED) with its age. It
  is real evidence about the recent past, and throwing it away would replace a stale answer
  with none, which is both less useful and less true;
* an ABSENT stream stays NOT_ASSESSABLE — there is no observation to infer anything from,
  and the two must not collapse into one verdict;
* a HISTORICAL question is untouched. Last March is not stale for being about March.

The freshness gate is switched alone. Every other gate stays advisory, and this test pins
that too: flipping the whole set at once would make any behaviour change impossible to
attribute to a particular guard.
"""

from datetime import datetime, timedelta, timezone

import pytest

from orchestrator.services.evidence.gates import freshness_gate
from orchestrator.services.evidence.policy import GateMode, load_policy
from shared.models import AnswerStatus

pytestmark = pytest.mark.unit

_REAL_STALENESS_MINUTES = 7390  # 2026-08-26 13:36 -> 2026-08-31 17:00


def _policy():
    # load_policy() is the real loader. `EvidencePolicy()` constructs an EMPTY policy
    # whose every gate defaults to advisory — so a test built on it passes whatever the
    # config says, which is how the earlier staleness tests passed while testing nothing.
    return load_policy()


def test_freshness_is_enforcing():
    assert _policy().gate_mode("freshness") is GateMode.ENFORCING
    assert _policy().is_enforcing("freshness") is True


@pytest.mark.parametrize(
    "gate",
    [
        "source_precedence",
        "permission",
        "completeness",
        "agreement",
        "spatial_adequacy",
        "calibration",
        "consequence",
        "causal_claim",
    ],
)
def test_every_other_gate_stays_advisory(gate):
    """Switched one at a time, so a behaviour change is attributable to a named guard."""
    assert _policy().gate_mode(gate) is GateMode.ADVISORY


def test_a_stale_reading_is_downgraded_rather_than_refused():
    """The user's decision: report the last recorded reading, do not withhold it."""
    now = datetime.now(timezone.utc)
    verdict = freshness_gate(
        _policy(),
        "co2",
        now - timedelta(minutes=_REAL_STALENESS_MINUTES),
        now,
        is_current_question=True,
    )
    assert verdict.passed is False
    assert verdict.mode is GateMode.ENFORCING
    assert verdict.downgrade_to is AnswerStatus.INFERRED
    assert verdict.downgrade_to is not AnswerStatus.NOT_ASSESSABLE


def test_the_age_is_stated_so_the_reader_can_judge_it():
    now = datetime.now(timezone.utc)
    verdict = freshness_gate(
        _policy(), "co2", now - timedelta(minutes=_REAL_STALENESS_MINUTES), now, True
    )
    assert str(_REAL_STALENESS_MINUTES) in (verdict.reason or "")


def test_an_absent_stream_is_still_distinguished_from_a_stale_one():
    """pm25_data holds zero rows. 'No data' and 'old data' are different answers."""
    now = datetime.now(timezone.utc)
    verdict = freshness_gate(_policy(), "pm25", None, now, True)
    assert verdict.downgrade_to is AnswerStatus.NOT_ASSESSABLE


def test_a_historical_question_is_not_downgraded():
    """Enforcement must not start refusing questions about the past."""
    now = datetime.now(timezone.utc)
    verdict = freshness_gate(
        _policy(),
        "co2",
        now - timedelta(minutes=_REAL_STALENESS_MINUTES),
        now,
        is_current_question=False,
    )
    assert verdict.passed is True


def test_a_fresh_reading_is_untouched():
    """The safety property: enforcing must not downgrade healthy answers."""
    now = datetime.now(timezone.utc)
    assert freshness_gate(_policy(), "co2", now - timedelta(minutes=2), now, True).passed is True
