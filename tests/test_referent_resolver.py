"""Unit tests for the referent-existence gate (services/referent_resolver.py).

Reproduces, at the unit level, the "Zone 99.99 returns fabricated data" bug: a query
naming a nonexistent zone must resolve to NOT_FOUND (→ honest clarification), not sail
through to the data pipeline. The SPARQL executor is injected and mocked, so these run
offline / in CI.
"""

import pytest

import orchestrator.services.referent_resolver as rr
from orchestrator.services.referent_resolver import (
    NO_REFERENT,
    NOT_FOUND,
    RESOLVED,
    SKIPPED,
    ReferentResolver,
    detect_referent,
)

pytestmark = pytest.mark.unit

_NS = "http://abacwsbuilding.cardiff.ac.uk/abacws#"


def _sparql_json(*subject_uris: str) -> dict:
    return {"results": {"bindings": [{"s": {"value": u}} for u in subject_uris]}}


def _exec_factory(exists_uris, suggest_uris):
    """Return an async SPARQL exec that answers existence vs suggestion queries."""

    async def _exec(query: str) -> dict:
        # The suggestion query is the only one using the dotted-id REGEX filter.
        if "REGEX" in query:
            return _sparql_json(*suggest_uris)
        return _sparql_json(*exists_uris)

    return _exec


# ── detect_referent — precision-first ────────────────────────────────────────


def test_detects_worded_zone_in_query():
    assert detect_referent("What is the temperature in Zone 99.99?", []) == "99.99"


def test_detects_dotted_id_from_entities():
    assert detect_referent("give me the latest reading", ["Zone 5.28", "temperature"]) == "5.28"


def test_ignores_threshold_value_with_no_location_word():
    # "26.5" is a comparison threshold, NOT a location — must not be gated.
    assert detect_referent("show zones warmer than 26.5 degrees", []) is None


def test_ignores_broad_query():
    assert detect_referent("what is the average temperature across all zones?", []) is None


def test_rejects_injection_token():
    # A quote/space can never be a valid referent → never reaches SPARQL.
    assert detect_referent('zone "; DROP', []) is None


# ── resolve — the gate behavior ──────────────────────────────────────────────


async def test_nonexistent_zone_is_not_found_with_suggestions():
    resolver = ReferentResolver(
        _exec_factory(
            exists_uris=[],  # nothing matches "99.99"
            suggest_uris=[f"{_NS}Air_Temperature_Sensor_5.28", f"{_NS}CO2_Sensor_5.08"],
        )
    )
    res = await resolver.resolve("temperature in Zone 99.99", [], _NS, "Abacws")
    assert res.status == NOT_FOUND
    assert res.referent == "99.99"
    assert "99.99" in res.message
    assert "5.28" in res.suggestions  # real nearby zones offered (zero-knowledge)


async def test_existing_zone_resolves():
    resolver = ReferentResolver(
        _exec_factory(exists_uris=[f"{_NS}Air_Temperature_Sensor_5.28"], suggest_uris=[])
    )
    res = await resolver.resolve("temperature in Zone 5.28", ["Zone 5.28"], _NS)
    assert res.status == RESOLVED


async def test_broad_query_has_no_referent_and_skips_sparql():
    called = {"n": 0}

    async def _exec(_q):
        called["n"] += 1
        return _sparql_json()

    res = await ReferentResolver(_exec).resolve("average temperature this week", [], _NS)
    assert res.status == NO_REFERENT
    assert called["n"] == 0  # no SPARQL issued for unscoped queries


async def test_fails_open_when_sparql_errors():
    async def _boom(_q):
        raise RuntimeError("GraphDB unreachable")

    res = await ReferentResolver(_boom).resolve("temperature in Zone 99.99", [], _NS)
    # Must NOT block — degrade to SKIPPED so the pipeline proceeds as before.
    assert res.status == SKIPPED


async def test_not_found_without_suggestions_still_honest():
    resolver = ReferentResolver(_exec_factory(exists_uris=[], suggest_uris=[]))
    res = await resolver.resolve("temperature in Zone 42.42", [], _NS, "Test Building")
    assert res.status == NOT_FOUND
    assert res.suggestions == []
    assert "list all zones" in res.message.lower()


# ── Fix 2: _fallback_pattern_search must not leak cross-zone data ─────────────


