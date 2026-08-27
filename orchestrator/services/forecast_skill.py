# -*- coding: utf-8 -*-
"""Answer "how good are your forecasts?" from the graph (CAVEAT-324).

``ontosage:ForecastSkill`` declares ``backtestMAE``, ``backtestMAPE``,
``ciCoverage80`` and ``horizonHours``, and the schema states what they are for:
*"Cited in every forecast answer; makes 'how good are your forecasts?'
SPARQL-answerable."*

Half of that was already true — ``forecast_agent._skill_note`` cites measured
skill in every forecast answer, reading the grader's JSON registry directly. The
other half was not: nothing put the numbers in the graph, and nothing read them
back, so a person asking how accurate the forecasts are got no answer at all.

``scripts/publish_forecast_skill.py`` writes the cells as triples; this reads them
back. Reporting rules that matter:

* **A modality with no published record is reported as unmeasured**, not as
  perfect and not as bad. "Nobody has backtested occupancy here" is an answer.
* **Coverage is reported with its fit count.** 0.83 over six walk-forward fits is
  a different claim from 0.83 over six hundred, and a coverage figure without its
  sample size invites the reader to over-trust it.
* **Coverage below nominal is stated plainly.** An 80% interval that covered 64%
  of actuals is a miscalibrated interval; softening that would defeat the point of
  measuring it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

#: Questions about the system's own predictive accuracy. Distinct from asking FOR a
#: forecast: "what will the CO2 be tomorrow?" wants a number, "how accurate are your
#: forecasts?" wants the track record behind it.
_SKILL_QUESTION_RE = re.compile(
    r"\bhow\s+(?:good|accurate|reliable|well)\b.{0,40}\b(?:forecast|predict|projection)"
    r"|\b(?:forecast|prediction)\s+(?:accuracy|skill|error|quality|reliability)\b"
    r"|\bhow\s+much\s+(?:should\s+i\s+)?trust\b.{0,30}\b(?:forecast|prediction)"
    r"|\bcan\s+i\s+trust\b.{0,30}\b(?:forecast|prediction)"
    r"|\bhow\s+confident\b.{0,30}\b(?:forecast|prediction)"
    r"|\b(?:backtest|walk[- ]forward)\b",
    re.IGNORECASE,
)

#: The nominal coverage of the interval this property records. Named once so the
#: comparison in the narration cannot drift from the property it is about.
NOMINAL_COVERAGE_80 = 0.80


def is_skill_question(query: str) -> bool:
    """True when the question asks how good the forecasts are, not for a forecast."""
    return bool(_SKILL_QUESTION_RE.search(query or ""))


@dataclass
class SkillRecord:
    modality: str
    horizon_h: float
    mae: Optional[float] = None
    mape: Optional[float] = None
    ci80: Optional[float] = None
    measured_at: str = ""
    n_fits: Optional[int] = None


_QUERY = (
    "PREFIX ontosage: <http://ontosage.org/capabilities#>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "SELECT ?m ?h ?mae ?mape ?ci ?at ?note WHERE {\n"
    "  ?s a ontosage:ForecastSkill ;\n"
    "     ontosage:skillOf ?m ;\n"
    "     ontosage:horizonHours ?h .\n"
    "  OPTIONAL { ?s ontosage:backtestMAE ?mae }\n"
    "  OPTIONAL { ?s ontosage:backtestMAPE ?mape }\n"
    "  OPTIONAL { ?s ontosage:ciCoverage80 ?ci }\n"
    "  OPTIONAL { ?s ontosage:skillMeasuredAt ?at }\n"
    "  OPTIONAL { ?s rdfs:comment ?note }\n"
    "} ORDER BY ?m ?h"
)


def _num(v: Any) -> Optional[float]:
    try:
        return float(str(v))
    except (TypeError, ValueError):
        return None


_FITS_RE = re.compile(r"(\d+)\s+walk-forward")


def records_from_rows(rows: Any) -> List[SkillRecord]:
    """Parse SPARQL rows into skill records. Pure."""
    out: List[SkillRecord] = []
    for row in rows or []:
        get = row.get if isinstance(row, dict) else (lambda k: getattr(row, k, None))
        modality = str(get("m") or "").strip()
        horizon = _num(get("h"))
        if not modality or horizon is None:
            continue
        note = str(get("note") or "")
        fits = _FITS_RE.search(note)
        out.append(
            SkillRecord(
                modality=modality,
                horizon_h=horizon,
                mae=_num(get("mae")),
                mape=_num(get("mape")),
                ci80=_num(get("ci")),
                measured_at=str(get("at") or "")[:19],
                n_fits=int(fits.group(1)) if fits else None,
            )
        )
    return out


async def published_skill(run_select: Callable[[str], Any]) -> List[SkillRecord]:
    """Every published skill record. [] on any failure — never raises."""
    try:
        res = await run_select(_QUERY)
    except Exception as exc:
        logger.debug(f"[forecast_skill] lookup failed: {exc}")
        return []
    rows = res.get("rows") if isinstance(res, dict) else res
    return records_from_rows(rows)


def format_skill(records: List[SkillRecord], *, modality: Optional[str] = None) -> str:
    """A markdown answer about measured predictive skill."""
    if not records:
        return (
            "**No forecast skill has been measured for this building.** The system can "
            "still forecast, but nothing has been backtested, so I have no basis to tell "
            "you how accurate it is — and I will not guess. Running the forecast grader "
            "measures it, after which this question is answered from the graph."
        )
    if modality:
        wanted = [r for r in records if r.modality.lower() == modality.lower()]
        if not wanted:
            have = ", ".join(sorted({r.modality for r in records}))
            return (
                f"**{modality} has not been backtested on this building.** That is not the "
                f"same as it forecasting badly — nobody has measured it. Measured "
                f"modalities: {have}."
            )
        records = wanted

    lines = [
        "**Measured forecast skill** (walk-forward backtesting on this building's own data):",
        "",
        "| modality | horizon | MAE | MAPE | 80% interval covered | fits |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    poor = []
    for r in sorted(records, key=lambda x: (x.modality, x.horizon_h)):
        cov = "—"
        if r.ci80 is not None:
            cov = f"{r.ci80:.0%}"
            if r.ci80 < NOMINAL_COVERAGE_80:
                cov += " ⚠"
                poor.append(f"{r.modality} at {r.horizon_h:g}h ({r.ci80:.0%})")
        lines.append(
            f"| {r.modality} | {r.horizon_h:g}h "
            f"| {'—' if r.mae is None else f'{r.mae:g}'} "
            f"| {'—' if r.mape is None else f'{r.mape:g}%'} "
            f"| {cov} | {r.n_fits if r.n_fits is not None else '—'} |"
        )
    if poor:
        lines += [
            "",
            "⚠ marks an interval that covered LESS than its nominal 80%: "
            + ", ".join(poor)
            + ". Those bands are optimistic — treat the stated range as narrower than "
            "the real uncertainty.",
        ]
    stamps = sorted({r.measured_at for r in records if r.measured_at})
    if stamps:
        lines += [
            "",
            f"_Measured {stamps[0][:10]}"
            + (f" to {stamps[-1][:10]}" if stamps[-1][:10] != stamps[0][:10] else "")
            + ". A figure is only as current as the data it was measured on._",
        ]
    fitcounts = [r.n_fits for r in records if r.n_fits is not None]
    if fitcounts and max(fitcounts) < 30:
        lines += [
            "",
            f"_Sample size is small (at most {max(fitcounts)} fits per cell), so these are "
            "indicative rather than tight estimates._",
        ]
    return "\n".join(lines)
