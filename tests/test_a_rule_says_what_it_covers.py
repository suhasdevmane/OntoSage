# -*- coding: utf-8 -*-
"""TODO-528 / BUG-482 — a standing rule covers a place, and says which points that is.

THE TWO HALVES OF ONE DEFECT
-----------------------------
BUG-482: "a concept rule watches ONE point of however many carry the class". A concept
resolves to a Brick CLASS — 288 points for `Temperature_Sensor` on this building — and the
engine evaluated exactly one of them while the rule read as though it covered the class.

TODO-528: "a concept rule cannot say WHICH floor or space it covers". The shipped rule
`humidity_damp_floor3` is named for floor 3, and the name was the ONLY place that fact
existed. The trigger had no spatial qualifier, so the author's two options were `scope:
all` (notify about humidity on every floor, under a rule promising one) and `scope:
first_reporting` (watch one arbitrary humidity sensor, which could be on any floor). Both
are wrong about the floor; only the second is wrong QUIETLY, which is why it was what
shipped.

They are the same weakness because neither is fixable alone. Widening a rule to every
matching point is only safe once the rule can say where "matching" stops; and a place is
only useful once the rule watches everything in it.

WHAT MUST HOLD
--------------
1. A rule may declare `floor:` and/or `space:` and watches EVERY point of its concept
   located there — resolved through the graph's spatial hierarchy, never by reading a floor
   number out of a sensor's name (that approach is documented as unreliable in
   `scripts/floor_modality_matrix.py`).
2. A rule REPORTS what it covers. The original defect was not a bad choice of point; it was
   that nothing anywhere said which point had been chosen.
3. A scope matching nothing leaves the rule watching nothing and SAYS so. A rule quietly
   re-widened to the building would be the defect wearing the fix's clothes.
4. A rule that declares no place behaves EXACTLY as before. Asserted by construction below,
   not by inspection: the pre-existing code path is a separate method, and these tests make
   the spatial one explode if an unscoped rule reaches it.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.rules_engine import (  # noqa: E402
    SCOPE_ALL,
    SCOPE_FIRST,
    SCOPE_POINT_LIMIT,
    EcaRule,
    RuleAction,
    RuleCoverage,
    RulePlace,
    RulesEngine,
    RuleTrigger,
)

REPO = Path(__file__).resolve().parent.parent


# ── fixtures ─────────────────────────────────────────────────────────────────


def _always(value):
    async def _f(*_a, **_k):
        return value

    return _f


def _noop():
    async def _f(*_a, **_k):
        return None

    return _f


def _engine(
    values: Dict[str, float],
    fired: List[Tuple[str, str, float]],
    *,
    in_place: Optional[Dict[str, List[str]]] = None,
) -> RulesEngine:
    """An engine whose graph, store and notifier are all fixtures.

    `in_place` maps a place key ("floor=3", "space=5.01") to the sensor uuids the graph
    would return for it — standing in for the SPARQL the query builder is tested separately
    against, so these assertions are about the engine's decisions and not about GraphDB.
    """

    async def _fetch(uuid: str) -> Optional[float]:
        return values.get(uuid)

    async def _notify(rule: EcaRule, uuid: str, value: float) -> None:
        fired.append((rule.id, uuid, value))

    eng = RulesEngine(building_id="bldgX", value_fetcher=_fetch, notifier=_notify)
    eng._breach_sustained = _always(True)  # type: ignore[assignment]
    eng._in_cooldown = _always(False)  # type: ignore[assignment]
    eng._mark_cooldown = _noop()  # type: ignore[assignment]
    eng._clear_breach = _noop()  # type: ignore[assignment]

    class _M:
        brick_classes = ["brick:Humidity_Sensor"]

    async def _resolve(_c):
        return [_M()]

    import orchestrator.services.concept_resolver as cr

    cr.concept_resolver.resolve = _resolve  # type: ignore[assignment]

    table = in_place or {}

    async def _scoped(_cls, place: RulePlace) -> Tuple[List[str], bool]:
        key = "+".join(
            p
            for p in (
                f"floor={place.floor}" if place.floor else "",
                f"space={place.space}" if place.space else "",
            )
            if p
        )
        return list(table.get(key, [])), False

    eng._uuids_for_class_in_place = _scoped  # type: ignore[assignment]
    return eng


def _rule(
    *,
    scope: Optional[str] = SCOPE_ALL,
    floor: Optional[str] = None,
    space: Optional[str] = None,
    uuid: Optional[str] = None,
    threshold: float = 65.0,
) -> EcaRule:
    return EcaRule(
        id="humidity_damp_floor3",
        name="High humidity — possible damp — floor 3",
        trigger=RuleTrigger(
            sensor_uuid=uuid,
            concept=None if uuid else "damp",
            op=">",
            threshold=threshold,
            scope=scope,
            floor=floor,
            space=space,
        ),
        action=RuleAction(type="notify", message="Humidity {value:.0f}%"),
    )


def _run(coro):
    return asyncio.run(coro)


# ── 1. a rule can say where it applies, and covers everything there ──────────


def test_a_rule_can_declare_the_floor_its_name_promises():
    """TODO-528: the trigger had `concept` and `scope` and no way to say WHERE."""
    t = RuleTrigger(concept="damp", scope=SCOPE_ALL, floor="3")
    assert t.floor == "3"
    assert RulesEngine._place_of(_rule(floor="3")) == RulePlace(floor="3", space=None)


def test_a_floor_scoped_rule_watches_every_matching_point_on_that_floor():
    """BUG-482, the half about count: three humidity points on floor 3, all three watched,
    and the two that breach both reported. Before this the rule evaluated exactly one."""
    fired: List[Tuple[str, str, float]] = []
    eng = _engine(
        {"h3a": 72.0, "h3b": 40.0, "h3c": 80.0, "h5a": 90.0},
        fired,
        in_place={"floor=3": ["h3a", "h3b", "h3c"]},
    )
    assert _run(eng._evaluate_rule(_rule(scope=SCOPE_ALL, floor="3"))) is True
    assert sorted(u for _, u, _ in fired) == ["h3a", "h3c"]


def test_a_floor_scoped_rule_does_not_reach_a_breaching_point_on_another_floor():
    """The scope has to EXCLUDE, or it is decoration. `h5a` reads 90% and must stay silent
    under a rule scoped to floor 3."""
    fired: List[Tuple[str, str, float]] = []
    eng = _engine(
        {"h3b": 40.0, "h5a": 90.0}, fired, in_place={"floor=3": ["h3b"], "floor=5": ["h5a"]}
    )
    assert _run(eng._evaluate_rule(_rule(scope=SCOPE_ALL, floor="3"))) is False
    assert fired == []


def test_a_space_scope_narrows_to_one_room():
    fired: List[Tuple[str, str, float]] = []
    eng = _engine({"h301": 72.0, "h302": 99.0}, fired, in_place={"space=3.01": ["h301"]})
    assert _run(eng._evaluate_rule(_rule(scope=SCOPE_ALL, space="3.01"))) is True
    assert [u for _, u, _ in fired] == ["h301"]


def test_floor_and_space_together_are_a_conjunction():
    """Both declared means both applied — not one silently winning."""
    fired: List[Tuple[str, str, float]] = []
    eng = _engine({"h301": 72.0}, fired, in_place={"floor=3+space=3.01": ["h301"]})
    assert _run(eng._evaluate_rule(_rule(scope=SCOPE_ALL, floor="3", space="3.01"))) is True
    assert [u for _, u, _ in fired] == ["h301"]


def test_first_reporting_inside_a_place_still_watches_exactly_one():
    """`first_reporting` is not deprecated by a place — it now means one point ON FLOOR 3
    rather than one point anywhere, and the coverage record says which."""
    fired: List[Tuple[str, str, float]] = []
    eng = _engine({"h3a": 72.0, "h3c": 80.0}, fired, in_place={"floor=3": ["h3a", "h3c"]})
    assert _run(eng._evaluate_rule(_rule(scope=SCOPE_FIRST, floor="3"))) is True
    assert len(fired) == 1
    cov = eng.coverage("humidity_damp_floor3")
    assert cov is not None and len(cov.watched) == 1 and cov.in_scope == 2


# ── 2. the rule reports what it covers ───────────────────────────────────────


def test_the_engine_can_be_asked_which_points_a_rule_covers():
    """The original defect was not a bad choice of point — it was that NOTHING said which
    point had been chosen. A rule's coverage is now a first-class, readable record."""
    fired: List[Tuple[str, str, float]] = []
    eng = _engine({"h3a": 50.0, "h3c": 51.0}, fired, in_place={"floor=3": ["h3a", "h3c"]})
    eng._sensor_of.update({"h3a": "bldg:Zone_Air_Humidity_Sensor_3.01"})
    _run(eng._evaluate_rule(_rule(scope=SCOPE_ALL, floor="3")))

    cov = eng.coverage("humidity_damp_floor3")
    assert isinstance(cov, RuleCoverage)
    assert cov.floor == "3" and cov.scope == SCOPE_ALL
    assert sorted(cov.watched) == ["h3a", "h3c"]
    assert "bldg:Zone_Air_Humidity_Sensor_3.01" in cov.sensors
    text = cov.describe()
    assert "floor 3" in text and "2 point(s)" in text
    assert "humidity_damp_floor3" in text