class _FakeResp:
    status_code = 200

    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class _CaptureClient:
    """Records the SPARQL sent to .post and returns empty bindings."""

    def __init__(self):
        self.queries = []

    async def post(self, endpoint, auth=None, data=None, headers=None):
        self.queries.append((data or {}).get("query", ""))
        return _FakeResp({"results": {"bindings": []}})


def _bare_agent():
    # Bypass __init__ (which builds heavy engines); _fallback_pattern_search only
    # needs _prefix_block(), which reads a module-level prefix constant.
    from orchestrator.agents.sparql_agent import SPARQLAgent

    return object.__new__(SPARQLAgent)


async def test_fallback_preserves_explicit_zone_location():
    agent = _bare_agent()
    client = _CaptureClient()
    original = (
        "SELECT ?s WHERE { ?s rdf:type brick:Air_Temperature_Sensor . "
        "?s rdfs:label ?l . FILTER(CONTAINS(?l, '5.28')) }"
    )
    await agent._fallback_pattern_search(original, client)
    assert client.queries, "fallback should have issued a query"
    # The location id from the original query must be carried into the fallback so it
    # cannot return a different zone's sensor.
    assert "CONTAINS(STR(?sensor), '5.28')" in client.queries[0]


async def test_fallback_stays_broad_without_location():
    agent = _bare_agent()
    client = _CaptureClient()
    original = "SELECT ?s WHERE { ?s rdf:type brick:Air_Temperature_Sensor . }"
    await agent._fallback_pattern_search(original, client)
    assert client.queries
    # No dotted-id constraint injected when the user named no specific zone.
    import re as _re

    assert not _re.search(r"CONTAINS\(STR\(\?sensor\), '\d{1,2}\.\d{1,2}'\)", client.queries[0])


# ── BUG-232: a failed guess at a referent must not become the answer ─────────


def _resolver(exists: bool = False):
    """A resolver over a fixture graph that knows nothing (or everything)."""

    async def _exec(_q):
        return {"results": {"bindings": [{"s": {"value": "x"}}] if exists else []}}

    return rr.ReferentResolver(_exec)


@pytest.mark.parametrize(
    "query,captured",
    [
        ("This room feels stuffy even though the CO2 reading is normal.", "feels"),
        ("Which room has the most daylight?", "has"),
        ("Would a smaller approved room plausibly reduce energy use?", "plausibly"),
    ],
)
def test_the_pattern_still_captures_the_word_after_room(query, captured):
    """Documents the cause rather than hiding it.

    `_WORDED_REF_RE` takes whatever follows "room"/"zone"/"space", and English puts a verb
    there as readily as an id. The capture is NOT narrowed -- a building may genuinely name a
    space "Atrium" -- so the fix has to live in how a MISS is handled.
    """
    assert rr.detect_referent(query, []) == captured


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "This room feels stuffy even though the CO2 reading is normal.",
        "Which room has the most daylight?",
        "Would a smaller approved room plausibly reduce energy use?",
    ],
)
async def test_a_word_shaped_unknown_token_is_not_a_referent(query):
    """The defect: the user was told 'I couldn't find "feels" in <building>' and their actual
    question went unanswered. Measured at 12 of the 20 declines in the sensor_data lane."""
    res = await _resolver(exists=False).resolve(query, [], "http://x#", "B")
    assert res.status == rr.NO_REFERENT
    assert not res.message


@pytest.mark.asyncio
async def test_an_identifier_shaped_token_still_reports_not_found():
    """The gate's whole purpose. "room 99.99" that does not exist is a real mistake and the
    user must hear about it -- this fix must not silence that."""
    res = await _resolver(exists=False).resolve(
        "What is the temperature in room 99.99?", [], "http://x#", "B"
    )
    assert res.status == rr.NOT_FOUND
    assert res.referent == "99.99"
    assert res.message


@pytest.mark.asyncio
async def test_a_word_shaped_token_that_DOES_exist_still_resolves():
    """A building may name a space "Atrium". The graph is what decides, not the shape."""
    res = await _resolver(exists=True).resolve(
        "What is the temperature in room Atrium?", [], "http://x#", "B"
    )
    assert res.status == rr.RESOLVED
    assert res.referent == "Atrium"
