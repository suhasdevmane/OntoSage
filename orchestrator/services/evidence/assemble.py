# -*- coding: utf-8 -*-
"""Build the evidence record, once, for every answer (V6-T02).

**One chokepoint, not ten.** Every lane leaves what it knows on the state bus; this module
turns that into a single :class:`EvidenceRecord` at the end of the pipeline.

The alternative -- each lane building its own record -- was rejected on direct evidence from
this codebase. BUG-210 was two copies of one linking step drifting apart until identical
inputs produced different results depending which path ran. Ten copies of the evidence
assembler would reproduce that failure ten times, and each drift would be invisible because
every lane would still be producing *a* record.

Two properties this module guarantees:

* **A lane that emits nothing yields NOT_ASSESSABLE**, with a reason saying so. Silence is
  never read as success, which is what makes the chokepoint safe to add to lanes that do not
  know about it yet.
* **Assembly can never break an answer.** The caller wraps it, and every field degrades to a
  neutral value. An evidence record is there to describe the answer, and a describer that can
  take down the thing it describes is worse than none.
"""

from __future__ import annotations

import re as _re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from shared.models import (
    AnswerStatus,
    EvidenceRecord,
    EvidenceSource,
    OmissionReason,
    OmittedCriterion,
    Operation,
    SpatialAdequacy,
)
from shared.utils import get_logger

logger = get_logger(__name__)

#: Which lane produced the answer -> what KIND of act that was, and therefore what kind of
#: claim it can support. Ordered most-derived first: when several lanes ran, the answer is
#: shaped by the last one to touch it, and a forecast built on an aggregate is a forecast.
#:
#: **THE KEYS HERE ARE THE KEYS THE LANES ACTUALLY WRITE**, verified against the pipeline and
#: pinned by ``tests/test_evidence_chokepoint.py::test_every_lane_key_is_actually_written``.
#: The first version of this table was copied from CLAUDE.md's reserved-key list, which names
#: `sparql_results` and `sql_data` -- strings that appear nowhere in the pipeline. The lanes
#: write `sparql_result` and `sql_result` (singular), so the two most important data lanes
#: could never be inferred: every sensor-reading and metadata answer fell through to
#: NOT_ASSESSABLE, "no lane produced evidence for this answer".
#:
#: That failure is exactly the one this module's docstring says it exists to prevent. BUG-210
#: was two copies of one step drifting; T02 shipped a second copy of the lane list which had
#: already drifted from the one in ``_response_node``. Documentation is not a source of truth
#: about code, and a table of key names has to be checked against the code that writes them.
_LANE_SEMANTICS: Sequence[tuple] = (
    ("forecast_result", Operation.FORECAST, AnswerStatus.PREDICTED),
    ("deliberate_result", Operation.RECOMMENDATION, AnswerStatus.RECOMMENDED),
    ("diagnosis_result", Operation.DIAGNOSIS, AnswerStatus.INFERRED),
    ("analytics_result", Operation.CALCULATION, AnswerStatus.CALCULATED),
    # Authoritative records: a booking or a compliance date is looked up, not measured.
    # Calling it OBSERVED would blur a register entry into a sensor reading, and the
    # catalogues are explicit that the two must never be blurred.
    # A filed report (TODO-229). INFERRED, not OBSERVED, and the choice is not new
    # here: evidence/precedence.py already grades a human_report as "inference --
    # a person's account is evidence, not a measurement". The danger this closes is
    # a downstream reader treating "the tap in 5.16 is dripping" as something the
    # building observed. Nobody measured the tap; somebody said so, and the record
    # has to keep those apart. The ACT is an authoritative one on the system's own
    # register, which is why the operation matches register_result.
    ("report_intake_result", Operation.AUTHORITATIVE_LOOKUP, AnswerStatus.INFERRED),
    ("events_result", Operation.AUTHORITATIVE_LOOKUP, AnswerStatus.OBSERVED),
    ("register_result", Operation.AUTHORITATIVE_LOOKUP, AnswerStatus.OBSERVED),
    ("capability_result", Operation.AUTHORITATIVE_LOOKUP, AnswerStatus.OBSERVED),
    ("document_result", Operation.AUTHORITATIVE_LOOKUP, AnswerStatus.OBSERVED),
    # Geometry IS measured -- from the surveyed floor plan rather than from a sensor.
    # spatial_result must be tried BEFORE floor_plan_result: the spatial lane also renders
    # through the floor-plan channel for display, so testing floor_plan first would label
    # every geometry computation as a floor-plan lookup.
    ("spatial_result", Operation.OBSERVATION, AnswerStatus.OBSERVED),
    ("floor_plan_result", Operation.OBSERVATION, AnswerStatus.OBSERVED),
    ("sql_result", Operation.OBSERVATION, AnswerStatus.OBSERVED),
    ("sparql_result", Operation.AUTHORITATIVE_LOOKUP, AnswerStatus.OBSERVED),
)

#: The ten lanes T02 must cover, as named in its objective. Kept beside the table so a lane
#: added to one and forgotten in the other is a test failure rather than a silent gap.
T02_LANES: Sequence[str] = (
    "sparql_result",
    "sql_result",
    "analytics_result",
    "forecast_result",
    "deliberate_result",
    "events_result",
    "register_result",
    "capability_result",
    "spatial_result",
    "floor_plan_result",
)

#: Lanes whose whole purpose is to decline. Reaching one is a correct outcome, not a failure.
_REFUSAL_LANES = ("privacy_refusal_result", "control_result")


def infer_lane(results: Dict[str, Any]) -> Optional[str]:
    """Which lane shaped this answer."""
    for key, _op, _st in _LANE_SEMANTICS:
        if results.get(key):
            return key
    return None