def test_an_unscoped_rule_also_reports_its_coverage():
    """A rule with no place still says what it watches — otherwise the honesty this row
    buys would apply only to rules someone had already thought about."""
    fired: List[Tuple[str, str, float]] = []
    eng = _engine({"u1": 1.0}, fired)
    eng._resolve_uuids_anywhere = _always(["u1"])  # type: ignore[assignment]
    _run(eng._evaluate_rule(_rule(scope=SCOPE_ALL)))
    cov = eng.coverage("humidity_damp_floor3")
    assert cov is not None and cov.watched == ["u1"]
    assert cov.floor is None and "the whole building" in cov.describe()


def test_coverage_report_lists_only_rules_the_engine_loaded():
    eng = _engine({}, [])
    assert eng.coverage_report() == []
    assert eng.coverage("nothing-resolved-yet") is None


# ── 3. a scope that matches nothing is stated, never widened ─────────────────


def test_a_place_matching_no_point_leaves_the_rule_watching_nothing(caplog):
    """ "Never fabricate": the failure must be a stated absence, not a fallback to some
    unrelated humidity sensor — which is precisely the behaviour being removed."""
    fired: List[Tuple[str, str, float]] = []
    eng = _engine({"h5a": 90.0}, fired, in_place={"floor=5": ["h5a"]})

    async def _must_not_run(_rule):  # pragma: no cover - the assertion is that it doesn't
        raise AssertionError("a scoped rule fell back to the unscoped, building-wide chooser")

    eng._resolve_uuid = _must_not_run  # type: ignore[assignment]
    eng._resolve_uuids_anywhere = _must_not_run  # type: ignore[assignment]

    with caplog.at_level(logging.WARNING):
        assert _run(eng._evaluate_rule(_rule(scope=SCOPE_ALL, floor="9"))) is False
    assert fired == []
    msg = caplog.text
    assert "floor 9" in msg
    assert "cannot fire" in msg
    assert "NOT falling back" in msg


