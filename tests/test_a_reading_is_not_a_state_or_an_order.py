# -*- coding: utf-8 -*-
"""A reading is a number: it is not a capacity, a state, or an order of work.

Three P1 rows, one defect. A free-text model narration was handed rows of
``(uuid, timestamp, value)`` and asked to answer a question those rows cannot answer, so it
supplied the missing part:

* **BUG-1302** tabled five *"Overcrowded areas"* against *"exceed 10 occupants"* — a threshold
  that exists nowhere in this building — with all five places "sensor name not recorded".
* **BUG-1332** narrated the six static ``ontosage:MaintenanceIssue`` KnowledgeTopics, a
  taxonomy of what a user *can report* carrying no timestamp and no status, as *"six active
  issues … the only recorded problems at the moment"*. Asked four times: four wrong answers.
* **BUG-709** put *"never issue an instruction, a plan, a recovery order or a priority"* in a
  prompt on 2026-09-18. On the fourth ask of BUG-1332 the model wrote a five-step
  *"Recommended recovery sequence (dependency-aware)"* addressed to an incident leader —
  *"Restore power to both chargers"*, *"Verify … before allowing occupants to enter"* — built
  from a charger occupancy point read as "available". **The prompt rule held three times of
  four.** That is the whole reason this file exists: a rule that must hold every time cannot
  live only in a prompt.

The measured live failures are quoted VERBATIM below, so a future change that stops catching
one of them fails here rather than in front of a reader.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import pytest

from orchestrator.services.anomaly.narration_guard import (
    REPORT_LANE_FAMILIES,
    reading_lane_claims,
    rows_record_a_state,
)

REPO = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------------------
# The measured live failures, verbatim.
# --------------------------------------------------------------------------------------

BUG_1332_ORIGINAL = (
    "The building records show **six active issues** that incident leaders will need to "
    "address: Water leak / leakage; Broken or faulty light; Lift out of order; Heating fault "
    "/ room too cold; Blocked or broken toilet; Broken door / access control fault. These are "
    "the only recorded problems at the moment."
)

BUG_1332_RUN2 = (
    "The snapshot shows six priority-service issues; these are the only issues currently " "listed."
)

BUG_1332_RUN3 = (
    "There are six active issues in the records — the only issues recorded at the moment."
)

BUG_1332_RUN1_PROCEDURE = (
    "**Recommended recovery sequence (dependency-aware)**\n"
    "1. Safety first - Intruder detectors. Ensure all intruder-detector zones (Floor 0 Zone "
    "A, Zone B, Floors 2-5) are powered and reporting.\n"
    "2. Power to critical equipment - EV chargers. Restore power to both chargers.\n"
    "3. Re-open high-priority meeting spaces. Verify that HVAC and lighting for these rooms "
    "are functional before allowing occupants to enter.\n"
    "4. Restore seminar rooms that are currently free.\n"
    "5. Re-establish occupancy monitoring for high-traffic floors."
)

#: The fifth ask, 2026-10-01 00:07, occupant01 on /v1 streaming, lane=sensor_data, 123.6 s.
BUG_1332_ASK5 = (
    "**Recommended recovery sequence (dependency-aware, based on the latest sensor snapshot "
    "and the overall statistics)**\n\n"
    "| Step | What to restore | Why it comes first |\n"
    "| 2 | **Critical power & charging** - EV Charger 2 | Power is required for all other "
    "services. Restoring power to this charger ensures that any critical equipment (e.g., "
    "servers, elevators) can be powered. |"
)

BUG_1302 = (
    "**Overcrowded areas (as of 2026-09-30 21:19:27)**\n"
    "| Area (sensor name) | Occupancy | Unit |\n"
    "| sensor name not recorded | 11.0 | not recorded |\n"
    "These five areas are the only ones in the latest snapshot that exceed 10 occupants, "
    "indicating they are currently overcrowded."
)

BUG_1298 = (
    "This suggests the area is currently overcrowded and exceeding safe capacity limits. "
    "Immediately activate the building's crowd-control protocol -- close adjacent access "
    "points, redirect foot traffic, and alert security."
)


class TestEveryMeasuredFailureIsCaught:
    @pytest.mark.parametrize(
        "name,text,expected_phrase",
        [
            ("1332 original", BUG_1332_ORIGINAL, "six active issues"),
            ("1332 run 2", BUG_1332_RUN2, "the only issues"),
            ("1332 run 3", BUG_1332_RUN3, "six active issues"),
            ("1332 run 1 procedure", BUG_1332_RUN1_PROCEDURE, "recommended recovery sequence"),
            ("1332 ask 5", BUG_1332_ASK5, "what to restore"),
            ("1302", BUG_1302, "exceed 10 occupants"),
            ("1298", BUG_1298, "crowd-control"),
        ],
    )
    def test_caught(self, name, text, expected_phrase):
        hits = reading_lane_claims(text, ())
        joined = " | ".join(h.lower() for h in hits)
        assert hits, f"{name} was not caught at all"
        assert expected_phrase in joined, f"{name}: {joined}"

    def test_the_procedure_is_caught_at_every_step_not_only_its_heading(self):
        """Deleting the heading must not smuggle the steps past."""
        hits = " | ".join(h.lower() for h in reading_lane_claims(BUG_1332_RUN1_PROCEDURE, ()))
        for step in (
            "ensure all intruder-detector zones",
            "restore power",
            "re-open high-priority meeting spaces",
            "before allowing occupants to enter",
            "re-establish occupancy monitoring",
        ):
            assert step in hits, step

    def test_both_capacity_claims_in_the_1302_text_are_named(self):
        hits = " | ".join(h.lower() for h in reading_lane_claims(BUG_1302, ()))
        assert "overcrowded" in hits
        assert "exceed 10 occupants" in hits


class TestItDoesNotActTooWidely:
    """Lesson #135, for the fourth time in this repository."""

    @pytest.mark.parametrize(
        "sentence",
        [
            # The answer the guard exists to PROTECT (BUG-1298's ask 8, hand-read as the
            # intended behaviour): a bare observed count, labelled as observed.
            "10.00 people was the highest count observed. The lowest count recorded was 0.00 "
            "people, giving a spread of 10.00 people.",
            # A series' own statistics. An earlier draft of the occupancy-limit family matched
            # `minimum of 450.0` and hit six hand-read-GOOD report answers.
            "The CO2 sensor in room 5.01 recorded 2,681 readings, with an average of 767.6 "
            "ppm, a minimum of 450.0 ppm and a maximum of 1,101.0 ppm.",
            "Floor 0 Zone A: 60 readings; min 0, mean 0.983, max 1 people; latest 1 at 23:33.",
            "Energy use reached a single-day maximum of 6.21 kWh, above the daily mean.",
            # The word alone is not a claim.
            "The ventilation capacity is unchanged and this is not a capacity issue.",
            "Occupancy Status rose from 0.0 to 1.0 between 22:10 and 22:15.",
            "No readings were returned for the period you asked about.",
            # The anomaly lane's prompt asks for an INVESTIGATION step, and should get one.
            "Recommended investigation steps: cross-check the sensor against a second one.",
            "Recommended investigation: compare this against the neighbouring sensor.",
        ],
    )
    def test_a_clean_reading_narration_is_untouched(self, sentence):
        assert reading_lane_claims(sentence, ()) == []

    def test_a_plant_capacity_is_not_an_occupancy_claim(self):
        """Measured: 2 of the 4 reading-lane hits in the stored corpus were this sentence.

        A delta-T answer, hand-readable as fine, about thermal output. Replacing it with a
        bullet list of statistics would be the defect this guard is written to avoid.
        """
        assert (
            reading_lane_claims(
                "A delta-T of 8-9 C is slightly below the typical target but still within a "
                "healthy operating range. The system is functioning, though you might want "
                "to check whether the boilers are running at full capacity during peak "
                "demand.",
                (),
            )
            == []
        )

    def test_a_space_at_capacity_is_still_caught(self):
        """The plant exclusion must not become a way through."""
        assert reading_lane_claims("Room 5.01 is at full capacity.", ())
        assert reading_lane_claims(
            "Several rooms and floors are operating near or at their typical maximum " "occupancy.",
            (),
        )

    @pytest.mark.parametrize(
        "refusal",
        [
            # BOTH OF THESE WERE DESTROYED BY THIS GUARD, at the lane, with the real local
            # model, on 2026-10-01 -- and both are the behaviour the new prompt rules were
            # written to produce. The guard was the bug, for the third time in this repo.
            "These figures reflect the most recent measurements. No capacity limits or "
            "thresholds were supplied, so no assessment of overcrowding or safety limits "
            "can be made.",
            "I don't have any capacity or limit information for the building, so I can't say "
            "whether any area is overcrowded.",
            "Because no capacity or threshold figures are available, I can't determine "
            "whether any of these areas are overcrowded.",
            # The register/control decline wordings, same shape.
            "The building model doesn't contain any information about occupancy limits or "
            "alarm behaviour.",
            "No capacity figure is recorded for this space, so it cannot be called " "overcrowded.",
            "The records do not record any open issues at the moment.",
            "No recovery order is recorded, so none can be given.",
        ],
    )
    def test_a_refusal_that_names_the_claim_is_not_the_claim(self, refusal):
        assert reading_lane_claims(refusal, ()) == [], refusal

    def test_a_negation_is_not_a_general_escape_hatch(self):
        """The frame is epistemic, not any `not`: a claim beside a disclaimer still counts."""
        assert reading_lane_claims(
            "The unit is not recorded. The area is not merely busy, it is overcrowded.", ()
        )
        # A markdown table cell saying "not recorded" must not excuse the prose below it --
        # BUG-1302's own answer had "sensor name not recorded" on five rows.
        assert reading_lane_claims(BUG_1302, ())


