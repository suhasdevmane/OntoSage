# -*- coding: utf-8 -*-
"""The reach report scores every question with the router's own code, offline, and stays honest.

What these pin
--------------
* The referent model answers the gate's five lookups exactly (co-occurrence in ONE field, label or
  IRI contains), and the report's stricter whole-word test tells "on" inside "carbon" from a real
  thing, so a junk typed referent is never counted as an existing one.
* The real ``ReferentResolver.resolve`` runs unchanged over that model: not found, resolved, a
  word-shaped token that resolves trivially, a floor that does not exist, a kind the building has
  none of.
* Flags are exclusive where they say so: ``nothing`` means nothing at all, a decline route is not
  a grounded reach, and a rule that claims the question from a neutral start counts.
* The lift filter keeps a word that marks unreached questions and drops a word that is merely
  common; the tables add up.
* The evaluation pool never contains a held-out question, and without a hash file the CLI refuses.

Fixtures are tiny and synthetic. The Models test parses the real schema TTL (as
``test_register_reach.py`` does) but needs no GraphDB and no orchestrator import.
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
NS = "http://example.org/bldg#"


def _load():
    name = "_test_reach_report_module"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / "reach_report.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rr = _load()
BRICK = "https://brickschema.org/schema/Brick#"

ENTITIES: Dict[str, List[str]] = {
    "subjects": [
        NS + "Room5.01",
        NS + "Room5.02",
        NS + "Floor_3",
        NS + "Chiller_01",
        NS + "Carbon_Sensor_1",
        NS + "Board_1",
    ],
    "labels_typed": [
        "Room 5.01",
        "Room 5.02",
        "Floor 3",
        "Chiller 01",
        "Carbon Monoxide Sensor",
        "Distribution board",
    ],
    "labels_any": [
        "Room 5.01",
        "Room 5.02",
        "Floor 3",
        "Chiller 01",
        "Carbon Monoxide Sensor",
        "Distribution board",
    ],
    "classes": [BRICK + "Room", BRICK + "Floor", BRICK + "Chiller", BRICK + "Sensor"],
}


@pytest.fixture(scope="module")
def model():
    return rr.ReferentModel(ENTITIES, NS)


@pytest.fixture(scope="module")
def resolver(model):
    return rr.offline_referent_resolver(model)


# ── the entity model answers the gate's lookups ────────────────────────────────────────


def test_every_term_must_sit_in_one_field(model):
    assert model.exists_terms(["floor", "3"]) is True  # "floor_3" holds both
    assert model.exists_terms(["floor", "7"]) is False
    assert model.exists_terms(["chiller"]) is True  # a class local name
    # "room" is in one field and "monoxide" in another entity's: two fields do not make one thing
    assert model.exists_terms(["room", "monoxide"]) is False


def test_a_token_is_a_label_or_iri_substring(model):
    assert model.exists_token("5.01") is True
    assert model.exists_token("9.99") is False


def test_matching_ids_lists_the_dotted_ids_containing_the_token(model):
    assert model.matching_ids("5.0") == {"5.01", "5.02"}
    assert model.matching_ids("5.01") == {"5.01"}
    assert model.matching_ids("9.9") == set()


def test_a_short_word_inside_a_longer_one_exists_for_the_gate_but_not_as_a_word(model):
    assert model.exists_terms(["on"]) is True  # inside "carbon" and "monoxide"
    assert model.exists_whole_word(["on"]) is False
    assert model.exists_whole_word(["chiller"]) is True
    assert model.exists_whole_word(["floor", "3"]) is True


# ── the real gate, run over the model ──────────────────────────────────────────────────


def _resolve(resolver, model, text):
    return rr.resolve_referent(resolver, model, text)


def test_a_room_id_that_does_not_exist_is_not_found(resolver, model):
    out = _resolve(resolver, model, "What is the temperature in Room 9.99?")
    assert (out["kind"], out["status"], out["phrase"]) == ("id", "not_found", "9.99")


def test_a_room_id_that_exists_resolves_and_is_not_weak(resolver, model):
    out = _resolve(resolver, model, "What is the temperature in room 5.01?")
    assert out["status"] == "resolved" and out["weak"] is False


def test_a_floor_that_does_not_exist_is_not_found_but_the_kind_exists(resolver, model):
    out = _resolve(resolver, model, "How busy is floor 42?")
    assert (out["kind"], out["status"]) == ("floor", "not_found")
    assert out["head_exists"] is True  # the building has floors, just not this one


def test_a_kind_the_building_has_none_of_says_so(resolver, model):
    out = _resolve(resolver, model, "Is there anyone in the rooftop garden?")
    assert out["status"] == "not_found" and out["head_exists"] is False


def test_a_word_after_room_that_resolves_trivially_is_weak(resolver, model):
    """'room CARBON ...': the word is in the graph, so the gate says RESOLVED, and it is a word,
    not an id. (A function word after 'room' -- 'room IS too cold' -- is no longer a referent.)"""
    out = _resolve(resolver, model, "The room carbon sensor reads high")
    assert out["status"] == "resolved" and out["weak"] is True
    assert rr.flags_for(_row(referent=out))["referent"] is False


def test_a_function_word_after_room_or_before_levels_is_no_referent_at_all(resolver, model):
    """'room IS too cold' read as a place called 'is'; 'classes ON Levels 1 and 3' as a measurand
    called 'on' (which 'carbon' contains). Neither names anything."""
    for text in ("The room is too cold", "I have classes on Levels 1 and 3 tomorrow"):
        assert _resolve(resolver, model, text)["status"] == "no_referent", text


def test_no_referent_at_all_is_reported_as_none(resolver, model):
    out = _resolve(resolver, model, "How efficient is the building?")
    assert out["status"] == "no_referent" and out["phrase"] == ""


# ── concepts from a TTL on disk ────────────────────────────────────────────────────────

_HBCO = """
@prefix hbco: <http://ontosage.org/hbco#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .
hbco:stuffiness a hbco:Concept ; hbco:layTerm "stuffy", "airless" ;
    hbco:mapsToBrickClass brick:CO2_Sensor ; hbco:confidence "high" .
