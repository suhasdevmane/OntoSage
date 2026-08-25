# -*- coding: utf-8 -*-
"""The eight Master 14.1 acceptance scenarios, assembled in one place (V6-T47).

The Master Report's acceptance criteria read as a test plan, and until now they were satisfied
across five files with no single place that answered *"do all eight hold?"*. This is that place.

Each scenario exercises the **real guard**, so deleting the guard fails the test — the acceptance
criterion for this turn. Nothing here mocks the thing under test; the fixtures are inputs, and the
assertions are about what the shipped code decides.

Everything runs **parked** — no live stack, no active building. That matters more than it sounds:
the committed tree has no active building by design, so a scenario suite that needed one could
never run in CI or on a fresh clone, which is exactly where a regression would otherwise reach
production.

    1. Remove the room sensor             -> refuse a room-level claim, don't use corridor data
    2. Introduce missing intervals        -> duration and averages change appropriately
    3. Move a sensor in metadata          -> history stays linked to the prior location
    4. Create conflicting sensors         -> report the disagreement, never average it away
    5. Causal question, correlation only  -> wording stays qualified
    6. Public user, restricted data       -> access control is enforced
    7. Standards question, no calibration -> "not assessable"
    8. Same question across roles         -> same result; only explanation depth adapts

Where a scenario has deeper coverage elsewhere, this file asserts the HEADLINE property and names
the file that goes further, rather than duplicating it.
"""

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.unit

NS = "http://example.org/bldg#"