def test_a_place_whose_points_are_all_silent_is_reported_as_such(caplog):
    """Two different nothings. "No point is there" is a scope/graph problem; "the points
    are there and none is reporting" is a data problem, and they need different fixes."""
    fired: List[Tuple[str, str, float]] = []
    eng = _engine({}, fired, in_place={"floor=3": ["h3a", "h3b"]})
    with caplog.at_level(logging.WARNING):
        assert _run(eng._evaluate_rule(_rule(scope=SCOPE_ALL, floor="3"))) is False
    assert "NONE is reporting a value" in caplog.text
    cov = eng.coverage("humidity_damp_floor3")
    assert cov is not None and cov.in_scope == 2 and cov.watched == []


def test_a_silent_point_in_scope_is_excluded_not_counted_as_within_threshold():
    """A point with no reading is not a healthy point. The coverage record keeps both
    numbers so the difference stays visible."""
    fired: List[Tuple[str, str, float]] = []
    eng = _engine({"h3a": 72.0}, fired, in_place={"floor=3": ["h3a", "h3b", "h3c"]})
    assert _run(eng._evaluate_rule(_rule(scope=SCOPE_ALL, floor="3"))) is True
    cov = eng.coverage("humidity_damp_floor3")
    assert cov is not None
    assert cov.in_scope == 3 and cov.watched == ["h3a"]


# ── 4. an unscoped rule is untouched ─────────────────────────────────────────


def test_an_unscoped_rule_never_reaches_the_spatial_path():
    """The non-negotiable, asserted by construction rather than by reading the diff."""
    fired: List[Tuple[str, str, float]] = []
    eng = _engine({"u1": 99.0}, fired)

    async def _must_not_run(*_a, **_k):  # pragma: no cover - the assertion is that it doesn't
        raise AssertionError("a rule declaring no place was routed through the place query")

    eng._resolve_uuids_in_place = _must_not_run  # type: ignore[assignment]
    eng._uuids_for_class_in_place = _must_not_run  # type: ignore[assignment]
    eng._resolve_uuids_anywhere = _always(["u1"])  # type: ignore[assignment]

    assert _run(eng._evaluate_rule(_rule(scope=SCOPE_ALL))) is True
    assert [u for _, u, _ in fired] == ["u1"]