class TestScopeIsMeasuredNotAssumed:
    """BUG-1302's row calls this module "lane-agnostic … a two-line call". It is not."""

    @pytest.mark.parametrize(
        "sentence",
        [
            # All five are verbatim from hand-read-GOOD stored answers on the capability and
            # register lanes. The original family B matched `evacuat\\w+` and destroyed them.
            "Intercom at refuge point (for the evacuation route, record RTE-013).",
            "From Abacws Building's documents: Evacuation And Peeps.",
            "EV-006 - Evacuation chair - Level 3 north stair - owner: Building Fire Warden "
            "Coordinator; status: active.",
            "Among the 12 evacuation-provision records, 4 refuge points are active and 1 is "
            "defective.",
            "Public address system for evacuation instructions. Assembly point: the open area "
            "on Senghennydd Road directly outside the main entrance.",
        ],
    )
    def test_a_recorded_evacuation_fact_is_not_an_instruction(self, sentence):
        assert reading_lane_claims(sentence, []) == []

    def test_an_evacuation_instruction_is_still_caught(self):
        for sentence in (
            "The floor should be evacuated.",
            "Evacuate the building immediately.",
            "An evacuation is advised.",
            "We recommend an evacuation of the affected floor.",
        ):
            assert reading_lane_claims(sentence, []), sentence

    def test_the_register_lanes_are_not_wired_to_this_guard(self):
        """The 11 hand-read-GOOD answers it would alter all live on those lanes."""
        for module in (
            "orchestrator/services/record_registry.py",
            "orchestrator/agents/capability_agent.py",
            "orchestrator/agents/sparql_agent.py",
        ):
            src = (REPO / module).read_text(encoding="utf-8", errors="replace")
            assert "reading_lane_claims" not in src, module


