# -*- coding: utf-8 -*-
"""A cached answer must carry the evidence record that describes it (BUG-235).

Reproducible against the live stack: ask a question twice, and the FIRST response carries an
evidence record while the SECOND does not. On a cache hit the pipeline is skipped, `plan_trace`
is reconstructed by hand, and `evidence_record` was simply left out -- so every repeated
question returned prose with no statement of what supports it. With a one-hour TTL that is a
large share of real traffic, and it silently voided the guarantee V6-T02 exists to make.

It also explains why T02's acceptance probe passed: the probe asks each question once.

The downstream effect was not cosmetic. BUG-230 scopes the plausibility guard by the record's
operation and fails OPEN when there is none, so on cached turns that guard kept running over
whatever numbers the answer happened to contain -- exactly the behaviour the fix removed.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ORCH = Path(__file__).resolve().parent.parent / "orchestrator"
SRC = (ORCH / "workflow" / "_orchestrator.py").read_text(encoding="utf-8")


def test_the_record_is_stored_with_the_cached_answer():
    put = SRC[SRC.index("await self.response_cache.put(") :][:900]
    assert '"evidence_record": results.get("evidence_record")' in put


def test_the_record_is_restored_on_a_cache_hit():
    hit = SRC[SRC.index('state.intermediate_results["cache_hit"] = True') :][:1400]
    assert 'state.intermediate_results["evidence_record"]' in hit
    assert '(cached.get("metadata") or {}).get("evidence_record")' in hit


def test_a_restored_record_is_marked_as_served_from_cache():
    """A reader must be able to tell that the evidence behind this answer was gathered for an
    earlier turn."""
    hit = SRC[SRC.index('state.intermediate_results["cache_hit"] = True') :][:1400]
    assert '"served_from_cache": True' in hit


def test_the_restored_record_keeps_its_original_retrieved_at():
    """`retrieved_at` says when the EVIDENCE was gathered, and for a cached answer it genuinely
    was gathered then. Refreshing it to now would manufacture currency the answer does not
    have -- the exact failure the freshness gate exists to catch. So the restore must not
    touch it.
    """
    hit = SRC[SRC.index('state.intermediate_results["cache_hit"] = True') :][:1400]
    assert not re.search(
        r'"retrieved_at"\s*:', hit
    ), "the cache-hit branch must not rewrite retrieved_at"


def test_the_cache_entry_has_somewhere_to_put_it():
    """`metadata` already existed on the cache entry; the record rides in it rather than in a
    new field, so old entries deserialise unchanged."""
    cache = (ORCH / "services" / "response_cache.py").read_text(encoding="utf-8")
    assert '"metadata": metadata or {}' in cache
    assert "metadata: Optional[Dict] = None" in cache


def test_plan_trace_was_already_restored_and_the_record_now_matches_it():
    """plan_trace is rebuilt on a cache hit precisely so a cached turn still explains itself.
    The evidence record needed the same treatment and did not have it."""
    hit = SRC[SRC.index('state.intermediate_results["cache_hit"] = True') :][:1400]
    assert '"kind": "reflex"' in hit