def _human_report_source(results: Dict[str, Any]) -> Optional[EvidenceSource]:
    """The filed report as a source, marked as a person's account (TODO-229).

    ``EvidenceSource.kind`` has documented 'human_report' since the model was
    written and nothing ever emitted one. Without it a report turn produced a
    record with no sources at all, which reads as "nothing backed this answer" —
    when in fact something did, just not an instrument.

    ``simulated=False`` is asserted deliberately: a person really did file this.
    Everywhere else in this module a missing provenance degrades to None, because
    None and False are different claims; here the claim is known.
    """
    r = results.get("report_intake_result") or {}
    if not r:
        return None
    return EvidenceSource(
        source_id=str(r.get("report_id") or "user_report"),
        kind="human_report",
        store="postgres:user_reports",
        simulated=False,
        observed_at=None,  # a person's account carries no instrument timestamp
        calibration_state="unknown",
    )


def _sources_from(results: Dict[str, Any]) -> List[EvidenceSource]:
    """Lift whatever provenance the lanes already record.

    Deliberately forgiving: provenance shapes differ between lanes and a missing field must
    degrade to `simulated=None` (undeclared) rather than to False. None and False are NOT
    the same claim -- False asserts the data is real, None says nobody said.
    """
    out: List[EvidenceSource] = []
    for tag in results.get("_prov_stores") or []:
        try:
            if isinstance(tag, dict):
                out.append(
                    EvidenceSource(
                        source_id=str(tag.get("source_id") or tag.get("store") or "unknown"),
                        kind=str(tag.get("kind") or "sensor"),
                        store=str(tag.get("store") or ""),
                        simulated=tag.get("synthetic", tag.get("simulated")),
                        # V7-T10/T11/T17. Carried when the lane recorded them — a record
                        # register knows its owner, its version and when it takes effect;
                        # a sensor reading knows none of the three, and an empty string
                        # says so rather than inventing one.
                        owner=str(tag.get("owner") or ""),
                        authority=str(tag.get("authority") or ""),
                        record_version=str(tag.get("record_version") or ""),
                        effective_at=tag.get("effective_at"),
                    )
                )
            elif isinstance(tag, str):
                out.append(EvidenceSource(source_id=tag, kind="sensor", store=tag))
        except Exception:  # one malformed tag must not cost the whole record
            continue

    for uuid in contributing_uuids(results)[:25]:
        if not any(s.source_id == uuid for s in out):
            out.append(EvidenceSource(source_id=uuid, kind="sensor"))
    return out


def contributing_uuids(results: Dict[str, Any]) -> List[str]:
    """The timeseries ids behind this answer.

    NOT from ``results["uuids"]``. CLAUDE.md and agent-patterns.md both list that as a reserved
    key "set by the sparql node" and **nothing writes it** — the SQL node keeps `uuids` as a
    local and puts `sensor_metadata` on the bus instead, keyed by uuid. Reading the documented
    name returned an empty list on every answer, so no per-sensor source was ever created and
    every per-source field had nothing to attach to.

    `uuids` is still honoured first in case a lane ever starts writing it, so this does not
    become a second place that has to be kept in step.
    """
    out: List[str] = []
    seen = set()
    for key in ("uuids",):
        for u in results.get(key) or []:
            if isinstance(u, str) and u not in seen:
                seen.add(u)
                out.append(u)
    meta = results.get("sensor_metadata")
    if isinstance(meta, dict):
        for u in meta:
            if isinstance(u, str) and u not in seen:
                seen.add(u)
                out.append(u)
    return out


#: Column names that hold an observation time. Matched on the NAME first because a row can
#: carry several parseable values and only one of them is when the reading was taken.
_TIME_COL_RE = _re.compile(r"(?:^|_)(?:time|date|datetime|timestamp|ts|observed|recorded)", _re.I)

#: How far ahead of "now" a timestamp may sit and still be believed. Clocks drift between the
#: database server and this process; anything beyond this is a schedule, not an observation.
_CLOCK_SKEW_S = 300


def _as_datetime(value: Any) -> Optional[datetime]:
    """Parse one cell into an aware datetime, or None. Never raises."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and 8 <= len(value) <= 40:
        text = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is not None:
        return dt
    # Naive: the reading belongs to the building, so the building's timezone is the one that
    # makes it comparable. Assuming UTC would shift every staleness figure by the offset --
    # in Europe/London that is an hour of false freshness for half the year.
    try:
        from zoneinfo import ZoneInfo

        from shared.config import settings

        return dt.replace(tzinfo=ZoneInfo(settings.BUILDING_TIMEZONE))
    except Exception:
        return dt.replace(tzinfo=timezone.utc)


def _rows_of(payload: Any) -> List[Dict[str, Any]]:
    """The row list, whichever shape a lane used to hand it up."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []
    for path in (("results", "data"), ("data",), ("rows",)):
        cur: Any = payload
        for key in path:
            cur = cur.get(key) if isinstance(cur, dict) else None
        if isinstance(cur, list):
            return [r for r in cur if isinstance(r, dict)]
    return []


#: A uuid-shaped column NAME. In the wide table each sensor is its own column, so this is how
#: a row is attributed to the sensor it observed. Alphanumeric rather than strict hex, because
#: the synthetic ontology ids (``00000000-ac01-...``) are uuid-shaped without being hex uuids.
_UUID_SHAPE_RE = _re.compile(
    r"^[0-9A-Za-z]{8}-[0-9A-Za-z]{4}-[0-9A-Za-z]{4}-[0-9A-Za-z]{4}-[0-9A-Za-z]{12}$"
)