class TestTheInvariantsAreStatedOnTheRows:
    """A future lane that DOES carry the fact must lift the family, not inherit a ban."""

    def test_a_status_bearing_row_stands_the_live_state_family_down(self):
        rows = [{"uuid": "u", "value": 1.0, "status": "open"}]
        assert rows_record_a_state(rows) is True
        assert reading_lane_claims(BUG_1332_ORIGINAL, rows) == []

    def test_a_reading_row_records_no_state(self):
        rows = [{"timestamp": "2026-10-01T00:00:00", "uuid": "u", "value": 0.0}]
        assert rows_record_a_state(rows) is False
        assert reading_lane_claims(BUG_1332_ORIGINAL, rows)

    def test_a_capacity_bearing_row_stands_the_occupancy_limit_family_down(self):
        rows = [{"uuid": "u", "value": 11.0, "room_capacity": 24}]
        assert reading_lane_claims(BUG_1302, rows) == []


# --------------------------------------------------------------------------------------
# The sql lane's action: the facts, never a decline.
# --------------------------------------------------------------------------------------

READINGS = [
    {"timestamp": f"2026-09-30T2{2 + i // 6}:{(i * 7) % 60:02d}:00", "uuid": "u1", "value": 10 + i}
    for i in range(12)
]
META = {"u1": {"label": "Occupancy Count Sensor - Floor 1", "unit": "people"}}