def test_the_pre_existing_resolver_is_still_the_one_an_unscoped_rule_uses():
    """`_resolve_uuids_anywhere` is the old `_resolve_uuids` body under a new name. If a
    refactor ever merged the two paths, an existing rule's behaviour would start depending
    on spatial code it never asked for."""
    import inspect

    src = inspect.getsource(RulesEngine._resolve_uuids_anywhere)
    assert "_uuids_for_class(" in src, "the unscoped path no longer uses the unscoped query"
    assert "_place" not in src, "spatial logic leaked into the path unscoped rules take"


def test_a_direct_uuid_rule_that_also_declares_a_place_does_not_load(caplog):
    """A place cannot narrow a single named point, so such a rule READS as scoped while
    the scope changes nothing — the same quiet lie this row exists to remove."""
    r = _rule(uuid="abc-123", scope=None, floor="3")
    with caplog.at_level(logging.WARNING):
        assert RulesEngine._place_is_meaningful(r) is False
    assert "DISABLED" in caplog.text
    assert RulesEngine._place_is_meaningful(_rule(uuid="abc-123", scope=None)) is True
    assert RulesEngine._place_is_meaningful(_rule(scope=SCOPE_ALL, floor="3")) is True


def test_a_scoped_rule_must_still_declare_all_or_first_reporting():
    """A place answers WHERE. It does not answer whether the rule means every point there
    or one of them, so the V12-20 declaration is still required."""
    assert RulesEngine._scope_is_declared(_rule(scope=None, floor="3")) is False
    assert RulesEngine._scope_is_declared(_rule(scope=SCOPE_ALL, floor="3")) is True


# ── 5. the place is resolved through the graph, not out of a name ───────────


def _query(floor: Optional[str] = None, space: Optional[str] = None) -> str:
    eng = RulesEngine(building_id="bldgX")
    eng._namespace = lambda: "http://example.org/bldgX#"  # type: ignore[assignment]
    q = eng._place_sparql("brick:Humidity_Sensor", RulePlace(floor=floor, space=space))
    assert q is not None
    return q


def test_the_floor_is_resolved_through_the_spatial_hierarchy():
    """`scripts/floor_modality_matrix.py` records why the alternative is wrong: a point's
    NAME is a convention, not a fact, and a building naming its points differently gets an
    empty — or worse, a partly right — answer. Same traversal as
    `sparql_agent._floor_scoped_sparql`."""
    q = _query(floor="3")
    assert "brick:hasLocation ?loc" in q
    assert "(brick:isPartOf|^brick:hasPart)*" in q
    assert "?floor a brick:Floor" in q


def test_the_floor_is_not_inferred_from_the_sensors_own_name():
    """The tempting, wrong version: pull "3" out of `Zone_Air_Humidity_Sensor_3.01`."""
    q = _query(floor="3")
    assert "?sensorLabel" not in q
    # The one read of the sensor's IRI is the BUILDING filter, not a floor inference.
    assert q.count("STR(?sensor)") == 1
    assert "STRSTARTS(STR(?sensor)" in q
    floor_block = q[q.index("?floor a brick:Floor") : q.index("\n} ORDER BY")]
    assert "?sensor" not in floor_block, "the floor constraint reads the sensor's own name"


def test_the_place_name_is_matched_against_the_places_own_identity():
    """ "3", "Floor3" and "Floor 3 (Third Floor)" are the same floor. A rule author should
    not have to know which spelling this building chose."""
    q = _query(floor="3")
    assert "?floorLocal" in q and "?floorLabel" in q and "?floorNum" in q
    assert '"3"' in q
    qs = _query(space="5.01")
    assert "?spaceLocal" in qs and "?spaceLabel" in qs
    assert '"5.01"' in qs


def test_the_building_filter_survives_the_scope():
    """Without it a rule for one building binds to another building's sensors."""
    assert "STRSTARTS" in _query(floor="3")


def test_the_scoped_query_is_distinct():
    """A point typed Zone_Air_Humidity_Sensor AND Humidity_Sensor AND
    Relative_Humidity_Sensor satisfies `a/rdfs:subClassOf*` by three paths and would
    otherwise eat three rows of the limit while looking like three points."""
    assert "SELECT DISTINCT" in _query(floor="3")


