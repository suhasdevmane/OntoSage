"""Response-cache wrong-entity safety (CAVEAT-035).

Two bugs, both of which served one entity's cached answer for a DIFFERENT entity:
  1. normalise_query dropped single-char tokens, so "floor 3" and "floor 5" collapsed to the
     SAME normalised key -> identical exact-cache hash -> wrong floor's answer.
  2. the fuzzy matcher scored trigram similarity only, so a long question differing solely in a
     room/zone id (>0.85 similarity) could return the other entity's answer.
"""

from __future__ import annotations

import json

import pytest

from orchestrator.services.response_cache import (
    ResponseCacheService,
    normalise_query,
    query_hash,
    salient_ids,
)

pytestmark = pytest.mark.unit


def test_normalise_keeps_single_digit_entity_ids():
    # The core fix: a bare floor/zone number must survive normalisation so distinct
    # entities get distinct cache keys.
    assert normalise_query("noise on floor 3") != normalise_query("noise on floor 5")
    assert query_hash("noise on floor 3") != query_hash("noise on floor 5")
    # single-char *letters* are still dropped (noise word 'a' etc.), digits kept.
    assert "3" in normalise_query("what is the co2 on floor 3")


def test_salient_ids_extraction():
    assert salient_ids(normalise_query("temperature in room 5.04")) == {"5.04"}
    assert salient_ids("3 floor noise") == {"3"}
    assert salient_ids("how do i make a complaint") == set()


def _svc():
    return ResponseCacheService(redis_client=None, fuzzy=True, min_similarity=0.85)


_BASE = "alpha bravo charlie delta echo foxtrot golf hotel india"


async def test_fuzzy_guard_rejects_mismatched_id(monkeypatch):
    # Stored answer is for entity id "5"; a >0.85-similar question about id "4" must NOT hit.
    svc = _svc()

    async def fake_hgetall(_key):
        return {"hashA": f"5 {_BASE}"}

    async def fake_get(_key):
        return json.dumps({"response": "answer for 5", "intent": "sensor_data"})

    monkeypatch.setattr(svc, "_redis_hgetall", fake_hgetall)
    monkeypatch.setattr(svc, "_redis_get", fake_get)

    miss = await svc._fuzzy_lookup(f"{_BASE} 4", "bldg1")  # normalises to "4 " + base
    assert miss is None


async def test_fuzzy_guard_allows_same_id(monkeypatch):
    svc = _svc()

    async def fake_hgetall(_key):
        return {"hashA": f"5 {_BASE}"}

    async def fake_get(_key):
        return json.dumps({"response": "answer for 5", "intent": "sensor_data"})

    monkeypatch.setattr(svc, "_redis_hgetall", fake_hgetall)
    monkeypatch.setattr(svc, "_redis_get", fake_get)

    hit = await svc._fuzzy_lookup(f"{_BASE} 5", "bldg1")  # same id 5, ~identical
    assert hit is not None and hit["response"] == "answer for 5"
