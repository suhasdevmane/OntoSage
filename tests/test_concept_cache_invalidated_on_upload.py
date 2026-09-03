# -*- coding: utf-8 -*-
"""An ontology change must take effect without anyone knowing a Redis key (BUG-398).

`ConceptResolver` caches the whole HBCO lay-term map in REDIS, so a container restart does
not refresh it. `invalidate_cache()` exists, its docstring says "call after HBCO TTL is
re-uploaded" — and nothing called it.

Measured while fixing BUG-395: new lay terms were added to `ontology/hbco_mappings.ttl`,
uploaded, and confirmed present in GraphDB by direct query. The question still routed to the
wrong lane through TWO container restarts. Only a manual `DEL cache:concept:hbco_all` made
the ontology change take effect.

That is worse than a stale cache. The project's central promise is "extend the TTL and the
system answers" — design contract 2, and the reason a building is onboarded without code
changes. A vocabulary addition that lands in the graph, verifies in the graph, and changes
nothing until someone clears an undocumented Redis key makes that promise false in a way
that looks like the ontology being wrong.

The thirteenth instance in this project of a capability built, correct, tested, and never
invoked.
"""

import inspect

import pytest

pytestmark = pytest.mark.unit


def test_the_uploader_invalidates_the_concept_cache():
    from orchestrator.services import ttl_uploader

    src = inspect.getsource(ttl_uploader)
    assert "concept_resolver.invalidate_cache()" in src, (
        "nothing drops the cached HBCO map after an upload, so a new lay term reaches "
        "GraphDB and the resolver keeps reading the old one"
    )


def test_it_is_only_dropped_when_something_was_actually_uploaded():
    """A boot that uploads nothing should not pay for a cache round-trip."""
    from orchestrator.services import ttl_uploader

    src = inspect.getsource(ttl_uploader)
    # Anchor on the CALL, not the first mention — the explanatory comment above it
    # contains the word too, and a first draft of this test matched that instead.
    idx = src.find("concept_resolver.invalidate_cache()")
    assert idx > 0, "no call site found"
    window = src[max(0, idx - 1600) : idx]
    assert 'if summary["uploaded"]' in window, "the invalidation is not gated on an upload"


def test_a_cache_failure_cannot_stop_a_boot():
    """Dropping a cache is housekeeping; failing it must not take the orchestrator down."""
    from orchestrator.services import ttl_uploader

    src = inspect.getsource(ttl_uploader)
    idx = src.find("concept_resolver.invalidate_cache()")
    assert idx > 0, "no call site found"
    window = src[idx : idx + 400]
    assert "except Exception" in window


def test_the_resolver_still_exposes_the_method_the_uploader_calls():
    """Pins the contract between the two so a rename cannot silently unwire it again."""
    from orchestrator.services.concept_resolver import concept_resolver

    assert hasattr(concept_resolver, "invalidate_cache")
    assert inspect.iscoroutinefunction(concept_resolver.invalidate_cache)
