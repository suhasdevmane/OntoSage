# -*- coding: utf-8 -*-
"""The conformance report must run for a building that is NOT the active one.

That is the whole claim it exists to support (A4 of the architecture upgrade plan): the
ARCHITECTURE transfers, not the tuning. A suite that only exercised it against whichever
building happened to be active would prove nothing about portability and would break the
moment somebody swapped buildings — a failure mode this repo has already had, nine tests
at once (``lesson_tests_must_not_assume_active_building``).

So every test here reads the **bldg4 fixture**, which is deliberately not installed, and
the rest are pure functions fed hand-built facts. Nothing here needs a graph, a store, a
container or an active building.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]
_B4 = _REPO / "bldg4"


def _load():
    """Import the script by path, as a user would run it.

    Registered in ``sys.modules`` BEFORE it executes: ``@dataclass`` resolves annotations
    through ``sys.modules[cls.__module__]``, and a module absent from there raises during
    class creation rather than anywhere near the test.
    """
    import sys

    name = "_conformance_report"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, str(_REPO / "scripts" / "conformance_report.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cr = _load()


def _skip_if_no_fixture():
    if not (_B4 / "building.yaml").is_file():
        pytest.skip("the bldg4 fixture is not present in this checkout")


# ── it reads a building that is not the active one ───────────────────────────


def test_profile_comes_from_the_fixture_not_from_the_active_building():
    _skip_if_no_fixture()
    profile = cr.load_profile(_B4)
    assert profile.building_id == "bldg4"
    assert profile.namespace.endswith("#")
    # The active building's namespace must not leak in through config or defaults.
    active = _REPO / "input" / "building.yaml"
    if active.is_file():
        import yaml

        active_ns = (yaml.safe_load(active.read_text(encoding="utf-8")) or {}).get(
            "ontology_namespace"
        )
        if active_ns:
            assert profile.namespace != active_ns


def test_the_fixture_datasource_placeholders_resolve():
    """``${MYSQL_HOST:-...}`` must become a value, or every store probe measures the shell."""
    _skip_if_no_fixture()
    profile = cr.load_profile(_B4)
    assert profile.registry_stores, "the fixture declares no datasource"
    for key, entry in profile.registry_stores.items():
        assert "${" not in str(entry.get("host", "")), key
        assert "${" not in str(entry.get("database", "")), key


def test_intents_are_read_from_the_registry_not_written_in():
    _skip_if_no_fixture()
    intents = cr.load_intents(_B4)
    shipped = cr._read_yaml(_REPO / "orchestrator" / "intents" / "intent_definitions.yaml")
    assert len(intents) == len({i["name"] for i in shipped["intents"]})
    assert "sensor_data" in intents


def test_a_missing_lane_drops_its_question_class_rather_than_failing_it():
    """A deployment without a lane must not be graded on the class that lane serves."""
    _skip_if_no_fixture()
    intents = cr.load_intents(_B4)
    without = {k: v for k, v in intents.items() if k != "register"}
    caps, dropped = cr.derive_matrix(cr.QUESTION_CLASSES, without, _measures())
    assert not any(c.key == "register_lookup" for c in caps)
    assert any("register" in d for d in dropped)


def test_the_report_runs_offline_for_the_fixture_and_says_it_could_not_measure():
    _skip_if_no_fixture()
    report = cr.run(
        input_dir=_B4,
        graph_endpoint="http://127.0.0.1:1/repositories/none",
        volumes_root=_REPO / "volumes",
        fresh_hours=24,
        offline=True,
    )
    assert report["building"]["building_id"] == "bldg4"
    graph = [c for c in report["checks"] if c["key"] == "graph"][0]
    # Unreachable is UNKNOWN, never PASS. A report that scored an unmeasured building as
    # fine would be worse than no report.
    assert graph["status"] == cr.UNKNOWN
    assert cr.render_markdown(report)


# ── the contract checks decide from numbers ──────────────────────────────────


def test_fanout_fails_on_a_duplicated_graph_and_passes_on_a_clean_one():
    assert cr.check_reference_fanout(3642, 3615).status == cr.PASS
    bad = cr.check_reference_fanout(9000, 3000)
    assert bad.status == cr.FAIL
    assert "3.000" in bad.detail
    assert cr.check_reference_fanout(0, 0).status == cr.FAIL


def test_a_point_with_two_series_fails_even_though_fanout_is_clean():
    """BUG-531's exact shape: each reference carries its own id, so fan-out stays at 1.00."""
    assert cr.check_reference_fanout(3642, 3615).status == cr.PASS
    check = cr.check_one_series_per_point(["Sensor_A", "Sensor_B"], known=True)
    assert check.status == cr.FAIL
    assert "two or more series" in check.detail