def _observations_by_source(results: Dict[str, Any], now: datetime) -> Dict[str, datetime]:
    """``{sensor id: when it was last observed}``, from the rows the data lanes returned.

    PER SENSOR, never pooled. Maxing over the whole result set let a live sensor certify a
    dead one: a CO2 answer resting on a two-day-old narrow row was recorded as forty seconds
    old because a wide-table row for an unrelated sensor shared the result set.

    Both table shapes are attributable, so nothing has to be guessed:

    * **narrow** ``(uuid, datetime, value)`` -- the row names its own sensor;
    * **wide** -- the uuid IS the column name, so every non-null uuid-shaped column is an
      observation of that sensor at the row's timestamp. A null column is not: counting it
      would date a silent sensor to whenever any sensor last reported.

    Only observing lanes are read. A booking's start time is a time, and treating it as an
    observation would make an answer about the future look like a fresh measurement.
    """
    out: Dict[str, datetime] = {}
    for lane in ("sql_result", "analytics_result"):
        for row in _rows_of(results.get(lane)):
            stamp: Optional[datetime] = None
            for key, value in row.items():
                if _TIME_COL_RE.search(str(key)):
                    dt = _as_datetime(value)
                    # Beyond a small clock-skew allowance it is a schedule, not a reading.
                    if dt is not None and (dt - now).total_seconds() <= _CLOCK_SKEW_S:
                        if stamp is None or dt > stamp:
                            stamp = dt
            if stamp is None:
                continue

            named = [
                str(k) for k, v in row.items() if v is not None and _UUID_SHAPE_RE.match(str(k))
            ]
            if not named:
                # Narrow shape: the row says which sensor it belongs to.
                uid = row.get("uuid") or row.get("sensor_uuid") or row.get("id")
                if uid is not None:
                    named = [str(uid)]
            if not named:
                # A row with a timestamp, some value and no way to attribute it. Recorded
                # under a sentinel so the evidence is not silently dropped, but kept
                # distinguishable from a named sensor.
                if not any(
                    v is not None for k, v in row.items() if not _TIME_COL_RE.search(str(k))
                ):
                    continue  # timestamp only -- not an observation of anything
                named = ["(unattributed)"]

            for uid in named:
                if uid not in out or stamp > out[uid]:
                    out[uid] = stamp
    return out


#: Gates that exist but have no input to judge. Recorded by name rather than run, because a
#: gate fed a field nothing populates returns the same failure for every answer in the system
#: -- which reads as caution and is actually noise. The value is the field each one waits on.
#: Empty: every gate now has an input. Kept as the mechanism, not deleted -- a gate added
#: later without its input must be recorded here rather than left silently absent, which is
#: how T13/T16/T17 came to be marked done while nothing invoked them (BUG-237).
_GATES_AWAITING_INPUT: Dict[str, str] = {}


def _modality_of(results: Dict[str, Any]) -> str:
    """Which modality this answer is about, from the BUILDING'S OWN modality config.

    Resolved by intersecting the Brick classes the question's concepts mapped to with the
    classes each configured modality declares, so a building that defines its own modalities
    in ``input/<id>/saturation_modalities.yaml`` is honoured and no modality name is hardcoded
    here. Returns "" when it cannot be established, and the policy's default age limit applies.
    """
    classes = set()
    for c in results.get("concepts") or []:
        raw = c.get("brick_classes", []) if isinstance(c, dict) else getattr(c, "brick_classes", [])
        for bc in raw or []:
            # Three notations reach here for the same class. The HBCO mapping stores full
            # IRIs, the resolver hands them on as CURIEs (`brick:CO2_Level_Sensor`), and the
            # modality config declares bare local names. Stripping only # and / left the
            # CURIE intact, so nothing matched and every modality fell back to the DEFAULT
            # age limit — CO2 was being judged at 15 minutes instead of its configured 5.
            local = str(bc).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
            classes.add(local.rsplit(":", 1)[-1])
    if not classes:
        return ""
    try:
        from orchestrator.services.deliberation.coverage_audit import load_modalities

        for spec in load_modalities(None):
            if set(spec.brick_classes) & classes:
                return spec.name
    except Exception as exc:  # config is optional; the default limit still applies
        logger.debug(f"[evidence] modality config unavailable: {exc}")
    return ""


def _is_current_status_question(results: Dict[str, Any], rec: EvidenceRecord) -> bool:
    """Does this answer claim something about NOW?

    Only present-tense questions can be stale. "What was the CO2 last March?" is not stale for
    March having been a while ago, and gating it would be nonsense.

    Decided from the time range the dialogue lane already extracted rather than from a phrase
    list: an explicit past window IS the question saying it is historical, and it is the same
    signal the SQL lane used to fetch the rows. A question with no window that OBSERVED
    something is asking about the present -- that is what "what's the CO2 in the theatre"
    means with nothing else said.
    """
    if rec.operation is not Operation.OBSERVATION:
        return False
    tr = results.get("time_range")
    if isinstance(tr, dict) and (tr.get("start") or tr.get("end")):
        return False
    # An observation with NO MEASURAND is geometry, not a reading. "How do I get to the
    # seminar room" and "which corridors are wide enough" are answered from the floor plan;
    # a corridor's width does not go stale, and flagging it produced "no  observation is
    # available for this space" — a verdict with an empty modality, which is the tell. Six of
    # the first 41 freshness advisories were this, and enforcing them would have refused
    # wayfinding answers for being insufficiently fresh.
    if not _modality_of(results):
        return False
    return True


def _latest_values_by_uuid(results: Dict[str, Any]) -> Dict[str, float]:
    """Each contributing sensor's most recent numeric value, from the rows on the bus.

    Same attribution rules as _observations_by_source: a narrow row names its sensor in a
    `uuid` column; in a wide row the uuid IS the column name; a null cell is not a reading.
    """
    latest: Dict[str, tuple] = {}  # uuid -> (stamp, value)
    for lane in ("sql_result", "analytics_result"):
        for row in _rows_of(results.get(lane)):
            stamp = None
            for key, value in row.items():
                if _TIME_COL_RE.search(str(key)):
                    dt = _as_datetime(value)
                    if dt is not None and (stamp is None or dt > stamp):
                        stamp = dt
            if stamp is None:
                continue
            wide = [
                (str(k), v)
                for k, v in row.items()
                if v is not None and _UUID_SHAPE_RE.match(str(k))
            ]
            if wide:
                pairs = wide
            else:
                uid = row.get("uuid") or row.get("sensor_uuid")
                val = row.get("value", row.get("reading"))
                pairs = [(str(uid), val)] if uid is not None and val is not None else []
            for uid, val in pairs:
                try:
                    num = float(val)
                except (TypeError, ValueError):
                    continue
                if uid not in latest or stamp > latest[uid][0]:
                    latest[uid] = (stamp, num)
    return {u: v for u, (_t, v) in latest.items()}


