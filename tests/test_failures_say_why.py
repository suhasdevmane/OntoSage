# -*- coding: utf-8 -*-
"""A logged failure must name its cause (CAVEAT-415).

Several exception classes carry no message: `httpx.ReadTimeout`, `httpx.ConnectTimeout`,
`asyncio.TimeoutError`, a bare `Exception()`. Logged as `f"...: {exc}"` they produce a line
that ends in a colon and says nothing at all.

Measured on bldg1 across six hours of a corpus capture: **62 warnings with an empty
message**, of which **52 were the capability lane abandoning the ontology and falling back
to the document KB** on a 15-second SPARQL timeout — roughly 11% of the 488 capability
questions in that run leaving the TTL-first path (contract 2) with no record of why. Two
anomaly sweeps and two ontology censuses failed the same way.

The fallback itself is correct behaviour: GraphDB was slow under concurrent load and the
lane degraded rather than failing. What was wrong is that it happened *invisibly* — the one
line written about it was empty, so a silent quality degradation looked like a healthy run.
"""

import asyncio
import inspect

import pytest

from shared.utils import describe_exception

pytestmark = pytest.mark.unit


class _Silent(Exception):
    """Stands in for httpx.ReadTimeout, whose str() is empty."""


@pytest.mark.parametrize(
    "exc",
    [_Silent(), Exception(), asyncio.TimeoutError(), TimeoutError(), ValueError("")],
)
def test_a_messageless_exception_still_names_its_class(exc):
    text = describe_exception(exc)
    assert text.strip()
    assert type(exc).__name__ in text
    assert not text.rstrip().endswith(":"), "a line ending in a colon is the defect itself"


def test_a_message_is_kept_and_the_class_added():
    text = describe_exception(ValueError("bad namespace"))
    assert "ValueError" in text and "bad namespace" in text


def test_whitespace_only_counts_as_no_message():
    assert "no message" in describe_exception(RuntimeError("   "))


def test_it_never_raises_on_an_awkward_exception():
    class _Awkward(Exception):
        def __str__(self):  # noqa: D105
            raise RuntimeError("cannot render")

    try:
        out = describe_exception(_Awkward())
    except Exception:  # pragma: no cover - the point is that this does not happen
        pytest.fail("describe_exception raised while describing an exception")
    assert "_Awkward" in out


# ── the sites that were measured failing silently ──────────────────────────────────────


@pytest.mark.parametrize(
    "module_path, symbol",
    [
        ("orchestrator.services.capability_graph_resolver", "CapabilityGraphResolver.resolve"),
        ("orchestrator.services.ontology_inventory", None),
        ("orchestrator.agents.dialogue_agent", None),
    ],
)
def test_the_measured_sites_describe_their_exception(module_path, symbol):
    import importlib

    mod = importlib.import_module(module_path)
    src = inspect.getsource(mod)
    assert "describe_exception" in src, (
        f"{module_path} logs a failure without naming its cause; this is where 62 empty "
        f"warnings came from"
    )


def test_the_anomaly_sweep_logs_a_traceback():
    """A background loop that swallows an exception is the hardest kind to diagnose."""
    from orchestrator import main

    src = inspect.getsource(main)
    idx = src.find("[anomaly-scan] sweep failed")
    assert idx > 0
    window = src[idx : idx + 400]
    assert "describe_exception" in window
    assert "exc_info=True" in window, "a retrying background sweep needs the traceback"


def test_no_measured_site_still_logs_a_bare_exception():
    """Pinned narrowly: these four handlers, not every log line in the codebase."""
    import importlib

    bare = []
    for path, needle in (
        ("orchestrator.services.capability_graph_resolver", "amenity fetch failed"),
        ("orchestrator.services.ontology_inventory", "class census failed"),
        ("orchestrator.agents.dialogue_agent", "GraphDB retrieval failed"),
        ("orchestrator.main", "sweep failed (will retry)"),
    ):
        src = inspect.getsource(importlib.import_module(path))
        idx = src.find(needle)
        if idx < 0:
            continue
        window = src[idx : idx + 300]
        if "describe_exception" not in window:
            bare.append(f"{path}:{needle}")
    assert not bare, f"these still log an exception that may render as empty: {bare}"