def test_an_unaskable_graph_reports_unknown_not_pass():
    assert cr.check_one_series_per_point([], known=False).status == cr.UNKNOWN


def test_a_store_named_by_the_graph_must_be_in_both_files():
    graph_stores = {"alpha": 10, "beta": 5}
    both = cr.check_stores_registered(graph_stores, ["alpha", "beta"], {"alpha": {}, "beta": {}})
    assert both.status == cr.PASS
    only_registry = cr.check_stores_registered(graph_stores, ["alpha"], {"alpha": {}, "beta": {}})
    assert only_registry.status == cr.FAIL
    assert "building.yaml" in only_registry.detail
    only_config = cr.check_stores_registered(graph_stores, ["alpha", "beta"], {"alpha": {}})
    assert only_config.status == cr.FAIL
    assert "database_registry" in only_config.detail


def test_a_series_with_no_store_is_a_failure_not_a_silence():
    check = cr.check_stores_registered({"alpha": 3, "": 7}, ["alpha"], {"alpha": {}})
    assert check.status == cr.FAIL
    assert check.measured["series_without_store"] == 7


def test_a_store_without_a_driver_is_unknown_and_a_store_that_errors_is_a_failure():
    unprobed = cr.check_store_probes(
        {"a": {"answered": False, "reason": "no MySQL driver available on this host"}}
    )
    assert unprobed.status == cr.UNKNOWN
    broken = cr.check_store_probes({"a": {"answered": False, "reason": "OperationalError: nope"}})
    assert broken.status == cr.FAIL


def test_freshness_counts_points_once_across_overlapping_quantities():
    """A point typed with two matching classes belongs to two quantities.

    Summing the per-quantity counts reports more reporting points than the building has,
    which is how a coverage figure over 100% gets published.
    """
    modality = {
        "temperature": {"uuids": ["u1", "u2"], "fresh": 2, "with_rows": 2},
        "zone_temperature": {"uuids": ["u1", "u2"], "fresh": 2, "with_rows": 2},
    }
    check = cr.check_freshness(modality, 24, {"points": 2, "fresh": 2})
    assert check.status == cr.PASS
    assert check.measured["points_total"] == 2
    assert "2 of 2" in check.detail


def test_a_quantity_with_history_and_no_recent_rows_is_a_limitation_not_a_pass():
    modality = {
        "temperature": {"uuids": ["u1"], "fresh": 1, "with_rows": 1},
        "water": {"uuids": ["u2"], "fresh": 0, "with_rows": 1},
    }
    check = cr.check_freshness(modality, 24, {"points": 2, "fresh": 1})
    assert check.status == cr.LIMITED
    assert "water" in check.detail


def test_floor_plan_links_fail_when_nothing_joins_the_plan_to_the_graph():
    plans = {"found": True, "manifests": 3, "spaces": 60, "linked_in_namespace": 0, "iris": []}
    assert cr.check_floor_plan_links(plans, set()).status == cr.FAIL
    linked = {
        "found": True,
        "manifests": 3,
        "spaces": 2,
        "linked_in_namespace": 2,
        "iris": ["ns#A", "ns#B"],
    }
    assert cr.check_floor_plan_links(linked, {"ns#A", "ns#B"}).status == cr.PASS
    # Linked to IRIs the graph does not hold is a limitation, not a clean pass.
    assert cr.check_floor_plan_links(linked, {"ns#A"}).status == cr.LIMITED


# ── the matrix is decided by the data, not by the lane existing ──────────────


def _measures(**overrides):
    base = {
        "fresh_hours": 24,
        "modality_freshness": {
            "temperature": {
                "uuids": ["u1", "u2"],
                "fresh": 2,
                "with_rows": 2,
                "points": 2,
                "spaces_covered": 2,
                "stores": ["alpha"],
            }
        },
        "unresolved_modalities": ["water_flow_hot"],
        "points_fresh": 2,
        "spaces": 4,
        "spaces_detail": [
            {"iri": "ns#R1", "label": "Room 1.01 — Office", "floor": "Level 1"},
            {"iri": "ns#R2", "label": "Room 2.01 — Lab", "floor": "Level 2"},
        ],
        "floors": ["Level 1", "Level 2"],
        "floors_instrumented": 2,
        "registers_held": {"WorkOrder": 12, "AccessEvent": 40, "AssetStatus": 6},
        "registers_declared": 5,
        "registers_known": True,
        "documents": 9,
        "amenities": ["Lighting"],
        "floor_plan": {"manifests": 2, "plan_spaces": 10, "linked_in_namespace": 10},
        "max_history_days": 90.0,
        "person_level_modalities": ["occupancy"],
    }
    base.update(overrides)
    return base