def _conflict_verdicts(results: Dict[str, Any], rec: EvidenceRecord) -> List[Any]:
    """Scenario 4 (V6-T18): when comparable sensors disagree, say so — never average it away.

    Grouped by the modality KIND the sparql lane already inferred per sensor, because that is
    the only comparability assertion available on the bus; the tolerance per modality comes
    from policy, where D-4 put every threshold. A set with no declared tolerance is left
    UNJUDGED, and unjudged is not agreement — ConflictReport.judged exists for that reason.
    """
    verdicts: List[Any] = []
    try:
        meta = results.get("sensor_metadata")
        if not isinstance(meta, dict) or len(meta) < 2:
            return verdicts
        values = _latest_values_by_uuid(results)
        if len(values) < 2:
            return verdicts

        from orchestrator.services.evidence.conflict import Reading, detect
        from orchestrator.services.evidence.gates import GateVerdict
        from orchestrator.services.evidence.policy import load_policy

        policy = load_policy()
        # Group by (modality, SPACE THE EVIDENCE IS ABOUT) — never by modality alone. The
        # first version grouped 90 different rooms' thermometers as one comparison and
        # reported the building's normal spatial variation as a 9.53-degree "conflict".
        # Scenario 4 is about sensors measuring the SAME thing; the only assertion of
        # same-thing-ness on the bus is the spatial grades' evidence_space, so sensors
        # without one are NOT judged. Silence over a fabricated disagreement.
        grades = results.get("_spatial_grades") or {}
        by_group: Dict[tuple, List[Reading]] = {}
        for uid, val in values.items():
            m = meta.get(uid) or {}
            kind = str(m.get("kind") or "").lower()
            space_of = str((grades.get(uid) or {}).get("evidence_space") or "")
            if not kind or not space_of:
                continue
            by_group.setdefault((kind, space_of), []).append(
                Reading(
                    sensor_id=uid,
                    value=val,
                    label=str(m.get("label") or ""),
                    unit=str(m.get("unit") or ""),
                )
            )
        for (kind, space_of), readings in by_group.items():
            if len(readings) < 2:
                continue
            report = detect(space_of, kind, readings, policy.agreement_tolerance(kind))
            if not report.judged:
                continue  # nothing to compare against — silence, not a clean bill
            if report.conflicting:
                # The extremes and the count, not all N readings: a ninety-line conflict
                # entry buries the two numbers that matter.
                lo = min(report.readings, key=lambda r: r.value)
                hi = max(report.readings, key=lambda r: r.value)
                rec.conflicts.append(
                    f"The {len(report.readings)} {kind} sensors covering "
                    f"{space_of.rsplit('#', 1)[-1]} disagree by {report.spread:g} "
                    f"(tolerance {report.tolerance:g}): {lo.describe()} while "
                    f"{hi.describe()}. Both are reported because averaging them would "
                    "produce a figure neither sensor measured."
                )
                verdicts.append(
                    GateVerdict(
                        "conflict",
                        False,
                        policy.gate_mode("conflict"),
                        report.reason,
                        remedy=(
                            "Both values are reported; averaging them would produce a figure "
                            "neither sensor measured. Check the drifting sensor."
                        ),
                        downgrade_to=AnswerStatus.INFERRED,
                        threshold=f"{report.tolerance:g}",
                    )
                )
    except Exception as exc:
        logger.debug(f"[evidence] conflict check skipped: {exc}")
    return verdicts


def _causal_verdict(results: Dict[str, Any], rec: EvidenceRecord) -> List[Any]:
    """Scenario 5 (V6-T33): a diagnosis phrased causally must have the support for it.

    Runs only on the diagnosis lane — its OUTPUT is the causal claim. Support is graded from
    what the record itself shows: two or more contributing series is correlation, and nothing
    on this bus asserts a mechanism, so MECHANISTIC is never claimed here. The caller-decides
    rule is causal_guard's own: inferring support from the prose would be the mistake the
    guard exists to catch.
    """
    verdicts: List[Any] = []
    try:
        diag = results.get("diagnosis_result")
        if not diag:
            return verdicts
        text = ""
        if isinstance(diag, dict):
            text = str(diag.get("response") or diag.get("answer") or diag.get("explanation") or "")
        elif isinstance(diag, str):
            text = diag
        if not text.strip():
            return verdicts

        from orchestrator.services.evidence.causal_guard import (
            causal_gate,
            support_from_evidence,
        )
        from orchestrator.services.evidence.policy import load_policy

        n_series = sum(1 for s in rec.sources if s.kind == "sensor") or len(
            results.get("sensor_metadata") or {}
        )
        support = support_from_evidence(series_compared=n_series)
        if hasattr(rec, "causal_support"):
            rec.causal_support = support
        verdicts.append(causal_gate(load_policy(), text, support))
    except Exception as exc:
        logger.debug(f"[evidence] causal guard skipped: {exc}")
    return verdicts


def _omissions_from_dossier(results: Dict[str, Any], rec: EvidenceRecord) -> None:
    """V6-T39: what a ranking left out becomes part of the record, not lane-private data.

    The deliberate lane already tracks every space it excluded and why; those entries died
    inside the dossier. Reason mapping is textual because the ledger stores prose — and the
    mapping is deliberately conservative: anything unrecognised is INADEQUATE_COVERAGE, the
    weakest claim, rather than a guessed stronger one.
    """
    try:
        dossier = results.get("evidence_dossier")
        if not isinstance(dossier, dict):
            return
        excluded = dossier.get("coverage_excluded") or []
        if not excluded:
            return
        from shared.models import OmissionReason, OmittedCriterion

        for e in excluded[:12]:
            if not isinstance(e, dict):
                continue
            space = str(e.get("space") or "").strip()
            reason_text = str(e.get("reason") or "").lower()
            if not space:
                continue
            if "restrict" in reason_text or "permission" in reason_text:
                reason = OmissionReason.RESTRICTED
            elif "stale" in reason_text or "old" in reason_text:
                reason = OmissionReason.STALE
            elif (
                "no data" in reason_text or "no reading" in reason_text or "missing" in reason_text
            ):
                reason = OmissionReason.MISSING
            else:
                reason = OmissionReason.INADEQUATE_COVERAGE
            rec.omitted_criteria.append(
                OmittedCriterion(criterion=space, reason=reason, detail=str(e.get("reason") or ""))
            )
    except Exception as exc:
        logger.debug(f"[evidence] dossier omissions skipped: {exc}")


