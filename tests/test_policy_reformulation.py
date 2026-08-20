# -*- coding: utf-8 -*-
"""V5-T41: a denial proposes the nearest ALLOWED question, in the building's words."""

from __future__ import annotations

import pytest

from orchestrator.services.privacy.policy_engine import PolicyVerdict
from orchestrator.services.privacy.reformulation import (
    alternatives_for,
    explain,
    render_refusal,
)

pytestmark = pytest.mark.unit


def _restrict(**over):
    base = dict(
        decision="restrict",
        policy_iri="http://x#p_occ",
        reason="aggregation floor: ≥14 sensors / ≥7 spaces for role 'occupant'",
        resolution_s=300.0,
        min_sensors=14,
        min_spaces=7,
    )
    base.update(over)
    return PolicyVerdict(**base)


def _deny(
    reason="'individual_presence' requests are denied for every role — the system "
    "explains the building, never individuals",
    **over,
):
    base = dict(
        decision="deny",
        policy_iri="http://x#p_inf",
        reason=reason,
        alternative="ask for aggregate occupancy instead",
    )
    base.update(over)
    return PolicyVerdict(**base)


def test_restrict_offers_aggregate_and_coarsening_from_the_verdict():
    alts = alternatives_for(_restrict())
    joined = " ".join(alts)
    assert "14 sensors" in joined and "7 spaces" in joined  # the ACTUAL floors
    assert "5-second average" in joined or "average" in joined
    assert any("recent" in a for a in alts)


def test_resolution_units_read_naturally():
    hourly = alternatives_for(_restrict(resolution_s=3600, min_sensors=1, min_spaces=1))
    assert any("1-hour average" in a for a in hourly)


def test_person_question_gets_a_room_level_rewrite():
    alts = alternatives_for(_deny(), "Is the professor in her office right now?")
    assert any("Is anyone in that office" in a for a in alts)
    assert any("never individuals" in a or "counts" in a for a in alts)


def test_badge_history_rewrite():
    alts = alternatives_for(_deny(), "Show me the badge history for the manager this week")
    assert any("entries were recorded" in a for a in alts)


def test_rate_limit_denial_points_at_the_retry_window():
    v = _deny(
        reason="rate limit reached: 600 queries per 60 min for role 'occupant'",
        alternative="retry in ~42s",
    )
    assert alternatives_for(v) == ["retry in ~42s"]


def test_missing_policy_denial_points_at_the_admin():
    v = _deny(reason="no access policy is registered for role 'visitor'", alternative="")
    assert any("administrator" in a for a in alternatives_for(v))


def test_explanation_prefers_the_buildings_own_policy_comment():
    v = _deny()
    comment = "Occupant data stays with the occupant; aggregates are always available."
    assert explain(v, comment) == comment
    # with no authored comment, a generic but honest fallback
    assert "never identifies" in explain(v)


def test_rendered_refusal_has_head_why_and_options():
    text = render_refusal(_deny(), "Is the professor in her office?", "")
    assert text.startswith("**I can't answer that.**")
    assert "You can instead:" in text
    assert "- " in text
    assert "p_inf" in text  # policy cited


def test_restrict_head_distinguishes_granularity_from_prohibition():
    text = render_refusal(_restrict(), "occupancy of my office")
    assert "at the level you asked" in text
    assert "You can instead:" in text
