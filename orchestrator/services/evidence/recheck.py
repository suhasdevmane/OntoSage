# -*- coding: utf-8 -*-
"""When a recommendation goes out of date, and what should make you change your mind (V6-T37).

A recommendation is a claim with a shelf life. *"5.03 is your quietest option"* was true of a
particular five minutes, and by the time someone has walked there a seminar may have started.
An answer that states a choice and not its expiry invites the reader to treat a snapshot as a
standing fact — and the longer it sits in a chat window, the more authority it accrues.

Three things travel with every recommendation:

**Evidence time** — when the readings were TAKEN, never when the answer was generated. Those
differ by the whole pipeline latency plus however long the stream had been silent, and only the
first tells the reader how old the world they are being shown is.

**Recheck point** — evidence time plus the modality's own volatility. CO2 in an occupied room
moves in minutes; a room's area does not move at all. Deriving this from the modality rather
than fixing one interval is what stops the advice being either useless or alarmist.

**Switch trigger** — the condition under which the choice stops being the right one, stated
BEFORE it happens. "Come back and ask again" is not advice; "if it fills up, the next best is
5.07" is.

**A recheck point is never invented.** Where the modality's volatility is undeclared, the answer
says the shelf life is unknown rather than picking a plausible-looking hour — a confident expiry
on an unknown quantity is the same fabrication as a confident reading.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from shared.utils import get_logger

logger = get_logger(__name__)

#: Volatility is read from the freshness policy: the age at which a reading stops being usable
#: as "now" IS the modality's practical shelf life, and having one source for both means a
#: building that tunes its freshness limits gets consistent recheck advice for free rather than
#: a second table that drifts.
DEFAULT_RECHECK_FRACTION = 1.0


@dataclass
class RecheckAdvice:
    """When this recommendation expires, and what should change the reader's mind."""

    evidence_time: Optional[datetime] = None
    recheck_at: Optional[datetime] = None
    horizon_minutes: Optional[float] = None
    switch_condition: str = ""
    modality: str = ""

    @property
    def complete(self) -> bool:
        """All three parts present. The acceptance criterion, expressed as a property."""
        return bool(self.evidence_time and self.recheck_at and self.switch_condition)

    def describe(self, now: Optional[datetime] = None) -> str:
        """The line a recommendation must carry."""
        parts = []

        if self.evidence_time is None:
            parts.append(
                "**Evidence time: unknown.** I can't tell you how old these readings are, so "
                "treat the recommendation as unverified rather than current."
            )
        else:
            age = ""
            if now is not None:
                minutes = (now - self.evidence_time).total_seconds() / 60.0
                if minutes >= 0:
                    age = f", {_human_minutes(minutes)} ago"
            parts.append(f"**As measured at {self.evidence_time:%H:%M on %d %b}{age}.**")

        if self.recheck_at is None:
            parts.append(
                "How quickly this goes out of date is not declared for "
                f"{self.modality or 'this measurement'}, so I can't give you a recheck point — "
                "check again before relying on it."
            )
        else:
            parts.append(
                f"Recheck by **{self.recheck_at:%H:%M}** "
                f"({_human_minutes(self.horizon_minutes or 0)} of useful life)."
            )

        if self.switch_condition:
            parts.append(f"Switch if: {self.switch_condition}")
        return " ".join(parts)


def _human_minutes(minutes: float) -> str:
    """'25 minutes' / '2 hours' / '3 days'. Rounded, because a false precision on a shelf life
    invites the reader to trust the boundary to the minute."""
    minutes = max(0.0, float(minutes))
    if minutes < 90:
        return f"{round(minutes)} minutes"
    hours = minutes / 60.0
    if hours < 36:
        return f"{round(hours)} hours"
    return f"{round(hours / 24.0)} days"


def horizon_for(modality: str, policy=None) -> Optional[float]:
    """Minutes of useful life for a recommendation resting on this modality.

    Returns None when the building has not declared one. That is a result, not a failure: a
    plausible-looking default would be a confident expiry on an unknown quantity.
    """
    try:
        if policy is None:
            from orchestrator.services.evidence.policy import load_policy

            policy = load_policy()
        limit = policy.max_age_minutes(modality)
        if limit and limit > 0:
            return float(limit) * DEFAULT_RECHECK_FRACTION
    except Exception as exc:
        logger.debug(f"[recheck] no declared volatility for {modality!r}: {exc}")
    return None


def switch_condition_for(modality: str, chosen: str = "", runner_up: str = "") -> str:
    """The condition that should make the reader change their mind.

    Generic English over the modality, never a building literal, and it names the ALTERNATIVE
    where one is known — "come back and ask again" puts the work back on the reader, which is
    what the advice was supposed to remove.
    """
    what = (modality or "conditions").replace("_", " ")
    where = chosen or "the space you chose"
    if runner_up:
        return (
            f"{what} in {where} moves outside the range that made it the best option — "
            f"the next best was {runner_up}."
        )
    return (
        f"{what} in {where} moves outside the range that made it the best option, or the space "
        f"becomes occupied."
    )


def advise(
    modality: str,
    evidence_time: Optional[datetime],
    chosen: str = "",
    runner_up: str = "",
    policy=None,
) -> RecheckAdvice:
    """Assemble the three parts. Never raises."""
    horizon = horizon_for(modality, policy)
    recheck_at = None
    if evidence_time is not None and horizon:
        recheck_at = evidence_time + timedelta(minutes=horizon)
    return RecheckAdvice(
        evidence_time=evidence_time,
        recheck_at=recheck_at,
        horizon_minutes=horizon,
        switch_condition=switch_condition_for(modality, chosen, runner_up),
        modality=modality,
    )


__all__ = ["RecheckAdvice", "advise", "horizon_for", "switch_condition_for"]