def _trend_integrity_verdict(results: Dict[str, Any], rec: EvidenceRecord) -> List[Any]:
    """V6-T42/T07: a forecast or trend consults configuration history before claiming one.

    Every building currently declares ZERO effective-dated periods, so assess_trend returns
    REPORTABLE — by design, and its docstring argues why (unknown history must not make every
    trend unreportable; the gap belongs to the observability matrix). The value of wiring it
    NOW is that the day T65 authors periods, segmented and not-comparable verdicts start
    appearing with no further code change.
    """
    verdicts: List[Any] = []
    try:
        if not (results.get("forecast_result") or results.get("trend_result")):
            return verdicts
        from orchestrator.services.evidence.gates import GateVerdict
        from orchestrator.services.evidence.history import (  # noqa: F401
            ConfigurationPeriod,
        )
        from orchestrator.services.evidence.policy import load_policy
        from orchestrator.services.evidence.trend_integrity import (
            TrendVerdict,
            assess_trend,
        )

        tr = results.get("time_range") or {}
        start = _as_datetime(tr.get("start")) if isinstance(tr, dict) else None
        end = _as_datetime(tr.get("end")) if isinstance(tr, dict) else None
        if start is None or end is None:
            return verdicts
        periods = _configuration_periods(results)
        outcome = assess_trend(periods, start, end)
        if outcome.verdict is not TrendVerdict.REPORTABLE:
            verdicts.append(
                GateVerdict(
                    "trend_integrity",
                    False,
                    load_policy().gate_mode("trend_integrity"),
                    outcome.caveat or "a configuration change falls inside this window",
                    remedy="Compare segments either side of the change instead of one trend.",
                    downgrade_to=AnswerStatus.INFERRED,
                )
            )
    except Exception as exc:
        logger.debug(f"[evidence] trend integrity skipped: {exc}")
    return verdicts


def _configuration_periods(results: Dict[str, Any]):
    """Effective-dated location periods for the contributing sensors.

    Reads what a lane already fetched (`_config_periods` on the bus, when the sparql lane
    starts supplying it). Zero instances exist in any graph today, so this returns [] — the
    honest input for assess_trend, which treats it as no-known-changes rather than an error.
    """
    out = []
    try:
        from orchestrator.services.evidence.history import ConfigurationPeriod

        for entry in results.get("_config_periods") or []:
            if not isinstance(entry, dict):
                continue
            frm = _as_datetime(entry.get("effective_from"))
            if frm is None:
                continue
            out.append(
                ConfigurationPeriod(
                    subject=str(entry.get("subject") or ""),
                    location=str(entry.get("location") or "") or None,
                    effective_from=frm,
                    effective_to=_as_datetime(entry.get("effective_to")),
                    change=str(entry.get("change") or ""),
                )
            )
    except Exception as exc:
        logger.debug(f"[evidence] configuration periods unavailable: {exc}")
    return out


def _precedence_verdicts(results: Dict[str, Any], rec: EvidenceRecord) -> List[Any]:
    """V6-T21: a measurement never overrides a system of record, and disagreement is stated.

    Runs whenever more than one tier contributed. The winning tier is recorded on the answer
    so a reader can see WHAT KIND of thing answered them, which is half of R-7; the other
    half is that a lower-tier disagreement is narrated rather than dropped.
    """
    verdicts: List[Any] = []
    try:
        from orchestrator.services.evidence.gates import GateVerdict
        from orchestrator.services.evidence.policy import load_policy
        from orchestrator.services.evidence.precedence import (
            claims_from_sources,
            resolve,
        )

        if len(rec.sources) < 2:
            return verdicts
        policy = load_policy()
        claims = claims_from_sources(
            rec.sources, _latest_values_by_uuid(results), policy.source_tiers()
        )
        tiers = {c.tier for c in claims}
        if len(tiers) < 2:
            return verdicts  # one tier answered; nothing to order

        modality = _modality_of(results)
        verdict = resolve(claims, policy.agreement_tolerance(modality))
        rec.source_tier = verdict.winning_tier
        if verdict.disagreement:
            rec.conflicts.append(verdict.describe())
            verdicts.append(
                GateVerdict(
                    "source_precedence",
                    False,
                    policy.gate_mode("source_precedence"),
                    verdict.reason,
                    remedy=(
                        "The authoritative value leads; the lower-tier disagreement is "
                        "reported because it may indicate a fault or a no-show."
                    ),
                    downgrade_to=AnswerStatus.INFERRED,
                )
            )
    except Exception as exc:
        logger.debug(f"[evidence] precedence skipped: {exc}")
    return verdicts


def _permission_verdicts(results: Dict[str, Any], rec: EvidenceRecord) -> List[Any]:
    """V6-T22: an entitlement claim resting on a sensor is refused, with the route.

    Matched on the QUESTION, never the answer — BUG-213 showed what happens when a safety
    property depends on model output being well-formed. Silent when an authoritative source
    answered, and silent when the question is about the record itself (which the events lane
    answers properly, including "that system is not connected").
    """
    verdicts: List[Any] = []
    try:
        from orchestrator.services.evidence.gates import GateVerdict
        from orchestrator.services.evidence.permission_guard import assess
        from orchestrator.services.evidence.policy import load_policy
        from orchestrator.services.evidence.precedence import tier_for_kind

        question = str(results.get("original_query") or results.get("user_message") or "")
        if not question:
            return verdicts
        policy = load_policy()
        declared = policy.source_tiers()
        tiers = [tier_for_kind(str(getattr(s, "kind", "")), declared) for s in rec.sources]
        finding = assess(question, "authoritative" in tiers, tiers)
        if finding is None:
            return verdicts
        if not policy.entitlement_requires_authority(finding["kind"]):
            return verdicts
        rec.entitlement_claim = finding["kind"]
        verdicts.append(
            GateVerdict(
                "permission",
                False,
                policy.gate_mode("permission"),
                finding["reason"],
                remedy=finding["remedy"],
                # NOT_ASSESSABLE, not INFERRED: there is no weaker version of "this room is
                # free" that a sensor supports. The honest output is the route, not a hedge.
                downgrade_to=AnswerStatus.NOT_ASSESSABLE,
            )
        )
    except Exception as exc:
        logger.debug(f"[evidence] permission guard skipped: {exc}")
    return verdicts