def _narrate(reply: str, rows=None, meta=None) -> str:
    """Run the sql lane's formatter with the model stubbed to return ``reply``."""
    from orchestrator.agents import sql_agent as mod

    async def _fake(prompt, task_type=None):
        return reply

    original = mod.llm_manager.generate
    mod.llm_manager.generate = _fake
    try:
        agent = mod.SQLAgent.__new__(mod.SQLAgent)
        return asyncio.run(
            agent._format_results(
                rows if rows is not None else READINGS,
                "which areas are currently overcrowded?",
                "SELECT 1",
                META if meta is None else meta,
            )
        )
    finally:
        mod.llm_manager.generate = original


class TestTheSqlLaneReplacesTheNarrationWithTheFacts:
    def test_a_clean_narration_is_returned_unchanged(self):
        clean = "The highest count observed was 21 people at 23:17."
        assert _narrate(clean) == clean

    def test_the_1302_narration_is_replaced(self):
        out = _narrate(BUG_1302)
        assert "exceed 10 occupants" not in out
        assert "Overcrowded areas" not in out

    def test_the_1332_narration_is_replaced(self):
        out = _narrate(BUG_1332_ORIGINAL)
        assert "six active issues" not in out.lower()
        assert "at the moment" not in out.lower()

    def test_the_recovery_procedure_is_replaced(self):
        out = _narrate(BUG_1332_RUN1_PROCEDURE)
        assert "restore power" not in out.lower()
        assert "recovery sequence" not in out.lower()

    def test_the_replacement_is_not_a_decline_and_keeps_every_figure(self):
        """The reader must still get the readings. A guard that costs the answer is worse."""
        out = _narrate(BUG_1302)
        assert "I couldn't answer" not in out
        assert "could not" not in out.lower() or "No conclusion has been drawn" in out
        assert "No conclusion has been drawn from them" in out
        # The sensor's readable name, its unit and its own statistics survive.
        assert "Occupancy Count Sensor - Floor 1" in out
        assert "people" in out
        assert "21" in out, "the maximum reading must still be visible"
        assert "12 record(s)" in out

    def test_the_model_being_unreachable_uses_the_same_facts_path(self):
        """Two paths that can drift apart will drift apart."""
        from orchestrator.agents import sql_agent as mod

        async def _boom(prompt, task_type=None):
            raise RuntimeError("ollama down")

        original = mod.llm_manager.generate
        mod.llm_manager.generate = _boom
        try:
            agent = mod.SQLAgent.__new__(mod.SQLAgent)
            out = asyncio.run(agent._format_results(READINGS, "how busy is it?", "SELECT 1", META))
        finally:
            mod.llm_manager.generate = original
        assert "No conclusion has been drawn from them" in out
        assert "Occupancy Count Sensor - Floor 1" in out


