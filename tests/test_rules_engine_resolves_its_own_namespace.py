# -*- coding: utf-8 -*-
"""Every concept-triggered rule was dark (BUG-481).

`_uuid_for_class` opened with:

    bldg_ns = settings.ONTOLOGY_NAMESPACE

`Settings` has no such attribute and never has. The AttributeError was raised OUTSIDE that
method's own try block, so it propagated up to `_resolve_uuid`'s broad `except Exception`
and was logged as:

    [rules_engine] concept resolve failed for temperature_reading:
        'Settings' object has no attribute 'ONTOLOGY_NAMESPACE'
    [rules_engine] concept resolve failed for crowded: ...
    [rules_engine] concept resolve failed for busyness: ...
    [rules_engine] concept resolve failed for lift_status: ...

— once per rule, per cycle, continuously. Every concept-triggered rule resolved to no UUID
and could never fire.

WHY IT SURVIVED
---------------
Two things hid it, and neither was the absence of a test.

First, the MESSAGE named the wrong component. "concept resolve failed for
temperature_reading" reads as "the concept resolver could not map this lay term" — a data
problem, fixed in `hbco_mappings.ttl`. The actual fault was a programming error two calls
away, in a method the message never mentions. A log that misattributes its own cause sends
the reader to the wrong file.

Second, a rule that never fires looks exactly like a rule whose condition is not met. The
ECA engine's normal state IS silence, so a total failure and correct operation produce the
same observable output. `input/rules.yaml` was found and loaded — V10 recorded the engine
as newly live — and it was live and inert.

The namespace is now resolved from the engine's OWN `_building_id`, not the process-global
default: `RulesEngine` is constructed per building, and a background loop has no request
context to read one from.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.rules_engine import RulesEngine  # noqa: E402


def _engine(building_id: str = "bldg1") -> RulesEngine:
    return RulesEngine(building_id=building_id)


def _code(fn) -> str:
    """Source with comments and docstrings stripped.

    These assertions are about what the code DOES. The comments beside the fix quote the
    old message and the old setting name verbatim — that is the point of them — so a naive
    substring search over raw source fails on the documentation of the very bug it checks.
    """
    import ast

    tree = ast.parse(inspect.getsource(fn).lstrip())
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


def test_the_namespace_resolves_without_raising():
    ns = _engine()._namespace()
    assert isinstance(ns, str)


def test_the_namespace_is_not_empty_for_the_active_building():
    """An empty namespace makes the STRSTARTS filter match everything, silently."""
    assert _engine()._namespace(), (
        "no namespace resolved, so the query's building filter would match every sensor "
        "in the repository regardless of which building the rule belongs to"
    )


def test_the_setting_that_never_existed_is_gone():
    from shared.config import settings

    assert not hasattr(settings, "ONTOLOGY_NAMESPACE")
    assert "settings.ONTOLOGY_NAMESPACE" not in _code(RulesEngine)


def test_it_reads_the_engines_own_building_not_the_process_global():
    """`RulesEngine` is per building; a background loop has no request context."""
    assert "self._building_id" in _code(RulesEngine._namespace), (
        "the namespace is taken from the process-global setting, so a second building's "
        "rules would filter against the first building's namespace"
    )


def test_an_unknown_building_still_returns_a_string_rather_than_raising():
    """The failure mode being fixed is an exception escaping into a generic warning."""
    assert isinstance(_engine("no-such-building")._namespace(), str)


def test_the_warning_names_the_component_that_failed():
    """A message that misattributes its cause sends the reader to the wrong file."""
    src = _code(RulesEngine._resolve_uuid)
    assert (
        "concept resolve failed" not in src
    ), "the warning still blames the concept resolver for faults raised elsewhere"
    assert "type(e).__name__" in src, (
        "the exception TYPE is what distinguishes a missing mapping from a programming "
        "error; without it both read the same"
    )
    assert "rule.id" in src, "the warning does not say WHICH rule cannot fire"


def test_the_warning_says_the_consequence():
    """'failed' does not tell an operator that a standing alert is now dark."""
    assert "cannot fire" in _code(RulesEngine._resolve_uuid)


def test_nothing_here_names_a_building():
    body = _code(RulesEngine._namespace).lower()
    for literal in ("bldg1", "bldg2", "bldg3", "abacws"):
        assert literal not in body


# ── the second layer: the error was gone and the failure was not ────────────
#
# Fixing the namespace stopped the AttributeError. Every concept still resolved to None,
# now SILENTLY — which is strictly worse, because the warning that had been pointing at
# the wrong component was at least pointing at something.
#
# Measured against the live graph:
#
#     ?s brick:hasExternalReference ?o  ->     2 triples
#     ?s ref:hasExternalReference   ?o  -> 2,860 triples
#
# `_uuid_for_class` joined on the `brick:` form. The two that exist come from the Brick
# vocabulary itself, so the join never matched a real sensor and the query returned empty
# for EVERY class — including `brick:Temperature_Sensor`, of which this building has 288.
#
# After the fix, live: busyness -> d7baf689… (11,812 rows), temperature_reading ->
# 89d4f4fe… (62,085 rows). Before it, both were None.


def test_the_timeseries_join_uses_the_predicate_the_graph_actually_carries():
    src = _code(RulesEngine._uuids_for_class)
    assert "ref:hasExternalReference" in src, (
        "the join is back on brick:hasExternalReference, which exists twice in the whole "
        "repository and never on a real sensor"
    )
    assert "brick:hasExternalReference" not in src


def test_the_class_match_follows_subclasses():
    """A building may type its points more specifically than the concept names them."""
    assert "rdfs:subClassOf*" in _code(RulesEngine._uuids_for_class)


def test_the_candidate_order_is_deterministic():
    """Without ORDER BY, which point a rule watches varies between restarts."""
    assert "ORDER BY" in _code(RulesEngine._uuids_for_class)


def test_the_building_filter_is_still_applied():
    """Without it a rule for one building can bind to another building's sensor."""
    assert "STRSTARTS" in _code(RulesEngine._uuids_for_class)