def test_a_building_with_no_recent_readings_cannot_answer_a_present_tense_question():
    measures = _measures(
        modality_freshness={
            "temperature": {
                "uuids": ["u1"],
                "fresh": 0,
                "with_rows": 1,
                "points": 1,
                "spaces_covered": 1,
                "stores": ["alpha"],
            }
        }
    )
    verdict, reason, missing = cr._decide_current_reading(measures)
    assert verdict == cr.SUPPORTED_LIMITED
    assert "historical" in reason
    assert missing


def test_a_building_with_no_readings_at_all_is_not_supported():
    verdict, _, missing = cr._decide_current_reading(_measures(modality_freshness={}))
    assert verdict == cr.NOT_SUPPORTED
    assert missing


def test_one_instrumented_floor_cannot_support_a_floor_comparison():
    verdict, reason, _ = cr._decide_floor_ranking(_measures(floors_instrumented=1))
    assert verdict == cr.NOT_SUPPORTED
    assert "1 of 2" in reason


def test_a_building_holding_no_records_declines_register_questions():
    verdict, _, missing = cr._decide_register(_measures(registers_held={}))
    assert verdict == cr.NOT_SUPPORTED
    assert missing


def test_a_building_with_no_documents_cannot_answer_from_documents():
    assert cr._decide_document(_measures(documents=0))[0] == cr.NOT_SUPPORTED
    assert cr._decide_document(_measures(documents=2))[0] == cr.SUPPORTED_LIMITED
    assert cr._decide_document(_measures(documents=40))[0] == cr.SUPPORTED


def test_unlinked_floor_plans_are_not_supported_however_many_manifests_exist():
    verdict, reason, _ = cr._decide_spatial(
        _measures(floor_plan={"manifests": 6, "plan_spaces": 354, "linked_in_namespace": 0})
    )
    assert verdict == cr.NOT_SUPPORTED
    assert "354" in reason


def test_the_matrix_differs_between_two_buildings_with_the_same_lanes():
    """The point of the artifact: same code, same lanes, different verdicts."""
    _skip_if_no_fixture()
    intents = cr.load_intents(_B4)
    rich, _ = cr.derive_matrix(cr.QUESTION_CLASSES, intents, _measures())
    bare, _ = cr.derive_matrix(
        cr.QUESTION_CLASSES,
        intents,
        _measures(
            modality_freshness={},
            registers_held={},
            documents=0,
            floors=[],
            floors_instrumented=0,
            spaces=0,
            spaces_detail=[],
            floor_plan={"manifests": 0, "plan_spaces": 0, "linked_in_namespace": 0},
            max_history_days=None,
            person_level_modalities=[],
        ),
    )
    # Same classes — the lanes are identical — and different verdicts, decided by data.
    assert {c.key for c in rich} == {c.key for c in bare}
    assert [c.verdict for c in rich] != [c.verdict for c in bare]
    verdicts = {c.key: c.verdict for c in bare}
    # A refusal must hold whatever the building holds, so it survives an empty building —
    # with the limitation stated that it has not been exercised against sensitive data.
    assert verdicts.pop("privacy_refusal") == cr.SUPPORTED_LIMITED
    assert set(verdicts.values()) == {cr.NOT_SUPPORTED}
    assert all(c.missing for c in bare if c.verdict == cr.NOT_SUPPORTED)


def test_lanes_outside_this_report_are_named_rather_than_ignored():
    _skip_if_no_fixture()
    unmapped = cr.unmapped_intents(cr.QUESTION_CLASSES, cr.load_intents(_B4))
    assert unmapped, "a report covering every lane would be a surprise; say which it misses"
    assert "control" in unmapped


# ── the question set is generated from the building, never written per building ──