class TestThePromptStillCarriesTheRequest:
    """The guard is not a licence to drop the prompt rule; both are wanted."""

    def test_the_narration_prompt_forbids_a_threshold_a_state_and_an_order(self):
        from orchestrator.agents.sql_agent import SQLAgent

        # Normalised: `black` wraps a long string across lines and a contiguous-substring
        # assert then fails on correctly wired code (lessons #151).
        src = " ".join(inspect.getsource(SQLAgent._format_results).split())
        for fragment in (
            "NO CAPACITY, LIMIT OR THRESHOLD WAS SUPPLIED TO YOU",
            "A READING IS A NUMBER, NOT A STATE",
            "NEVER TELL ANYONE WHAT TO DO",
        ):
            assert fragment in src, fragment

    def test_the_guard_runs_after_the_model_not_instead_of_it(self):
        from orchestrator.agents.sql_agent import SQLAgent

        src = inspect.getsource(SQLAgent._format_results)
        assert src.index("llm_manager.generate") < src.index("reading_lane_claims")


class TestTheReportLaneKeepsItsRecommendations:
    """Scoping the families is part of the guard, not an oversight."""

    def test_the_operational_order_family_is_not_applied_to_a_report(self):
        assert "operational_order" not in REPORT_LANE_FAMILIES
        recommendation = (
            "Investigate the 6.21 kWh peak at 18 Sep 15:46. The energy meter shows a "
            "single-day maximum of 6.21 kWh, far above the daily mean of 4.5 kWh. Check the "
            "schedule of the equipment that runs then, and dispatch a technician if it "
            "should be restored to its normal profile."
        )
        assert reading_lane_claims(recommendation, (), families=REPORT_LANE_FAMILIES) == []
        # ...and the full guard WOULD have stripped it, which is why the scope exists.
        assert reading_lane_claims(recommendation, ())

    def test_a_report_may_not_escalate_to_people_or_claim_a_capacity(self):
        for sentence in (
            "Alert security and evacuate the building.",
            "Floor 3 is over its maximum occupancy.",
            "Six active issues are outstanding at the moment.",
        ):
            assert reading_lane_claims(sentence, (), families=REPORT_LANE_FAMILIES), sentence

    def test_the_report_lane_calls_the_guard_with_the_report_families(self):
        from orchestrator.agents.report_agent import ReportAgent

        src = " ".join(inspect.getsource(ReportAgent._narrate).split())
        assert "families=REPORT_LANE_FAMILIES" in src


# --------------------------------------------------------------------------------------
# Blast radius, over every stored answer this repository holds.
# --------------------------------------------------------------------------------------

_READING_LANES = {"sensor_data", "sql", "analytics", "compare", "trend", "anomaly", "forecast"}
_REPORT_LANES = {"report", "recommend"}
_GOOD = ("GOOD_ANSWER", "GOOD_DECLINE")


def _stored_answers():
    """(answer, lane, hand-read verdict) for the 73-probe pack + every docs/phase0 jsonl."""
    files = [
        REPO / "Datasets" / "System evaluation" / "Evidence pack - 73 probes" / "answers.jsonl"
    ]
    files += sorted((REPO / "docs" / "phase0").glob("*.jsonl"))
    out = []
    for path in files:
        if not path.exists() or path.name.endswith("_read.jsonl"):
            continue
        verdicts = {}
        sibling = path.with_name(path.name[: -len(".jsonl")] + "_read.jsonl")
        if sibling.exists():
            for i, line in enumerate(
                sibling.read_text(encoding="utf-8", errors="replace").splitlines()
            ):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    key = row.get("row")
                    verdicts[key if isinstance(key, int) else i] = str(row.get("verdict") or "")
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines()):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            answer = row.get("answer") or row.get("response") or ""
            if not isinstance(answer, str) or not answer.strip():
                continue
            out.append(
                (
                    answer,
                    str(row.get("lane") or row.get("route") or ""),
                    str(row.get("verdict") or row.get("label") or verdicts.get(i, "")),
                    f"{path.name}:{i + 1}",
                )
            )
    return out