def test_the_log_names_the_point_where_the_choice_is_actually_made():
    """A concept rule watches ONE point of however many carry that class.

    Which one is invisible from the rule definition, so a reader assumes it covers the
    building (BUG-482). It must be named by the code that PICKS it — `_uuids_for_class`
    only returns candidates, and naming one there would describe something other than
    what happened, which is the BUG-481 mistake over again.
    """
    assert "?sensor" in _code(
        RulesEngine._uuids_for_class
    ), "the query no longer selects the sensor, so no log can name it"
    chooser = _code(RulesEngine._resolve_uuid)
    assert "THIS point only" in chooser
    assert "_sensor_of" in chooser, "the log names a uuid rather than the sensor"


def test_a_dead_point_is_not_chosen_when_a_reporting_one_exists():
    """Deterministic is not the same as useful.

    `ORDER BY ?sensor LIMIT 1` made the choice reproducible and still wrong: 'damp' bound
    to RH_Sensor_F0, which holds ZERO rows, for a rule named humidity_damp_floor3. It
    bound and still could not fire — the failure moved one step later, where nothing logs
    a problem at all. The engine already knows how to read a point, so it asks.
    """
    src = _code(RulesEngine._resolve_uuid)
    assert "_uuids_for_class" in src, "only one candidate is fetched, so a dead point ends it"
    assert "_value_fetcher" in src, "candidates are not tested for whether they report"


def test_the_candidate_search_is_bounded():
    """This runs on a polling loop and each candidate costs a store read."""
    assert 1 < RulesEngine.CLASS_CANDIDATES <= 25
    assert "CLASS_CANDIDATES" in _code(RulesEngine._uuids_for_class)


def test_it_says_so_when_no_point_of_the_class_reports():
    """Silence here is indistinguishable from a rule whose condition is not met."""
    src = _code(RulesEngine._resolve_uuid)
    assert "no point of those classes is reporting" in src
    assert "cannot fire" in src
