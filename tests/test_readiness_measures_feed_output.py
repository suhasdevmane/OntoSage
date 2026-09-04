# -*- coding: utf-8 -*-
"""A configured feed is not data until it has produced some (CAVEAT-412).

`source_system_readiness.py` decided `if count or rows or feeds: DATA`, so an ENABLED FEED
alone was enough — a switch treated as a proxy for the data it is supposed to produce.

Measured on bldg1, 2026-09-03: `timetable` reported **DATA** on 0 triples, 0 Postgres rows,
and 0 rows in the events store that `feeds.yaml`'s own comment says it writes to. Its 55 KB
CSV has never been ingested. `weather_external` was the same. The report read 26 DATA / 1
ABSENT; the truth is 24 DATA / 2 WIRED / 1 ABSENT.

That is a false positive in the direction that looks like success, and it is not cosmetic:
V7 uses readiness to decide which questions it believes it can answer, so it inflated the
coverage ceiling and would route a timetable question to a lane holding nothing.

The feeds clause was added for a good reason — an earlier version reported ABSENT for
systems whose data genuinely arrives by feed. So the fix is not to remove it but to measure
the feed's OUTPUT, and to keep DATA when the output cannot be measured at all: an unmeasured
feed must not be demoted, or the original under-reporting returns.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ready = _load("_ready", "scripts/source_system_readiness.py")
score = _load("_score", "scripts/build_v7_scorecard.py")


def _decide(count, rows, docs, feeds, produced):
    """The readiness rule, applied exactly as main() applies it."""
    feed_has_data = bool(feeds) and (produced is None or produced > 0)
    if count or rows or feed_has_data:
        return "DATA"
    if docs:
        return "PROSE"
    if feeds:
        return "WIRED"
    return "ABSENT"


# ── the reported failure ───────────────────────────────────────────────────────────────


def test_an_enabled_feed_that_produced_nothing_is_not_data():
    assert _decide(0, 0, [], ["timetable"], produced=0) == "WIRED"


def test_a_feed_that_produced_something_is_data():
    assert _decide(0, 0, [], ["timetable"], produced=42) == "DATA"


def test_an_unmeasurable_feed_keeps_data_rather_than_being_demoted():
    """None means UNKNOWN. Demoting on unknown re-introduces the under-reporting the feeds
    clause was added to fix, and turns a connection hiccup into a planning decision."""
    assert _decide(0, 0, [], ["weather"], produced=None) == "DATA"


def test_triples_still_win_regardless_of_feeds():
    assert _decide(5, 0, [], [], produced=None) == "DATA"
    assert _decide(0, 226, [], [], produced=None) == "DATA"


def test_a_document_still_gives_prose_when_the_feed_is_empty():
    assert _decide(0, 0, ["room_bookings"], ["booking"], produced=0) == "PROSE"


def test_nothing_at_all_is_still_absent():
    assert _decide(0, 0, [], [], produced=None) == "ABSENT"


# ── the probes are declared, and fail safe ─────────────────────────────────────────────


def test_the_feed_backed_systems_declare_where_their_output_lands():
    for system in ("timetable", "weather_external"):
        assert system in ready.FEED_OUTPUT_PROBES, (
            f"{system} is fed by a feed with no output probe, so 'switched on' would again "
            f"stand in for 'has data'"
        )
        kind, query = ready.FEED_OUTPUT_PROBES[system]
        assert kind in ("sparql", "mysql")
        assert query.strip()


def test_a_system_with_no_probe_is_not_silently_demoted():
    """feed_output returns None for an unprobed system, and None keeps DATA."""
    assert ready.feed_output("no_such_system", "http://x", None) is None


def test_an_unreachable_store_reports_unknown_not_zero(monkeypatch):
    """Zero would say 'this feed produced nothing', which is a claim about the data."""
    monkeypatch.setattr(ready, "sparql_count", lambda *a, **k: (_ for _ in ()).throw(RuntimeError))
    assert ready.feed_output("weather_external", "http://nope", None) is None


# ── the scorecard understands the new state ────────────────────────────────────────────


def test_the_scorecard_ranks_wired_below_prose():
    """A document you can quote answers more questions than a feed producing nothing."""
    import inspect

    src = inspect.getsource(score.readiness_ceiling)
    assert '"WIRED"' in src
    rank = {"DATA": 0, "PROSE": 1, "WIRED": 2, "ABSENT": 3}
    assert rank["PROSE"] < rank["WIRED"] < rank["ABSENT"]


def test_the_scorecard_reports_the_wired_bucket():
    import inspect

    src = inspect.getsource(score.main)
    assert '"WIRED"' in src, "a WIRED ceiling would be dropped from the table entirely"


def test_an_unknown_state_takes_the_worst_rank_not_a_middling_one():
    """A state added upstream must degrade the ceiling, never flatter it."""
    import inspect

    src = inspect.getsource(score.readiness_ceiling)
    assert "max(rank.values())" in src, (
        "the default rank is hardcoded, so a new upstream state would rank better than "
        "ABSENT and quietly raise the reported ceiling"
    )