def _calibration_state(entry: Optional[Dict[str, Any]], now: datetime) -> str:
    """`calibrated` / `expired` / `unknown` for one sensor (V6-T34).

    `unknown` is the default and is never upgraded by silence. A sensor with a calibration
    date but no due date counts as calibrated — a building that records the date and not the
    interval has still calibrated the instrument, and demanding both would refuse every
    building that does the common thing.
    """
    if not entry:
        return "unknown"
    due = _as_datetime(entry.get("due_on"))
    if due is not None:
        return "expired" if due < now else "calibrated"
    return "calibrated" if entry.get("calibrated_on") else "unknown"


def _calibration_verdicts(results: Dict[str, Any], rec: EvidenceRecord, now: datetime):
    """Scenario 7: no standards verdict from an instrument nobody has calibrated.

    The consequence class comes from the ROUTED INTENT — the system's own classification of
    the question shape, not the model's self-assessment. D-6 is explicit: letting the model
    grade how bad it would be to be wrong puts the safety property in the least reliable
    component, and BUG-213 is what that looks like in practice.
    """
    verdicts: List[Any] = []
    try:
        from orchestrator.services.evidence.gates import calibration_gate
        from orchestrator.services.evidence.policy import load_policy

        policy = load_policy()
        shape = str(results.get("intent") or "")
        consequence = policy.consequence_class(shape)
        rec.consequence_class = consequence
        # Record every sensor's calibration REGARDLESS of the claim's consequence. The gate
        # only judges calibration-sensitive claims, but a reader of a temperature answer is
        # still entitled to know the instrument's condition — and leaving the field at its
        # "unknown" default would be indistinguishable from an undeclared sensor, which is
        # the confusion this turn exists to remove.
        cal_all = results.get("_calibration") or {}
        for _s in rec.sources:
            if _s.kind == "sensor":
                _s.calibration_state = _calibration_state(cal_all.get(_s.source_id), now)
        _seen = [x.calibration_state for x in rec.sources if x.kind == "sensor"]
        if _seen:
            rec.calibration_state = (
                "expired"
                if "expired" in _seen
                else ("unknown" if "unknown" in _seen else "calibrated")
            )
        if not policy.requires_calibration(consequence):
            return verdicts  # not a calibration-sensitive claim; silence, not a pass

        if not _seen:
            return verdicts
        # The WEAKEST state governs: a verdict resting on five instruments is only as
        # defensible as the least defensible of them.
        verdicts.append(calibration_gate(policy, rec.calibration_state, consequence))
    except Exception as exc:
        logger.debug(f"[evidence] calibration gate skipped: {exc}")
    return verdicts


def _oldest_contributing(
    rec: EvidenceRecord, observed: Optional[Dict[str, datetime]] = None
) -> Optional[datetime]:
    """The stalest observation the answer rests on — what freshness must actually be judged on.

    `latest_evidence_at` answers "how new is the newest evidence", which is what a reader wants
    to know. It is the wrong question for a gate: one current sensor in a result set would
    vouch for every stale one beside it.

    The row-derived map is preferred over `rec.sources` because in production the lanes tag
    provenance by STORE (`store:co2_data`), not by sensor uuid — so a version of this that
    read only `rec.sources` found nothing to compare and quietly fell back to the maximum,
    which is the behaviour it was written to replace. Attribution has to come from wherever it
    actually exists, not from the shape the record was expected to have.
    """
    if observed:
        stamps = list(observed.values())
        if stamps:
            return min(stamps)
    src = [s.observed_at for s in rec.sources if s.kind == "sensor" and s.observed_at]
    if src:
        return min(src)
    return rec.latest_evidence_at