@pytest.fixture(scope="module")
def stored():
    rows = _stored_answers()
    if len(rows) < 2000:
        pytest.skip(f"the stored-answer corpus is not present in full ({len(rows)} rows)")
    return rows


class TestBlastRadiusOverTheStoredAnswers:
    """A guard that rewrites correct answers is worse than the defect it was built for.

    Measured 2026-10-01 over **2,912** stored answers, 1,465 of them hand-read:

    ===============================  ======  ==========
    scope                            altered  GOOD lost
    ===============================  ======  ==========
    lane-blind (all 2,912)               22          11
    recorded reading lane (295)           2           0
    recorded report/recommend (58)        0           0
    ===============================  ======  ==========

    The 11 are the reason the guard is scoped: every one is a ``capability`` or register
    answer QUOTING a recorded procedure — *"press the refuge intercom to alert security"*,
    *"contact Security Services"*, *"Evacuate the room and isolate ventilation; await
    contractor"* — which is the one thing a reading lane never does.
    """

    def test_no_good_reading_lane_answer_is_altered(self, stored):
        casualties = [
            (src, reading_lane_claims(answer, ()))
            for answer, lane, verdict, src in stored
            if lane in _READING_LANES and verdict in _GOOD and reading_lane_claims(answer, ())
        ]
        assert casualties == [], f"the guard would rewrite {len(casualties)} GOOD answers"

    def test_no_report_lane_answer_is_altered(self, stored):
        casualties = [
            (src, reading_lane_claims(answer, (), families=REPORT_LANE_FAMILIES))
            for answer, lane, verdict, src in stored
            if lane in _REPORT_LANES
            and reading_lane_claims(answer, (), families=REPORT_LANE_FAMILIES)
        ]
        assert casualties == [], f"the report families would rewrite {len(casualties)} answers"

    def test_the_reading_lane_exposure_is_small_and_pinned(self, stored):
        """Two answers, both already hand-read WEIRD. If this number moves, read the rows."""
        hit = [
            (src, verdict)
            for answer, lane, verdict, src in stored
            if lane in _READING_LANES and reading_lane_claims(answer, ())
        ]
        assert len(hit) <= 4, hit
        assert all(v != "GOOD_ANSWER" and v != "GOOD_DECLINE" for _, v in hit), hit

    def test_the_noun_only_families_would_have_been_a_disaster(self, stored):
        """The measurement that decided the design, kept as a test so it stays true.

        The pre-2026-10-01 family B matched ``evacuat\\w+``. Wired lane-blind, as BUG-1302's
        row proposed ("lane-agnostic by construction … a two-line call"), it would have
        rewritten the scripted answer to *"What is the evacuation procedure?"*.
        """
        import re

        noun = re.compile(r"evacuat\w+", re.I)
        good_casualties = [
            src for answer, lane, verdict, src in stored if verdict in _GOOD and noun.search(answer)
        ]
        # 19 hand-read-GOOD answers, measured 2026-10-01. The number is a lower bound on
        # purpose: if a later corpus holds fewer, the lesson has been lost, not disproved.
        assert len(good_casualties) >= 19, (
            "this test is the record of why the noun was replaced by the instruction; "
            f"it found only {len(good_casualties)}"
        )
        assert any("What is the evacuation procedure" not in c for c in good_casualties)