def test_questions_use_only_referents_the_building_holds():
    _skip_if_no_fixture()
    intents = cr.load_intents(_B4)
    caps, _ = cr.derive_matrix(cr.QUESTION_CLASSES, intents, _measures())
    questions = cr.build_question_set(cr.QUESTION_CLASSES, caps, _measures())
    assert questions
    joined = " ".join(q.question for q in questions)
    # Fed only the two hand-built rooms and two floors, nothing else may appear.
    assert "Room 1.01" in joined and "Level 1" in joined
    for word in ("abacws", "cardiff", "bldg1", "Room 5."):
        assert word.lower() not in joined.lower(), word


def test_every_question_carries_the_behaviour_it_should_produce():
    _skip_if_no_fixture()
    caps, _ = cr.derive_matrix(cr.QUESTION_CLASSES, cr.load_intents(_B4), _measures())
    for q in cr.build_question_set(cr.QUESTION_CLASSES, caps, _measures()):
        assert q.expects.strip(), q.id
        assert q.question_class
        assert q.verdict_at_generation in (cr.SUPPORTED, cr.SUPPORTED_LIMITED, cr.NOT_SUPPORTED)


def test_an_unsupported_class_still_gets_questions_and_expects_a_decline():
    _skip_if_no_fixture()
    measures = _measures(documents=0)
    caps, _ = cr.derive_matrix(cr.QUESTION_CLASSES, cr.load_intents(_B4), measures)
    questions = cr.build_question_set(cr.QUESTION_CLASSES, caps, measures)
    docs = [q for q in questions if q.question_class == "document_answer"]
    assert docs, "a class the building cannot serve still has to be asked — to check it declines"
    assert all("decline" in q.expects for q in docs)


def test_the_absent_referent_is_shaped_like_the_building_s_own_names():
    """A name in a foreign format is declined because it does not parse, which proves nothing."""
    spaces = [{"label": "Room 1.01 — Office"}, {"label": "Room 1.02 — Store"}]
    absent = cr._absent_space_label(spaces)
    assert absent.startswith("Room 1.")
    assert absent not in {s["label"] for s in spaces}


def test_the_absence_class_asks_about_both_kinds_of_absence():
    """A quantity nothing measures, and a referent that does not exist, are different facts."""
    _skip_if_no_fixture()
    caps, _ = cr.derive_matrix(cr.QUESTION_CLASSES, cr.load_intents(_B4), _measures())
    texts = [
        q.question
        for q in cr.build_question_set(cr.QUESTION_CLASSES, caps, _measures())
        if q.question_class == "honest_absence"
    ]
    assert any("water flow hot" in t for t in texts)
    assert any("1.9" in t or "1.8" in t for t in texts)


def test_a_descriptive_label_is_shortened_the_way_a_person_would_say_it():
    assert cr._short_label("Room 0.01 — Main Reception") == "Room 0.01"
    assert cr._short_label("Telecommunications Room") == "Telecommunications Room"


def test_declared_quantities_are_read_as_people_say_them():
    assert cr._readable("pm25") == "PM2.5"
    assert cr._readable("co2") == "CO2"
    assert cr._readable("supply_air_temperature") == "supply air temperature"
    assert cr._readable_register("WorkOrder") == "work order"


# ── the report never tells a reader their data is not real ───────────────────


def test_no_rendered_line_says_a_building_s_data_is_not_real():
    """Project rule, and a store's own config note is exactly how the word gets in."""
    _skip_if_no_fixture()
    report = cr.run(
        input_dir=_B4,
        graph_endpoint="http://127.0.0.1:1/repositories/none",
        volumes_root=_REPO / "volumes",
        fresh_hours=24,
        offline=True,
    )
    report["stores"] = {
        "alpha": {
            "answered": False,
            "reason": "synthetic source unavailable",
            "uuids_with_rows": 0,
            "uuids_expected": 3,
            "newest": "",
            "history_days": None,
        }
    }
    text = cr.render_markdown(report).lower()
    for word in ("simulated", "synthetic", "fake"):
        assert word not in text, word


# ── the store probe, without a store ─────────────────────────────────────────


class _FakeCursor:
    """The smallest thing that behaves like a narrow table."""

    def __init__(self, rows_by_uuid):
        self._rows = rows_by_uuid
        self._answer = None

    def execute(self, sql, params=None):
        params = list(params or [])
        if "MIN(" in sql:
            stamps = [v for v in self._rows.values()]
            self._answer = (min(stamps), max(stamps)) if stamps else (None, None)
        elif "INTERVAL" in sql:
            hours = int(params[-1])
            wanted = params[:-1]
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
            self._answer = (
                len([u for u in wanted if u in self._rows and self._rows[u] >= cutoff]),
            )
        elif "COUNT(DISTINCT" in sql:
            self._answer = (len([u for u in params if u in self._rows]),)
        else:
            self._answer = (None,)

    def fetchone(self):
        return self._answer

    def fetchall(self):
        return []


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        pass