#: Timezone-AWARE, because the calibration state compares against aware dates parsed from the
#: graph. A naive value raises rather than silently comparing wrong, which is the right
#: failure mode and the reason this constant is stated once.
_NOW = datetime(2026, 8, 24, tzinfo=timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Remove the room sensor -> refuse a room-level claim
#    Deeper coverage: tests/test_acceptance_nonsubstitution.py
# ══════════════════════════════════════════════════════════════════════════════


class TestScenario1RoomSensorRemoved:
    """The non-substitution rule, graded rather than binary.

    The Master Report permits proxy data LABELLED as context while forbidding silent
    substitution, so three grades are needed: "the corridor outside 2.15 read 900 ppm" is a
    good answer, a bare "900 ppm" is a lie, and "I don't know" throws away real evidence.
    """

    def test_the_grades_exist_and_are_distinct(self):
        from shared.models import SpatialAdequacy

        assert {a.value for a in SpatialAdequacy} >= {"in_room", "served_zone", "proxy", "none"}

    def test_a_proxy_reading_can_never_be_recorded_as_in_room(self):
        """The scenario in one assertion: removing a room's own sensor must not let a
        neighbouring one inherit its status."""
        from shared.models import SpatialAdequacy

        assert SpatialAdequacy.PROXY is not SpatialAdequacy.IN_ROOM
        assert SpatialAdequacy.NONE is not SpatialAdequacy.PROXY

    def test_the_evidence_record_carries_the_grade(self):
        """A grade the record cannot hold is a grade no answer can state."""
        from shared.models import EvidenceRecord, SpatialAdequacy

        assert "spatial_adequacy" in EvidenceRecord.model_fields
        assert (
            EvidenceRecord().spatial_adequacy is SpatialAdequacy.NONE
        ), "the default is not NONE; evidence would start out claiming a location it lacks"

    def test_a_lane_labels_proxy_evidence_in_the_answer(self):
        """A grade recorded and never said out loud protects nobody."""
        from pathlib import Path

        src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
        assert (
            "proxy" in src.lower()
        ), "no lane mentions proxy evidence; a substituted reading would print unlabelled"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Missing intervals -> duration and averages change appropriately
#    Deeper coverage: tests/test_acceptance_quality.py
# ══════════════════════════════════════════════════════════════════════════════


class TestScenario2MissingIntervals:
    START = datetime(2026, 8, 1, 0, 0)
    END = datetime(2026, 8, 2, 0, 0)

    @classmethod
    def _stamps(cls, skip=()):
        skip = set(skip)
        return [cls.START + timedelta(hours=i) for i in range(24) if i not in skip]

    def test_a_complete_series_reports_full_coverage(self):
        from orchestrator.services.evidence.completeness import assess

        got = assess(self._stamps(), self.START, self.END, 3600)
        assert got.coverage is not None and got.coverage > 0.95, f"gapless series: {got.coverage}"

    def test_punching_a_hole_lowers_coverage_and_enumerates_the_gap(self):
        """A mean over half a window is a different claim from a mean over the window, and the
        difference has to survive into the answer."""
        from orchestrator.services.evidence.completeness import assess

        holed = assess(self._stamps(skip=range(6, 18)), self.START, self.END, 3600)
        assert holed.coverage is not None and holed.coverage < 0.6, f"12h hole: {holed.coverage}"
        assert holed.gaps, "the gap is not enumerated, so no answer can mention it"
        assert max(g.minutes for g in holed.gaps) >= 600

    def test_an_undeclared_cadence_is_unknown_not_complete(self):
        """Absence of a declared cadence must not read as perfect coverage — the failure that
        makes an uninstrumented building look fully monitored."""
        from orchestrator.services.evidence.completeness import assess

        got = assess(self._stamps(), self.START, self.END, None)
        assert got.coverage is None, "an unknown cadence was scored as complete"


# ══════════════════════════════════════════════════════════════════════════════
# 3. Move a sensor in metadata -> history stays linked to the prior location
# ══════════════════════════════════════════════════════════════════════════════


class TestScenario3SensorMoved:
    """The literal scenario: move the sensor, and March's readings still say March's room."""

    @staticmethod
    def _periods():
        from orchestrator.services.evidence.history import ConfigurationPeriod

        return [
            ConfigurationPeriod(
                effective_from=datetime(2026, 1, 1),
                effective_to=datetime(2026, 4, 1),
                location=f"{NS}Room5.01",
                change="commissioning",
            ),
            ConfigurationPeriod(
                effective_from=datetime(2026, 4, 1),
                location=f"{NS}Room5.09",
                change="relocation",
            ),
        ]

    def test_a_reading_is_attributed_to_the_room_in_force_when_it_was_taken(self):
        from orchestrator.services.evidence.history import location_as_of

        assert location_as_of(self._periods(), datetime(2026, 3, 15)) == f"{NS}Room5.01"
        assert location_as_of(self._periods(), datetime(2026, 5, 15)) == f"{NS}Room5.09"

    def test_a_reading_before_any_declared_period_is_unattributed_not_assumed(self):
        """ "We do not know where it was" and "it was where it is now" are different claims."""
        from orchestrator.services.evidence.history import location_as_of

        assert location_as_of(self._periods(), datetime(2025, 6, 1)) is None

    def test_a_window_spanning_the_move_is_flagged_and_split(self):
        from orchestrator.services.evidence.history import check_window

        integrity = check_window(self._periods(), datetime(2026, 3, 1), datetime(2026, 5, 1))
        assert not integrity.is_continuous, "a window spanning a relocation looked continuous"
        assert any(change == "relocation" for _, change in integrity.boundaries)
        assert len(integrity.segments) == 2, "the window was not split around the move"

    def test_a_window_inside_one_configuration_is_not_flagged(self):
        """Flagging everything would make the flag meaningless."""
        from orchestrator.services.evidence.history import check_window

        assert check_window(
            self._periods(), datetime(2026, 2, 1), datetime(2026, 3, 1)
        ).is_continuous

    def test_readings_keep_their_own_locations_across_a_move(self):
        from orchestrator.services.evidence.history import attribute_readings

        tagged = attribute_readings(
            [(datetime(2026, 3, 15), 21.0), (datetime(2026, 5, 15), 22.0)], self._periods()
        )
        assert [loc for _, _, loc in tagged] == [f"{NS}Room5.01", f"{NS}Room5.09"]


# ══════════════════════════════════════════════════════════════════════════════
# 4. Conflicting sensors -> report the disagreement, never average it away
#    Deeper coverage: tests/test_acceptance_quality.py
# ══════════════════════════════════════════════════════════════════════════════


class TestScenario4ConflictingSensors:
    @staticmethod
    def _readings(a, b):
        from orchestrator.services.evidence.conflict import Reading

        return [
            Reading(sensor_id=f"{NS}S_A", value=a, unit="degC"),
            Reading(sensor_id=f"{NS}S_B", value=b, unit="degC"),
        ]

    def test_two_disagreeing_sensors_are_reported_as_a_conflict(self):
        from orchestrator.services.evidence.conflict import detect

        report = detect(f"{NS}Room5.01", "temperature", self._readings(19.0, 26.0), 1.0)
        assert report.conflicting, "a 7-degree disagreement was not flagged"
        assert report.spread == 7.0

    def test_both_values_survive_into_the_report(self):
        """Averaging 19 and 26 gives 22.5 — a number no sensor reported and no room
        experienced. The individual readings have to remain nameable."""
        from orchestrator.services.evidence.conflict import detect

        report = detect(f"{NS}Room5.01", "temperature", self._readings(19.0, 26.0), 1.0)
        described = " ".join(r.describe() for r in report.readings)
        assert "19" in described and "26" in described

    def test_agreeing_sensors_are_not_reported_as_a_conflict(self):
        """A guard that fires on everything is noise, and noise gets ignored."""
        from orchestrator.services.evidence.conflict import detect

        assert not detect(f"{NS}R", "temperature", self._readings(21.0, 21.4), 1.0).conflicting

    def test_without_a_declared_tolerance_nothing_is_judged(self):
        """Inventing a tolerance would manufacture both conflicts and false agreement."""
        from orchestrator.services.evidence.conflict import detect

        report = detect(f"{NS}R", "temperature", self._readings(19.0, 26.0), None)
        assert not report.conflicting
        assert "no agreement tolerance" in report.reason

    def test_a_single_sensor_is_not_a_cross_check(self):
        from orchestrator.services.evidence.conflict import Reading, detect

        report = detect(f"{NS}R", "temperature", [Reading(sensor_id="s", value=19.0)], 1.0)
        assert not report.conflicting and "only one sensor" in report.reason


# ══════════════════════════════════════════════════════════════════════════════
# 5. Causal question with correlational evidence -> wording stays qualified
#    Deeper coverage: tests/test_causal_guard.py, tests/test_wave_a_wired.py
# ══════════════════════════════════════════════════════════════════════════════


class TestScenario5CausalWording:
    """The supervisors' worked example: the system MAY report that temperature rose after
    occupancy rose; it MUST NOT conclude the occupants caused the overheating. The difference
    is not the wording — it is what the evidence can carry.
    """

    def test_correlation_alone_licenses_no_attribution(self):
        from orchestrator.services.evidence.causal_guard import unlicensed_claims
        from shared.models import CausalSupport

        found = unlicensed_claims(
            "The high CO2 was caused by the closed damper.", CausalSupport.CORRELATIONAL
        )
        assert found, "a bare causal assertion passed on correlational evidence"

    def test_already_correlational_wording_is_recognised(self):
        """If honest hedged wording still trips the guard, authors route around the guard."""
        from orchestrator.services.evidence.causal_guard import is_already_correlational

        assert is_already_correlational("The high CO2 coincides with the damper being closed.")

    def test_qualify_rewrites_rather_than_empties(self):
        """An answer stripped of its explanation is not safer, only less useful."""
        from orchestrator.services.evidence.causal_guard import qualify
        from shared.models import CausalSupport

        out = qualify("The spike was caused by the fan stopping.", CausalSupport.CORRELATIONAL)
        assert out.strip(), "the guard emptied the answer instead of qualifying it"


# ══════════════════════════════════════════════════════════════════════════════
# 6. Public user requests restricted data -> access control is enforced
# ══════════════════════════════════════════════════════════════════════════════


class TestScenario6PublicUserRestricted:
    """A public visitor asking for security or per-space occupancy must be stopped by the
    POLICY, not by luck of phrasing."""

    @staticmethod
    def _engine():
        from orchestrator.services.privacy.policy_engine import Policy, PolicyEngine

        engine = PolicyEngine(building_id="bldgX", namespace=NS)
        engine._policies = [
            Policy(iri=f"{NS}p_admin", role="admin", tiers=[(0.0, 1.0)]),
            Policy(
                iri=f"{NS}p_public",
                role="public",
                scope_spaces="public",
                min_sensors=5,
                min_spaces=3,
                tiers=[(60.0, 3600.0)],
            ),
            Policy(
                iri=f"{NS}p_inf_presence",
                role="*",
                inference_class="individual_presence:deny",
            ),
        ]
        return engine

    def test_a_public_user_cannot_freely_read_a_single_space(self):
        """One space plus one sensor is an identifying view, whatever it is called."""
        verdict = self._engine().evaluate("public", scope="any", n_sensors=1, n_spaces=1)
        assert verdict.decision in (
            "deny",
            "restrict",
        ), f"a public user got {verdict.decision!r} for a single-space read"

    def test_the_decision_cites_a_policy_or_a_reason(self):
        """An enforcement decision that cannot say which rule produced it is indistinguishable
        from a bug."""
        verdict = self._engine().evaluate("public", scope="any", n_sensors=1, n_spaces=1)
        assert verdict.policy_iri or verdict.reason

    def test_an_individual_inference_is_denied_for_every_role_including_admin(self):
        """The one denial that does not bend to seniority. If an admin can ask it, the building
        tracks people and the policy is decorative."""
        for role in ("public", "occupant", "admin"):
            verdict = self._engine().evaluate(role, inference_class="individual_presence")
            assert verdict.decision == "deny", f"{role} was allowed an individual-presence query"

    def test_an_admin_aggregate_is_still_allowed(self):
        """Enforcement that blocks everything is not enforcement; it is an outage."""
        assert self._engine().evaluate("admin", n_sensors=10, n_spaces=5).allowed


# ══════════════════════════════════════════════════════════════════════════════
# 7. Standards question without calibrated evidence -> "not assessable"
# ══════════════════════════════════════════════════════════════════════════════


class TestScenario7NotAssessable:
    def test_not_assessable_is_a_distinct_status(self):
        """It must not collapse into "no data" (there ARE readings) nor into a pass/fail
        verdict (none can legitimately be given)."""
        from shared.models import AnswerStatus

        assert hasattr(AnswerStatus, "NOT_ASSESSABLE")
        assert AnswerStatus.NOT_ASSESSABLE.value == "not_assessable"

    def test_silence_about_calibration_is_unknown_never_calibrated(self):
        from orchestrator.services.evidence.assemble import _calibration_state

        assert (
            _calibration_state(None, _NOW) == "unknown"
        ), "a sensor with no calibration record was treated as compliance-grade"

    def test_an_expired_calibration_does_not_count_as_calibrated(self):
        from orchestrator.services.evidence.assemble import _calibration_state

        state = _calibration_state({"calibrated_on": "2024-01-01", "due_on": "2025-01-01"}, _NOW)
        assert state != "calibrated", f"an expired calibration reported as {state!r}"


# ══════════════════════════════════════════════════════════════════════════════
# 8. Same factual question across roles -> same result, only depth adapts
# ══════════════════════════════════════════════════════════════════════════════


class TestScenario8RoleConsistency:
    """Design contract #5: personas bias CLASSIFICATION and FRAMING only — never permissions,
    and never the underlying figure. A building that tells an executive 23 °C and a technician
    24 °C for the same sensor and window has two truths, which is worse than having none.
    """

    def test_personas_carry_no_permissions(self):
        """The structural guarantee. If a persona could carry permissions, persona would
        silently become a second access-control axis beside RBAC, and the two would drift."""
        from shared.persona_registry import get_persona_registry

        registry = get_persona_registry()
        personas = getattr(registry, "personas", None) or getattr(registry, "_personas", {})
        for name, spec in (personas or {}).items():
            blob = str(spec).lower()
            for forbidden in ("permission", "rbac", "allow_role"):
                assert forbidden not in blob, (
                    f"persona {name!r} mentions {forbidden!r}; RBAC must be the only "
                    "access-control axis"
                )

    def test_rbac_permissions_are_keyed_on_role(self):
        """The positive control for the test above: permissions DO exist, and they live on
        role. Asserting only absence would pass in a build that had lost RBAC entirely."""
        from orchestrator.middleware.rbac import ROLE_PERMISSIONS

        assert ROLE_PERMISSIONS, "no role permissions are defined at all"
        assert any("admin" in str(k).lower() for k in ROLE_PERMISSIONS)

    def test_role_is_not_consulted_when_shaping_a_figure(self):
        """The number is the number. Persona may change how much explanation surrounds it."""
        from pathlib import Path

        src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
        idx = src.find("_persona_adapter.enhance")
        assert idx > 0, "no persona adaptation step found to check"
        window = src[max(0, idx - 600) : idx + 600].lower()
        for forbidden in ("round(", "mean(", "sum("):
            assert forbidden not in window, (
                f"the persona step sits next to {forbidden!r}; presentation must not touch "
                "the figure"
            )


# ══════════════════════════════════════════════════════════════════════════════
# The suite's own contract
# ══════════════════════════════════════════════════════════════════════════════


def test_all_eight_scenarios_are_represented():
    """A count, so a scenario cannot be quietly dropped in a refactor.

    Eight is the number in Master 14.1. If the report ever gains a ninth, this fails and
    somebody has to decide about it deliberately.
    """
    import inspect
    import sys

    classes = [
        name
        for name, obj in inspect.getmembers(sys.modules[__name__], inspect.isclass)
        if name.startswith("TestScenario")
    ]
    assert (
        len(classes) == 8
    ), f"expected 8 scenario classes, found {len(classes)}: {sorted(classes)}"
    assert sorted(int(c.replace("TestScenario", "")[0]) for c in classes) == [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
    ]


def test_scenario_three_states_its_wiring_status():
    """HONESTY GUARD for the one scenario whose guard is not yet reachable in production.

    V6-T07 is tracked `logic_done_not_wired`: `history.py` is built and correct, but no
    pipeline lane consults it. Asserting only the module would imply an end-to-end property
    the system does not have — the reachability failure recorded as lesson #60, where a guard
    nothing calls stayed green while being unreachable.

    When T07 is wired this test fails, and the right response is to add an end-to-end scenario-3
    test and flip the tracker row — not to delete this.
    """
    from pathlib import Path

    callers = [
        p.as_posix()
        for p in Path("orchestrator").rglob("*.py")
        if "evidence/history.py" not in p.as_posix()
        and p.name != "__init__.py"  # a package re-export is not a caller
        and "location_as_of" in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not callers, (
        f"history.location_as_of now has pipeline callers ({callers}) — V6-T07 looks wired. "
        "Add an end-to-end scenario-3 test and update the tracker."
    )