def _available_gates(
    results: Dict[str, Any],
    rec: EvidenceRecord,
    now: datetime,
    observed: Optional[Dict[str, datetime]] = None,
) -> List[Any]:
    """Run the gates whose inputs actually exist. Never raises: a gate that cannot run must
    not cost the answer the record describes."""
    verdicts: List[Any] = []
    try:
        from orchestrator.services.evidence.gates import freshness_gate, spatial_gate
        from orchestrator.services.evidence.policy import load_policy

        policy = load_policy()
        verdicts.append(
            freshness_gate(
                policy,
                _modality_of(results),
                # The OLDEST contributing observation, not the newest. An answer is only as
                # current as its stalest ingredient, and judging on the newest let a live
                # sensor certify a dead one -- a two-day-old CO2 reading passed as seconds
                # old because an unrelated wide-table row shared the result set.
                _oldest_contributing(rec, observed),
                now,
                is_current_question=_is_current_status_question(results, rec),
            )
        )
    except Exception as exc:
        logger.debug(f"[evidence] freshness gate skipped: {exc}")

    # V6-T17: how much of the requested window was actually observed. Runs ONLY when the
    # question carried an explicit window -- an unwindowed "right now" question is
    # freshness's jurisdiction, and scoring an observed span against itself would return
    # coverage ~1.0 by construction. Judged on the WORST covered contributing stream, the
    # same direction freshness takes: an aggregate is only as complete as its thinnest
    # ingredient. Streams with no declared cadence are COUNTED AND NAMED as unassessable,
    # never silently treated as complete.
    try:
        from orchestrator.services.evidence.completeness import assess
        from orchestrator.services.evidence.gates import completeness_gate
        from orchestrator.services.evidence.policy import load_policy

        tr = results.get("time_range") or {}
        w_start = _as_datetime(tr.get("start")) if isinstance(tr, dict) else None
        w_end = _as_datetime(tr.get("end")) if isinstance(tr, dict) else None
        if (
            w_start is not None
            and w_end is not None
            and rec.operation in (Operation.OBSERVATION, Operation.CALCULATION)
        ):
            cadences = results.get("_cadences") or {}
            stamps_by_uuid: Dict[str, List[datetime]] = {}
            for lane in ("sql_result", "analytics_result"):
                for row in _rows_of(results.get(lane)):
                    stamp = None
                    for key, value in row.items():
                        if _TIME_COL_RE.search(str(key)):
                            stamp = _as_datetime(value) or stamp
                    if stamp is None:
                        continue
                    named = [
                        str(k)
                        for k, v in row.items()
                        if v is not None and _UUID_SHAPE_RE.match(str(k))
                    ] or ([str(row.get("uuid"))] if row.get("uuid") else [])
                    for uid in named:
                        stamps_by_uuid.setdefault(uid, []).append(stamp)
            judged, unassessable = [], 0
            for uid, stamps in stamps_by_uuid.items():
                cad = cadences.get(uid)
                if not cad:
                    unassessable += 1
                    continue
                judged.append(assess(stamps, w_start, w_end, cad).coverage)
            worst = min((c for c in judged if c is not None), default=None)
            if judged or unassessable:
                if worst is not None:
                    rec.completeness = round(worst, 3)
                detail = ""
                if unassessable:
                    detail = (
                        f"worst-covered of {len(judged)} assessable stream(s); "
                        f"{unassessable} more declare no cadence and could not be assessed"
                    )
                verdicts.append(
                    completeness_gate(
                        load_policy(),
                        worst,
                        consequence_class="informational",
                        detail=detail,
                    )
                )
    except Exception as exc:
        logger.debug(f"[evidence] completeness gate skipped: {exc}")

    # V6-T13. Judged on the STRONGEST grade among the contributing points, which is the
    # opposite of freshness on purpose: freshness asks whether anything the answer rests on is
    # stale (the weakest link), while spatial adequacy asks whether ANY point genuinely covers
    # the space, because one in-room sensor is enough to make a room-level claim regardless of
    # how many corridor sensors came along with it.
    try:
        from orchestrator.services.evidence.gates import spatial_gate
        from orchestrator.services.evidence.policy import load_policy

        grades = results.get("_spatial_grades") or {}
        if grades:
            order = {
                SpatialAdequacy.IN_ROOM: 3,
                SpatialAdequacy.SERVED_ZONE: 2,
                SpatialAdequacy.PROXY: 1,
                SpatialAdequacy.NONE: 0,
            }
            best, reason = SpatialAdequacy.NONE, ""
            for g in grades.values():
                try:
                    cand = SpatialAdequacy(str(g.get("grade")))
                except ValueError:
                    continue
                if order[cand] > order[best]:
                    best, reason = cand, str(g.get("reason") or "")
            verdicts.append(
                spatial_gate(
                    load_policy(),
                    best,
                    rec.spatial_scope or "space",
                    proxy_reason=reason,
                )
            )
    except Exception as exc:
        logger.debug(f"[evidence] spatial gate skipped: {exc}")
    return verdicts


