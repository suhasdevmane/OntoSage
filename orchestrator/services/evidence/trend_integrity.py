# -*- coding: utf-8 -*-
"""Did the building change, or did the instrument? (V6-T42)

Rule R-14, from the PhD and Academic Office catalogues: *separate measurement change from
environmental change before reporting any trend.*

V6-T07 built the mechanism -- effective-dated configuration periods, and the ability to split
a window around a change. This module is the judgement that sits on top of it: given a
requested trend and the configuration history, **is this trend reportable, and as what?**

The failure it prevents is the most persuasive kind available. Relocating, recalibrating or
replacing a sensor puts a step change in its series, and a step change is exactly what a real
event in the building looks like. Reported as a trend, the answer is confident, specific,
quantified -- and about nothing that happened.

**The verdict is graded, not binary.** Refusing every trend that crosses a recalibration
would discard most long-horizon questions on a well-maintained building, which are the ones
the research catalogues care most about. So:

* no change in the window -> report the trend normally;
* a change, with long stable stretches either side -> report those SEPARATELY and say why
  they are not joined;
* a change, with nothing long enough to characterise -> report the discontinuity and decline
  the trend, because a fragment either side supports no shape at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Sequence, Tuple

from orchestrator.services.evidence.history import (
    ConfigurationPeriod,
    WindowIntegrity,
    check_window,
)
from shared.utils import get_logger

logger = get_logger(__name__)


class TrendVerdict(str, Enum):
    """How much of a trend claim the configuration history supports."""

    REPORTABLE = "reportable"  # one stable configuration throughout
    SEGMENTED = "segmented"  # changed, but each side is long enough to stand alone
    NOT_COMPARABLE = "not_comparable"  # changed, and no side is long enough to characterise


@dataclass
class TrendIntegrity:
    verdict: TrendVerdict
    integrity: WindowIntegrity
    caveat: str = ""
    segments: List[Tuple[datetime, datetime, Optional[str]]] = field(default_factory=list)

    @property
    def may_report_single_trend(self) -> bool:
        """True only when one number may be quoted for the whole window."""
        return self.verdict is TrendVerdict.REPORTABLE

    def describe(self) -> str:
        if self.verdict is TrendVerdict.REPORTABLE:
            return ""
        if self.verdict is TrendVerdict.SEGMENTED:
            return (
                f"{self.caveat} The periods either side are reported separately rather than "
                "as one trend, because joining them across the change would present a "
                "measurement artefact as a change in the building."
            )
        return (
            f"{self.caveat} No stretch either side is long enough to characterise on its "
            "own, so no trend is reported for this window."
        )


def assess_trend(
    periods: Sequence[ConfigurationPeriod],
    start: datetime,
    end: datetime,
) -> TrendIntegrity:
    """Whether a trend over this window can be attributed to the building.

    A building with NO configuration history recorded gets REPORTABLE, deliberately. The
    alternative -- treating unknown history as suspect -- would make every trend on every
    building unreportable until somebody backfilled metadata, which trades a rare wrong
    answer for a universal useless one. The absence is instead surfaced by the observability
    matrix, where it is actionable.
    """
    integrity = check_window(periods, start, end)

    if integrity.is_continuous:
        return TrendIntegrity(TrendVerdict.REPORTABLE, integrity)

    comparable = integrity.comparable_segments
    caveat = integrity.caveat()
    if len(comparable) >= 2:
        return TrendIntegrity(TrendVerdict.SEGMENTED, integrity, caveat, comparable)
    return TrendIntegrity(TrendVerdict.NOT_COMPARABLE, integrity, caveat, comparable)


def artefact_kinds(integrity: WindowIntegrity) -> List[str]:
    """The distinct kinds of change inside the window.

    Named individually because the remedies differ: a relocation invalidates the SPACE a
    reading is attributed to, while a recalibration invalidates its VALUE. An answer that
    says only "something changed" leaves the reader unable to tell which of their conclusions
    survives.
    """
    return sorted({change for _, change in integrity.boundaries if change})