def test_the_scoped_query_is_bounded_and_truncation_is_reported():
    q = _query(floor="3")
    assert f"LIMIT {SCOPE_POINT_LIMIT}" in q
    assert SCOPE_POINT_LIMIT > RulesEngine.CLASS_CANDIDATES, (
        "a place-bounded set is an intended, finite set; bounding it as tightly as an "
        "unbounded class scan would silently drop points the rule claims to cover"
    )
    import inspect

    assert "truncated" in inspect.getsource(RulesEngine._resolve_uuids_in_place)


def test_a_place_name_cannot_end_the_sparql_literal():
    """These strings are interpolated into a FILTER. The grammar is the guard, and it is
    enforced by the MODEL so a malformed rule is refused at load rather than producing an
    empty result later."""
    for hostile in ('3" }  #', "3\\", '3" || "1" = "1', "3\n}"):
        with pytest.raises(Exception):
            RuleTrigger(concept="damp", scope=SCOPE_ALL, floor=hostile)
    eng = RulesEngine(building_id="bldgX")
    # And defence in depth: the builder refuses too, for a place assembled in code.
    assert eng._place_sparql("brick:Humidity_Sensor", RulePlace(floor='3" }')) is None


# ── 5b. the query, executed against a graph ─────────────────────────────────
#
# Everything above checks the query's TEXT. Text assertions pass on a query that never
# matched anything — which is the exact way BUG-481's second layer survived: the join was
# on a predicate that exists twice in the repository, and every string a reader would have
# checked for was present. So the query is also RUN, against a graph built here with two
# floors, two naming conventions and a multi-typed point.


def _fixture_graph():
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(
        data="""
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix ref:   <https://brickschema.org/schema/Brick/ref#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix x:     <http://example.org/x#> .
@prefix other: <http://example.org/other#> .

brick:Zone_Air_Humidity_Sensor rdfs:subClassOf brick:Humidity_Sensor .

x:Floor3 a brick:Floor ; rdfs:label "Floor 3 (Third Floor)" .
x:Level5 a brick:Floor ; rdfs:label "Level 5" .
x:Floor3 brick:hasPart x:Room3.01, x:Room3.02 .
x:Room3.01 rdfs:label "Room 3.01" .
x:Room5.02 brick:isPartOf x:Level5 .

x:H301 a brick:Zone_Air_Humidity_Sensor, brick:Humidity_Sensor ;
    brick:hasLocation x:Room3.01 ;
    ref:hasExternalReference [ ref:hasTimeseriesId "u-301" ; ref:storedAt x:db1 ] .
x:H302 a brick:Zone_Air_Humidity_Sensor ;
    brick:hasLocation x:Room3.02 ;
    ref:hasExternalReference [ ref:hasTimeseriesId "u-302" ; ref:storedAt x:db1 ] .
x:H502 a brick:Humidity_Sensor ;
    brick:hasLocation x:Room5.02 ;
    ref:hasExternalReference [ ref:hasTimeseriesId "u-502" ; ref:storedAt x:db1 ] .
other:H303 a brick:Humidity_Sensor ;
    brick:hasLocation x:Room3.01 ;
    ref:hasExternalReference [ ref:hasTimeseriesId "u-303" ; ref:storedAt x:db1 ] .
""",
        format="turtle",
    )
    return g


def _run_query(q: str):
    return sorted(str(row.uuid) for row in _fixture_graph().query(q))


def _scoped_query(**place) -> str:
    eng = RulesEngine(building_id="bldgX")
    eng._namespace = lambda: "http://example.org/x#"  # type: ignore[assignment]
    q = eng._place_sparql("brick:Humidity_Sensor", RulePlace(**place))
    assert q is not None
    return q


def test_the_query_actually_returns_the_points_on_the_named_floor():
    """`u-302` is reached only through Floor3 -> hasPart -> Room3.02: no name was parsed,
    and that room's IRI is the only thing carrying "3.02" anywhere."""
    assert _run_query(_scoped_query(floor="3")) == ["u-301", "u-302"]


def test_the_query_returns_a_point_whose_room_uses_the_inverse_relation():
    """Rooms link upward with `isPartOf` in some buildings and downward with `hasPart` in
    others. Floor 5 here uses the other one."""
    assert _run_query(_scoped_query(floor="5")) == ["u-502"]


def test_a_floor_spelled_as_a_level_is_still_that_floor():
    """`x:Level5` / "Level 5" — a rule author should not have to know the convention."""
    assert _run_query(_scoped_query(floor="5")) == ["u-502"]