def build_evidence_record(
    results: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
    gate_verdicts: Sequence[Any] = (),
) -> EvidenceRecord:
    """Assemble one record from everything the lanes left behind.

    `gate_verdicts` are applied here rather than in each lane so that the status an answer
    ends up with, and the list of gates that shaped it, are decided in exactly one place.
    """
    now = now or datetime.now(timezone.utc)
    rec = EvidenceRecord(retrieved_at=now)

    # A lane may hand up a partial record; anything it set wins over inference, because the
    # lane knows things the bus does not.
    partial = results.get("evidence") if isinstance(results.get("evidence"), dict) else {}

    lane = infer_lane(results)
    if lane:
        for key, op, status in _LANE_SEMANTICS:
            if key == lane:
                rec.operation = op
                rec.status = status
                break
    elif any(results.get(k) for k in _REFUSAL_LANES):
        # A refusal lane is a CORRECT outcome, and its reason is the answer.
        rec.status = AnswerStatus.NOT_ASSESSABLE
        rec.not_assessable_reason = "this question was declined by policy"
    else:
        rec.status = AnswerStatus.NOT_ASSESSABLE
        rec.not_assessable_reason = (
            "no lane produced evidence for this answer, so nothing supports it"
        )

    ents = results.get("entities") or []
    if ents and isinstance(ents, list):
        rec.interpreted_location = str(ents[0])
    tr = results.get("time_range") or {}
    if isinstance(tr, dict) and (tr.get("start") or tr.get("end")):
        rec.requested_period = f"{tr.get('start') or 'unbounded'} to {tr.get('end') or 'now'}"
    # V6-T40: a recurring window is part of WHAT WAS ASKED, and an answer that hides it
    # reads as though it covered all hours. The sql lane reports the mask it applied.
    _mask = (
        (results.get("sql_result") or {}).get("window_mask")
        if isinstance(results.get("sql_result"), dict)
        else ""
    )
    if _mask:
        rec.requested_period = (
            f"{rec.requested_period} ({_mask} only)" if rec.requested_period else f"{_mask} only"
        )

    rec.sources = _sources_from(results)
    # A report turn has no instrument behind it, so the generic provenance lift finds
    # nothing and the record would claim no sources at all — "nothing backed this
    # answer", when a person did (TODO-229).
    _hr = _human_report_source(results)
    if _hr is not None and not any(s.kind == "human_report" for s in rec.sources):
        rec.sources.append(_hr)
    if rec.sources:
        observed = [s.observed_at for s in rec.sources if s.observed_at]
        if observed:
            rec.latest_evidence_at = max(observed)

    # V6-T03: if no lane declared a per-source observation time, read it off the rows the data
    # lanes actually returned. Until this existed, latest_evidence_at was ALWAYS None -- the
    # field was documented, read by the freshness gate, and never written -- so an answer built
    # on a seven-week-old reading was indistinguishable from one taken a minute ago.
    # V6-T13: each source carries its own grade, so a reader holding one does not have to
    # infer from a record-level summary whether THAT sensor covered the space.
    _grades = results.get("_spatial_grades") or {}
    if _grades:
        for s in rec.sources:
            g = _grades.get(s.source_id)
            if not g:
                continue
            try:
                s.spatial_adequacy = SpatialAdequacy(str(g.get("grade")))
            except ValueError:
                continue

    observed = _observations_by_source(results, now)
    if observed:
        # Attribute to the sensor that was actually observed. Anything the rows could not
        # attribute applies to sensor sources that have no time of their own -- better than
        # discarding real evidence, and it can never overwrite an attributed one.
        fallback = observed.get("(unattributed)")
        for s in rec.sources:
            if s.kind != "sensor" or s.observed_at is not None:
                continue
            s.observed_at = observed.get(s.source_id) or fallback
        if rec.latest_evidence_at is None:
            stamps = [s.observed_at for s in rec.sources if s.observed_at] or [
                v for k, v in observed.items() if k != "(unattributed)"
            ]
            if not stamps and fallback:
                stamps = [fallback]
            if stamps:
                # The field means "newest observation behind the answer". The freshness gate
                # deliberately asks a DIFFERENT question -- see _oldest_contributing.
                rec.latest_evidence_at = max(stamps)

    # Whatever the lane asserted overrides inference.
    for field_name, value in (partial or {}).items():
        if value is None or not hasattr(rec, field_name):
            continue
        try:
            setattr(rec, field_name, value)
        except Exception:
            continue

    # V6-T16: run the gates whose inputs exist, and union them with anything a lane supplied.
    # Advisory by default (policy.gate_mode), so this records verdicts without moving a single
    # answer -- the shadow-mode discipline every V6 tightening goes through.
    gate_verdicts = list(gate_verdicts or []) + _available_gates(results, rec, now, observed)
    # Wave A (audit 2026-08-23): the gates below were built, tested and never called.
    gate_verdicts += _conflict_verdicts(results, rec)  # T18, scenario 4
    gate_verdicts += _precedence_verdicts(results, rec)  # T21, rule R-7
    gate_verdicts += _permission_verdicts(results, rec)  # T22, rule R-8
    gate_verdicts += _calibration_verdicts(results, rec, now)  # T34, scenario 7
    gate_verdicts += _causal_verdict(results, rec)  # T33, scenario 5
    gate_verdicts += _trend_integrity_verdict(results, rec)  # T42/T07, scenario 3 groundwork
    _omissions_from_dossier(results, rec)  # T39

    # V6-T36: whether the recommendation has a backup that can fail independently.
    try:
        _bk = results.get("_backup_verdict") or {}
        if _bk:
            rec.backup_independent = bool(_bk.get("independent"))
            if not _bk.get("independent") and _bk.get("reason"):
                rec.omitted_criteria.append(
                    OmittedCriterion(
                        criterion="independent backup",
                        reason=OmissionReason.NOT_INSTRUMENTED,
                        detail=str(_bk.get("reason")),
                    )
                )
    except Exception as exc:
        logger.debug(f"[evidence] backup verdict skipped: {exc}")

    # T28: which access tier answered. Description, not enforcement -- RBAC still gates the
    # data; the record now states the tier so cross-role consistency (scenario 8) is checkable.
    try:
        from orchestrator.services.evidence.access_tiers import tier_for_role

        role = str(results.get("user_role") or "")
        if role:
            rec.access_tier = tier_for_role(role).name
    except Exception as exc:
        logger.debug(f"[evidence] access tier skipped: {exc}")

    # Name the gates that did NOT run and why. A gate silently absent is indistinguishable
    # from a gate that passed, and that is how three of these came to be marked done.
    rec.gates_not_evaluated = [f"{g}: {why}" for g, why in _GATES_AWAITING_INPUT.items()]

    # Gates last: they can only ever restrict.
    if gate_verdicts:
        try:
            from orchestrator.services.evidence.gates import apply as apply_gates

            # Union, not overwrite: a lane may have declared a gate of its own on the
            # evidence partial (CAVEAT-226 -- the retrieval floor names itself when it
            # suppresses every candidate), and replacing the list would silently discard it,
            # putting the record back to being unable to explain its own change.
            _declared = list(rec.gates_applied or [])
            _fired = [v.gate for v in gate_verdicts if getattr(v, "blocks", False)]
            rec.gates_applied = _declared + [g for g in _fired if g not in _declared]

            # An ADVISORY failure changes no answer, so unless it is recorded here it leaves no
            # trace at all -- and shadow mode exists precisely to be read before enforcing.
            rec.gates_advisory = [
                f"{v.gate}: {v.reason}"
                for v in gate_verdicts
                if getattr(v, "advisory_failure", False)
            ]
            rec.status = apply_gates(gate_verdicts, rec.status)
            blocked = [v for v in gate_verdicts if getattr(v, "blocks", False)]
            if blocked and rec.status is AnswerStatus.NOT_ASSESSABLE:
                rec.not_assessable_reason = blocked[0].reason
                rec.remedy = blocked[0].remedy
        except Exception as exc:
            logger.debug(f"[evidence] gate application skipped: {exc}")

    return rec


def record_for_response(
    results: Dict[str, Any], *, gate_verdicts: Sequence[Any] = ()
) -> Dict[str, Any]:
    """The serialisable record for the API response. Never raises.

    A describer that can break the thing it describes is worse than none, so every failure
    path here still returns a well-formed record saying the assembly failed -- which is
    itself accurate.
    """
    try:
        rec = build_evidence_record(results, gate_verdicts=gate_verdicts)
        return rec.model_dump(mode="json")
    except Exception as exc:
        logger.warning(f"[evidence] record assembly failed: {exc}")
        return EvidenceRecord(
            status=AnswerStatus.NOT_ASSESSABLE,
            not_assessable_reason=f"evidence record could not be assembled: {exc}",
        ).model_dump(mode="json")