def test_the_probe_counts_each_quantity_against_the_store_rather_than_apportioning_it():
    """An apportioned figure reports every quantity as fresh whenever the store is."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = {
        "aaaaaaaa-0001": now,  # reporting
        "aaaaaaaa-0002": now - timedelta(days=9),  # historical only
    }
    cursor = _FakeCursor(rows)
    result = cr.probe_mysql_store(
        "alpha",
        {"type": "mysql_narrow", "table": "readings"},
        uuids=["aaaaaaaa-0001", "aaaaaaaa-0002", "aaaaaaaa-0001"],
        fresh_hours=24,
        connect=lambda **_: _FakeConn(cursor),
        groups={"live": ["aaaaaaaa-0001"], "stale": ["aaaaaaaa-0002"]},
    )
    assert result["answered"]
    # Deduped: the same id arriving twice is one point, not a coverage gap.
    assert result["uuids_expected"] == 2
    assert result["uuids_with_rows"] == 2
    assert result["uuids_fresh"] == 1
    assert result["groups"]["live"]["fresh"] == 1
    assert result["groups"]["stale"]["fresh"] == 0


def test_a_store_this_host_cannot_reach_reports_why_and_does_not_claim_to_have_answered():
    result = cr.probe_mysql_store(
        "alpha",
        {"type": "mysql_narrow", "table": "readings"},
        uuids=["aaaaaaaa-0001"],
        fresh_hours=24,
        connect=_raise,
    )
    assert not result["answered"]
    assert "RuntimeError" in result["reason"]


def _raise(**_):
    raise RuntimeError("refused")


def test_an_adapter_type_this_host_has_no_probe_for_is_not_reported_as_healthy():
    result = cr.probe_mysql_store("alpha", {"type": "cassandra"}, [], 24)
    assert not result["answered"]
    assert "no probe for adapter type" in result["reason"]


def test_a_table_name_that_is_not_an_identifier_is_refused():
    result = cr.probe_mysql_store(
        "alpha", {"type": "mysql_narrow", "table": "readings; DROP TABLE x"}, [], 24
    )
    assert not result["answered"]
    assert "plain identifier" in result["reason"]


# ── quantities are grouped the way the coverage auditor groups them ──────────


def test_a_label_exclusion_wins_over_an_inclusion_and_reads_both_label_and_iri():
    modalities = {
        "pm25": {
            "brick_classes": ["PM_Sensor"],
            "label_contains": ["pm2"],
            "label_excludes": ["pm1_"],
        }
    }
    points = [
        {
            "iri": "ns#PM2_5_Sensor_A",
            "class_local": "PM_Sensor",
            "text": "PM2.5 Sensor ns#PM2_5_Sensor_A",
            "uuid": "u1",
            "store": "s",
        },
        # Named PM2.5 in its label and PM1 in its IRI — the pair is what must be matched.
        {
            "iri": "ns#PM1_Sensor_B",
            "class_local": "PM_Sensor",
            "text": "PM2.5 Sensor ns#PM1_Sensor_B",
            "uuid": "u2",
            "store": "s",
        },
    ]
    indexed = cr.index_points_by_modality(modalities, points)
    assert indexed["pm25"]["uuids"] == ["u1"]


def test_a_quantity_the_building_models_but_never_routes_is_visible():
    modalities = {"temperature": {"brick_classes": ["Temperature_Sensor"]}}
    points = [
        {
            "iri": "ns#T1",
            "class_local": "Temperature_Sensor",
            "text": "T1",
            "uuid": "u1",
            "store": "",
        },
    ]
    indexed = cr.index_points_by_modality(modalities, points)
    assert indexed["temperature"]["unrouted"] == 1
    assert indexed["temperature"]["stores"] == []


# ── the JSON is machine-readable ─────────────────────────────────────────────


def test_the_report_serialises_without_losing_its_measurements():
    _skip_if_no_fixture()
    report = cr.run(
        input_dir=_B4,
        graph_endpoint="http://127.0.0.1:1/repositories/none",
        volumes_root=_REPO / "volumes",
        fresh_hours=24,
        offline=True,
    )
    round_tripped = json.loads(json.dumps(report, default=str))
    assert round_tripped["building"]["building_id"] == "bldg4"
    assert all("measured" in c for c in round_tripped["checks"])