def test_the_query_excludes_another_buildings_sensor_in_the_same_room():
    """`other:H303` sits in Room3.01 and must not be watched by bldgX's rule."""
    assert "u-303" not in _run_query(_scoped_query(floor="3"))


def test_a_multityped_point_is_returned_once():
    """`x:H301` is both Zone_Air_Humidity_Sensor and Humidity_Sensor, so it satisfies
    `a/rdfs:subClassOf*` twice. Without DISTINCT it is two rows of the limit."""
    assert _run_query(_scoped_query(floor="3")).count("u-301") == 1


def test_the_space_scope_executes_and_narrows_to_the_room():
    assert _run_query(_scoped_query(space="3.01")) == ["u-301"]
    assert _run_query(_scoped_query(space="Room3.02")) == ["u-302"]


def test_floor_and_space_together_execute_as_a_conjunction():
    assert _run_query(_scoped_query(floor="3", space="3.01")) == ["u-301"]
    assert _run_query(_scoped_query(floor="5", space="3.01")) == []


def test_a_place_that_does_not_exist_returns_nothing_rather_than_everything():
    """The honesty requirement, proved against a graph: no match is no rows, not a
    silently-widened match."""
    assert _run_query(_scoped_query(floor="9")) == []
    assert _run_query(_scoped_query(space="nowhere")) == []


# ── 6. building-agnostic ─────────────────────────────────────────────────────


def _code(fn) -> str:
    """Source with docstrings stripped, per `test_rules_engine_resolves_its_own_namespace`.

    The assertions below are about what the code DOES. The docstrings quote this building's
    own floor spellings as the example of what the query must tolerate — so a naive
    substring search fails on the documentation of the very portability it checks.
    """
    import ast
    import inspect

    # Re-wrapped in a class rather than dedented: `_place_sparql` embeds a SPARQL block
    # whose lines start at column 0, so there is no common indent to strip.
    tree = ast.parse("class _Wrapper:\n" + inspect.getsource(fn))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def test_nothing_in_the_spatial_scope_code_names_a_building():
    """Contract rule 3. Litmus test: would this run unchanged for another building?"""
    src = "".join(
        _code(fn)
        for fn in (
            RulesEngine._place_sparql,
            RulesEngine._resolve_uuids_in_place,
            RulesEngine._uuids_for_class_in_place,
            RulesEngine._place_of,
            RulesEngine._place_is_meaningful,
        )
    ).lower()
    for literal in ("bldg1", "bldg2", "bldg3", "abacws", "room5.", "floor3", "sensordb"):
        assert literal not in src, f"the spatial scope code contains the literal {literal!r}"


def test_no_floor_count_or_floor_list_is_assumed():
    """Floors are whatever the graph says they are — the query never enumerates them."""
    q = _query(floor="3")
    assert "VALUES ?floor" not in q
    assert "IN (" not in q


# ── 7. the shipped rule now means what its name says ────────────────────────


def test_the_shipped_rule_named_for_a_floor_declares_that_floor():
    """TODO-528's whole content: the rule's NAME was the only place its scope existed, and
    nothing enforces a name."""
    import re

    import yaml

    path = REPO / "input" / "rules.yaml"
    if not path.is_file():  # pragma: no cover - parked tree
        pytest.skip("no active building")
    checked = 0
    for entry in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("rules", []):
        trig = entry.get("trigger", {}) or {}
        if not trig.get("concept") or trig.get("sensor_uuid"):
            continue
        named = re.search(r"floor[_ ]?(\d+)", f"{entry.get('id','')} {entry.get('name','')}", re.I)
        if not named:
            continue
        checked += 1
        assert str(trig.get("floor")) == named.group(1), (
            f"rule {entry.get('id')!r} is named for floor {named.group(1)} and declares "
            f"floor={trig.get('floor')!r} — the name is not a scope"
        )
        assert trig.get("scope") == SCOPE_ALL, (
            f"rule {entry.get('id')!r} names a floor and watches only part of it; with the "
            "floor declared there is no longer a reason to watch one point"
        )
    assert checked, "no shipped concept rule names a floor — did this rule get renamed?"


def test_every_shipped_place_is_a_legal_place_name():
    import yaml

    path = REPO / "input" / "rules.yaml"
    if not path.is_file():  # pragma: no cover - parked tree
        pytest.skip("no active building")
    for entry in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("rules", []):
        trig = entry.get("trigger", {}) or {}
        if trig.get("floor") or trig.get("space"):
            # Round-trips through the model, so a shipped rule cannot carry a place the
            # loader would refuse.
            RuleTrigger(**trig)
