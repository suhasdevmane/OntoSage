# -*- coding: utf-8 -*-
"""BUG-544: checking that a word is NOT in the graph must not cost a full graph scan.

"Have closures, room moves and route changes reached each attendee…" picked up "moves" as a
referent. The existence check walked every triple for it (27.6 s on bldg1), crossed the 30 s
client timeout under load, and the turn declined with "the existence check didn't complete
in time". The Fuseki fallback then replaced GraphDB's timeout with a DNS error, hiding why.
"""

import asyncio
import inspect

import pytest

from orchestrator.services.referent_resolver import ReferentResolver

pytestmark = pytest.mark.unit

NS = "http://example.org/bldg#"


def _resolver(label_hit: bool, iri_hit: bool):
    queries = []

    async def _exec(q):
        queries.append(q)
        hit = label_hit if "rdfs:label ?l" in q else iri_hit
        return {"results": {"bindings": [{"s": {"value": NS + "x"}}] if hit else []}}

    return ReferentResolver(_exec), queries


def test_no_query_scans_every_triple():
    r, queries = _resolver(False, False)
    assert asyncio.run(r._exists("moves", NS)) is False
    assert len(queries) == 2
    assert not any("?s ?p ?o" in q for q in queries)


def test_a_label_hit_answers_without_the_second_lookup():
    r, queries = _resolver(True, False)
    assert asyncio.run(r._exists("atrium", NS)) is True
    assert len(queries) == 1


def test_an_unlabelled_subject_is_still_found_by_its_iri():
    r, queries = _resolver(False, True)
    assert asyncio.run(r._exists("chiller", NS)) is True
    assert "?s a ?type" in queries[-1]


def test_a_fuseki_failure_does_not_replace_the_graphdb_error():
    from orchestrator.agents import sparql_agent

    src = inspect.getsource(sparql_agent)
    fallback = src[src.index("trying Fuseki fallback"):]
    fallback = fallback[: fallback.index("Fallback pattern search for Fuseki too")]
    assert "except httpx.HTTPError as fuseki_err" in fallback and "raise e" in fallback