hbco:wayfinding a hbco:Concept ; hbco:layTerm "how do i get to" .
"""


def test_concepts_load_from_ttl_through_the_resolvers_own_parser(tmp_path):
    ttl = tmp_path / "mini_hbco.ttl"
    ttl.write_text(_HBCO, encoding="utf-8")
    concept_map = rr.load_concept_map([ttl])
    assert len(concept_map) == 2
    entry = next(e for e in concept_map.values() if e["concept_id"] == "stuffiness")
    assert entry["lay_terms"] == ["airless", "stuffy"]
    assert entry["brick_classes"] == ["brick:CO2_Sensor"]

    resolver = rr.offline_concept_resolver(concept_map)
    hit = rr._run(resolver.resolve("It is airless in here"))
    assert [m.concept_id for m in hit] == ["stuffiness"]
    assert rr._run(resolver.resolve("Hello there")) == []
    assert rr.grounding_module().has_measurand_concept([m.to_dict() for m in hit]) is True


# ── flags ──────────────────────────────────────────────────────────────────────────────


def _row(**over: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "concepts": [],
        "register": {"held": None, "second": None, "absent": None},
        "amenity_kinds": [],
        "referent": {"kind": "", "phrase": "", "status": "no_referent", "weak": False},
        "contract": {},
        "implied_sources": [],
    }
    row.update(over)
    return row


def test_a_question_that_reaches_nothing_is_flagged_nothing_and_only_that():
    flags = rr.flags_for(_row())
    assert flags["nothing"] is True
    assert not any(v for k, v in flags.items() if k != "nothing")


def test_each_grounded_reach_is_its_own_flag_and_is_never_nothing():
    cases = {
        "concept": {"concepts": ["stuffiness"]},
        "register": {"register": {"held": "Permit", "second": None, "absent": None}},
        "amenity": {"amenity_kinds": ["DrinkingWater"]},
        "referent": {
            "referent": {"kind": "id", "phrase": "5.01", "status": "resolved", "weak": False}
        },
        "routed": {"contract": {"general": {"rules": ["consumption_query"], "final": "analytics"}}},
    }
    for flag, over in cases.items():
        flags = rr.flags_for(_row(**over))
        assert flags[flag] is True and flags["nothing"] is False


def test_a_generic_topic_is_weak_and_a_decline_is_not_a_grounded_reach():
    topic = rr.flags_for(_row(amenity_kinds=["(generic)"]))
    assert topic["topic_only"] is True and topic["amenity"] is False and topic["nothing"] is False
    absent = rr.flags_for(_row(register={"held": None, "second": None, "absent": "Contract"}))
    assert absent["decline_only"] is True and absent["nothing"] is False
    missing = rr.flags_for(
        _row(referent={"kind": "space", "phrase": "gym", "status": "not_found", "weak": False})
    )
    assert missing["decline_only"] is True and missing["referent"] is False


def test_a_decline_does_not_hide_a_grounded_reach():
    flags = rr.flags_for(
        _row(
            concepts=["noisy"],
            referent={"kind": "space", "phrase": "gym", "status": "not_found", "weak": False},
        )
    )
    assert flags["concept"] is True and flags["decline_only"] is False


def test_a_rule_that_only_fires_from_another_start_does_not_count_as_routed():
    row = _row(contract={"capability": {"rules": ["x"], "final": "y"}, "general": {"rules": []}})
    assert rr.flags_for(row)["routed"] is False


# ── tables and rankings ────────────────────────────────────────────────────────────────


def _evaluated(text: str, source: str = "survey", group: str = "g", **over: Any) -> Dict[str, Any]:
    row = _row(**over)
    row.update({"id": text, "text": text, "source": source, "group": group})
    row["flags"] = rr.flags_for(row)
    return row


def test_rate_table_counts_and_percentages_add_up():
    rows = [
        _evaluated("a", concepts=["x"]),
        _evaluated("b", concepts=["x"]),
        _evaluated("c"),
        _evaluated("d", group="h"),
    ]
    table = {r["key"]: r for r in rr.rate_table(rows, lambda r: r["group"])}
    assert table["g"]["n"] == 3 and table["g"]["concept"] == 2 and table["g"]["nothing"] == 1
    assert table["g"]["concept_pct"] == pytest.approx(66.7, abs=0.05)
    assert table["h"]["nothing_pct"] == 100.0


def test_the_lift_filter_keeps_a_marker_word_and_drops_a_merely_common_one():
    rows = [_evaluated(f"vending machine stock {i} in the room", concepts=[]) for i in range(6)]
    rows += [_evaluated(f"how warm is the room number {i}", concepts=["warm"]) for i in range(20)]
    ranking = rr.ngram_ranking(rows, lambda r: not r["flags"]["concept"], min_count=3)
    terms = {r["term"] for r in ranking}
    assert "vending" in terms or "vending machine" in terms
    assert "room" not in terms  # in every question, so it marks nothing
    assert all(r["share"] >= 0.5 for r in ranking)


def test_content_terms_drop_stop_words_and_keep_adjacent_pairs():
    terms = rr.content_terms("What is the air quality in the building?")
    assert "air quality" in terms and "air" in terms and "the" not in terms
    assert "building" not in terms


# ── implied data sources ───────────────────────────────────────────────────────────────


def test_catalogue_rows_take_their_source_from_the_declared_evidence():
    models = SimpleNamespace(demand=rr.catalogue_demand())
    q = SimpleNamespace(
        primary="stakeholder_catalogue_37",
        tags={"required_data_sources": ""},
        evidence={
            "Authoritative_Sources": "The CMMS work order owner and the room booking system",
            "Sensors_Required": "",
        },
    )
    assert {"cmms_work", "booking"} <= set(rr.implied_sources(q, models))


def test_synthetic_rows_take_their_source_from_required_data_sources():
    q = SimpleNamespace(
        primary="synthetic",
        tags={"required_data_sources": "S1:existing; graph:metadata"},
        evidence={},
    )
    assert rr.implied_sources(q, None) == ["S1:existing", "graph:metadata"]
    assert rr.implied_sources(SimpleNamespace(primary="survey", tags={}, evidence={}), None) == []


# ── routing summary ────────────────────────────────────────────────────────────────────


def test_routing_summary_counts_rules_from_general_and_from_any_start():
    contract = SimpleNamespace(
        start_intents=("general", "capability"),
        stages={"parse": ["r1", "r2"], "post": [], "concept": ["r3"]},
        rule_names=["r1", "r2", "r3"],
    )
    rows = [
        _evaluated(
            "one",
            contract={
                "general": {"rules": ["r1"], "final": "sensor_data"},
                "capability": {"rules": ["r1", "r3"], "final": "analytics"},
            },
        ),
        _evaluated(
            "two",
            contract={
                "general": {"rules": [], "final": "general"},
                "capability": {"rules": ["r3"], "final": "analytics"},
            },
        ),
    ]
    out = rr.summarise_routing(rows, contract)
    by_rule = {r["rule"]: r for r in out["rules"]}
    assert (by_rule["r1"]["from_general"], by_rule["r1"]["from_any_start"]) == (1, 1)
    assert (by_rule["r3"]["from_general"], by_rule["r3"]["from_any_start"]) == (0, 2)
    assert out["never_fire"] == ["r2"]
    assert out["final_intent"]["general"] == {"sensor_data": 1, "general": 1}


def test_routing_summary_says_when_the_contract_was_not_evaluated():
    out = rr.summarise_routing([_evaluated("q")], None, "disabled with --no-contract")
    assert out["available"] is False and "disabled" in out["note"]


def test_the_contract_is_sequenced_parse_post_concept_with_the_concepts_resolved_first():
    """As dialogue_agent does: parse then post on one dict, then the concept stage on a fresh dict
    carrying the resolved concepts and the intent the earlier stages left."""
    calls: List[Any] = []

    def fake_apply(query, normalized, stage="parse"):
        calls.append((stage, dict(normalized)))
        if stage == "parse":
            normalized["intent"] = "sensor_data"
            normalized["routing_rules_applied"] = ["parse_rule"]
        if stage == "concept":
            normalized["routing_rules_applied"] = ["concept_rule"]
            normalized["intent"] = "analytics"

    runner = rr.ContractRunner.__new__(rr.ContractRunner)
    runner.rc = SimpleNamespace(apply_contract=fake_apply)
    runner.start_intents = ("general",)
    concepts = [{"concept_id": "stuffiness", "brick_classes": ["brick:CO2_Sensor"]}]
    out = runner.run("is it stuffy", concepts)
    assert [stage for stage, _ in calls] == ["parse", "post", "concept"]
    assert calls[0][1]["intent"] == "general" and calls[0][1]["general"] is True
    assert calls[2][1] == {"intent": "sensor_data", "concepts": concepts, "entities": []}
    assert out == {"general": {"rules": ["parse_rule", "concept_rule"], "final": "analytics"}}


# ── the models, end to end (no GraphDB, no orchestrator import) ────────────────────────


@pytest.fixture(scope="module")
def models(tmp_path_factory):
    ttl = tmp_path_factory.mktemp("hbco") / "mini.ttl"
    ttl.write_text(_HBCO, encoding="utf-8")
    snapshot = {
        "namespace": NS,
        "entities": ENTITIES,
        "register": {"record_counts": {"Permit": 5}, "amenities": {}},
    }
    return rr.Models(snapshot, rr.load_concept_map([ttl]), None, "no contract in this test", False)


def test_one_question_is_scored_by_every_model(models):
    q = SimpleNamespace(
        id="MB-test",
        text="How many permits are open in room 5.01 while it is stuffy?",
        primary="stakeholder_catalogue_37",
        group="Facilities",
        asked_before=False,
        tags={},
        evidence={"Authoritative_Sources": "the CMMS owner", "Sensors_Required": ""},
    )
    row = rr.evaluate(models, q)
    assert row["register"]["held"] == "Permit"
    assert row["concepts"] == ["stuffiness"] and row["measurand"] is True
    assert row["referent"]["status"] == "resolved" and row["referent"]["weak"] is False
    assert row["implied_sources"] == ["cmms_work"]
    assert row["contract"] == {}  # no contract runner was given
    assert row["flags"]["concept"] and row["flags"]["register"] and row["flags"]["referent"]
    assert row["flags"]["nothing"] is False


def test_a_question_naming_nothing_the_models_know_reaches_nothing(models):
    q = SimpleNamespace(
        id="MB-none",
        text="Tell me a fun fact",
        primary="survey",
        group="OTHER",
        asked_before=False,
        tags={},
        evidence={},
    )
    assert rr.evaluate(models, q)["flags"]["nothing"] is True


# ── the pool and the CLI ───────────────────────────────────────────────────────────────


def _bank(tmp_path, held: str):
    mb = rr.master_bank()
    raw = [
        mb.RawQuestion(t, mb.Appearance("stakeholder_catalogue_37", "g", "test"))
        for t in (held, "which lift is out of service", "is the atrium warm", "who owns the roof")
    ]
    path = tmp_path / "h.txt"
    path.write_text(hashlib.sha1(mb.normalise(held).encode("utf-8")).hexdigest() + "\n", "utf-8")
    return mb.build_bank(raw, mb.read_hash_file(path))


def test_the_evaluation_pool_never_contains_a_held_out_question(tmp_path):
    held = "which corridor is quietest after six"
    bank = _bank(tmp_path, held)
    assert len(bank.holdout()) == 1
    for sample in (0, 2, 50):
        pool = rr.select_pool(bank, [], sample, 4)
        assert held not in [q.text for q in pool]
        assert len(pool) == (min(sample, 3) if sample else 3)


def test_the_pool_check_is_a_hard_error_if_a_held_out_question_ever_slips_in(tmp_path):
    bank = _bank(tmp_path, "which corridor is quietest after six")
    bank.tuning = lambda: list(bank.questions)  # a broken bank that no longer excludes it
    with pytest.raises(RuntimeError, match="held-out"):
        rr.select_pool(bank, [], 0, 1)


def test_the_cli_refuses_to_run_without_a_hash_file(tmp_path, monkeypatch, capsys):
    mb = rr.master_bank()
    monkeypatch.delenv(mb.HASH_FILE_ENV, raising=False)
    monkeypatch.setattr(mb, "DEFAULT_HASH_FILE", tmp_path / "absent.txt")
    assert rr.main(["--md", ""]) == 2
    assert "holdout" in capsys.readouterr().err


def test_quiet_logging_restores_logging():
    before = logging.root.manager.disable
    with rr.quiet_logging():
        assert logging.root.manager.disable == logging.CRITICAL
    assert logging.root.manager.disable == before


# ── the report ─────────────────────────────────────────────────────────────────────────


def test_the_markdown_carries_every_section_and_only_pool_questions():
    rows = [
        _evaluated(
            "Where is the cafeteria today?",
            referent={
                "kind": "space",
                "phrase": "cafeteria",
                "status": "not_found",
                "weak": False,
                "head_exists": False,
            },
        ),
        _evaluated("How is the air quality here?"),
        _evaluated("air quality report please", source="stakeholder_catalogue_37", group="Facilities"),
    ]
    summary = rr.summarise(rows, None, "not run in this test")
    meta = {
        "date": "2026-01-01",
        "snapshot_taken_at": "t",
        "endpoint": "e",
        "namespace": NS,
        "entity_counts": "6 subjects",
        "concepts": 2,
        "concept_terms": 3,
        "concept_files": ["a.ttl"],
        "held_registers": 1,
        "events_store_classes": [],
        "seconds": 1.0,
        "bank": {
            "unique_questions": 3,
            "holdout_matched_in_bank": 0,
            "holdout_hashes": 0,
            "holdout_hashes_not_in_bank": 0,
            "raw_rows_by_source": {"survey": 2},
        },
    }
    text = rr.render_markdown(summary, meta)
    for heading in (
        "## 1. The pool",
        "## 2. Reach by source",
        "### 3.3 Referents",
        "## 5. Routing",
        "## 6. The data source",
        "## 7. Method",
    ):
        assert heading in text
    assert "cafeteria" in text  # the missing-referent list names it
    assert "Not evaluated" in text  # routing was not run, and the report says so
    assert summary["missing_referents"][0]["referent"] == "cafeteria"
