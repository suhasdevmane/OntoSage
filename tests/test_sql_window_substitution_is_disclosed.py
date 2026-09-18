# -*- coding: utf-8 -*-
"""A period the answer did not use must never be the period the question named (BUG-658).

When the SQL lane finds nothing in the window a question implies, it can drop every date
bound and answer from the most recent rows on record. Two things were wrong with that:

* the guard deciding whether it was allowed to was a PAST-TENSE keyword list — "today",
  "yesterday", "last week" — with no present tense in it at all, so "…right now" was
  classified as a question that named no period and the substitution was permitted; and
* nothing recorded that a substitution had happened. Two log lines, no marker, so no
  downstream gate, disclosure or evidence record could know, and the answer said nothing.

The fix has two halves and the SECOND one is the protection. Widening a list only moves
where it decays. What these tests pin hardest is that a substitution the guard FAILS to
catch is still disclosed — so a word missing from the list in a year's time costs a visible
sentence about the real period, not a silent claim about the wrong one.

Deliberately included: the two negative cases. A question whose window holds data must be
untouched (no marker, no sentence), and a question naming a past period must keep behaving
exactly as it did — returning nothing rather than substituting.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import pytest

from orchestrator.agents.sql_agent import (
    DEFAULT_LOOKBACK_DAYS,
    SQLAgent,
    names_a_period,
)
from orchestrator.services.disclosure_gate import (
    substitution_note,
    window_substitution_in,
)

pytestmark = pytest.mark.unit

# Not a building literal: an opaque identifier standing in for whatever the graph returns.
POINT = "00000000-0000-4000-8000-000000000001"
OTHER_POINT = "00000000-0000-4000-8000-000000000002"
STORE = "database1"

# A span deliberately far behind "now" — the shape of the defect, not a date this repo owns.
OLD_ROWS = [
    {"timestamp": "2025-01-01 00:00:00", "uuid": POINT, "value": 412.0},
    {"timestamp": "2025-03-09 23:55:00", "uuid": POINT, "value": 508.0},
]
FRESH_ROWS = [{"timestamp": "2026-09-17 09:00:00", "uuid": POINT, "value": 455.0}]


class _QueryResult:
    def __init__(self, data: List[Dict[str, Any]]):
        self.success = True
        self.data = list(data)
        self.error = None
        self.row_count = len(data)


class _AdapterType:
    value = "stub"


class _Adapter:
    """A store that holds `in_window` for the requested window and older rows at any date.

    REWRITTEN 2026-09-17 (BUG-660). This fake used to return None from
    `build_timeseries_query` and the tests replaced the agent's `_execute_query` to serve the
    fallback rows — which modelled the defect itself: the fallback bypassing the group's own
    adapter and hand-writing `FROM sensor_data` against the default one. A correct fallback
    now asks THIS adapter to build and run the query, so the fake has to answer both calls.

    The fallback is recognised by the one argument only it passes — the far-past start bound
    `_FALLBACK_FLOOR`, which lifts the adapter's own 30-day lookback — not by call order, so a
    test asserting "no fallback ran" is observing something real rather than an empty list
    nothing could ever append to.
    """

    adapter_type = _AdapterType()

    def __init__(
        self,
        in_window: List[Dict[str, Any]],
        fallback_batches: Optional[List[List[Dict[str, Any]]]] = None,
    ):
        self._in_window = in_window
        self._fallback_batches = list(fallback_batches or [])
        self.queries: List[str] = []
        self.fallback_queries: List[str] = []

    def build_timeseries_query(self, **kwargs) -> Optional[str]:
        from orchestrator.agents.sql_agent import _FALLBACK_FLOOR

        uuids = ",".join(kwargs.get("uuids") or [])
        if kwargs.get("start_date") == _FALLBACK_FLOOR:
            return f"FALLBACK latest rows for {uuids}"
        return f"WINDOW rows for {uuids}"

    def get_dialect_hints(self) -> str:
        return ""

    async def execute_query(self, sql: str) -> _QueryResult:
        self.queries.append(sql)
        if sql.startswith("FALLBACK"):
            self.fallback_queries.append(sql)
            if not self._fallback_batches:
                return _QueryResult([])
            # One batch per fallback call, the last one repeating — so two stores can each
            # return their own slice of history.
            index = min(len(self.fallback_queries), len(self._fallback_batches)) - 1
            return _QueryResult(self._fallback_batches[index])
        return _QueryResult(self._in_window)


class _Registry:
    is_available = True

    def __init__(self, adapter: _Adapter):
        self._adapter = adapter

    async def get_valid_uuids(self, uuids, primary=None, storage_map=None):
        return list(uuids)

    def _resolve_storage_key(self, storage: str) -> str:
        return str(storage).split(":")[-1].split("#")[-1]

    def get(self, key=None):
        return self._adapter

    def get_schema_text(self, key, keep_columns=None) -> str:
        return ""

    def get_timestamp_column(self, key) -> str:
        return "Datetime"


def _agent(monkeypatch, in_window, fallback_rows=None):
    """An agent whose store holds `in_window` now and `fallback_rows` at any date."""
    import orchestrator.agents.sql_agent as mod

    adapter = _Adapter(in_window, [list(fallback_rows or [])])
    monkeypatch.setattr(mod, "adapter_registry", _Registry(adapter), raising=True)

    agent = SQLAgent()

    async def _format(rows, query, label, metadata=None):
        return f"{len(rows)} reading(s)."

    async def _default_adapter_must_not_serve_the_fallback(sql: str):
        raise AssertionError(
            "the fallback reached the DEFAULT adapter via _execute_query; it must go through "
            f"the group's own adapter (BUG-660). SQL: {sql[:120]}"
        )

    monkeypatch.setattr(agent, "_format_results", _format, raising=True)
    monkeypatch.setattr(
        agent, "_execute_query", _default_adapter_must_not_serve_the_fallback, raising=True
    )
    agent._test_fallback_sql = adapter.fallback_queries  # type: ignore[attr-defined]
    agent._test_adapter = adapter  # type: ignore[attr-defined]
    return agent


async def _ask(agent, question, start=None, end=None, uuids=None):
    return await agent.fetch_data_for_uuids(
        uuids or [POINT],
        question,
        {u: f"bldg:{STORE}" for u in (uuids or [POINT])},
        start,
        end,
    )


# ── the guard: present tense is a period, and it was not ────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "What is the CO2 in that room right now?",
        "What is the temperature currently?",
        "Give me the latest humidity reading",
        "Show me the live occupancy",
        "How warm is it at the moment?",
        "What is the CO2 now?",
        "What is the air quality at present?",
    ],
)
def test_present_tense_names_a_period(question):
    """Every one of these returned False before the fix — which is what let it through."""
    assert names_a_period(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "What was the CO2 yesterday?",
        "Average temperature last week",
        "Readings between the 1st and the 8th",
        "Humidity over the past month",
        "What happened in the last hour?",
    ],
)
def test_past_tense_still_names_a_period(question):
    """The behaviour that already worked must not change."""
    assert names_a_period(question) is True


def test_a_question_naming_no_period_still_names_none():
    """The guard must stay narrow — widening it into 'everything is a period' would disable
    the fallback entirely and turn every gap into a refusal."""
    assert names_a_period("What is the CO2 in that room?") is False


# ── the substitution itself ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_present_tense_question_is_not_silently_substituted(monkeypatch):
    """'right now' with an empty window: no substitution, and no figures from another period.

    Before the fix the fallback ran, returned rows from an arbitrary earlier date, and the
    answer presented them as the current reading.
    """
    agent = _agent(monkeypatch, in_window=[], fallback_rows=OLD_ROWS)

    result = await _ask(agent, "What is the CO2 in that space right now?")

    assert agent._test_fallback_sql == [], "the unbounded fallback must not have run"
    assert result["results"]["data"] == []
    assert result["window_substituted"] is None


@pytest.mark.asyncio
async def test_a_substitution_the_guard_misses_is_still_disclosed(monkeypatch):
    """THE LOAD-BEARING TEST. The guard is a list and every list decays.

    This question names no period at all, so the guard correctly permits the substitution —
    which is exactly the state a future missing keyword will produce. The answer must still
    say which period the figures came from.
    """
    agent = _agent(monkeypatch, in_window=[], fallback_rows=OLD_ROWS)

    result = await _ask(agent, "What is the CO2 in that space?")

    assert agent._test_fallback_sql, "the fallback was expected to run for this question"

    marker = result["window_substituted"]
    assert marker is not None
    assert marker["substituted"] is True
    # The span is the honest part: earliest and latest actually returned.
    assert marker["actual_earliest"] == "2025-01-01 00:00:00"
    assert marker["actual_latest"] == "2025-03-09 23:55:00"
    assert marker["rows"] == len(OLD_ROWS)
    # The requested window is named, and named as the query actually bounded it.
    assert marker["requested_label"] == f"the last {DEFAULT_LOOKBACK_DAYS} days"

    # And the user is told, in the answer.
    text = result["formatted_response"]
    assert "2025-03-09 23:55:00" in text
    assert f"the last {DEFAULT_LOOKBACK_DAYS} days" in text
    assert "not as current" in text


@pytest.mark.asyncio
async def test_the_marker_reaches_the_disclosure_gate_from_the_bus(monkeypatch):
    """A downstream gate must be able to find the substitution without parsing prose."""
    agent = _agent(monkeypatch, in_window=[], fallback_rows=OLD_ROWS)
    result = await _ask(agent, "What is the CO2 in that space?")

    bus = {"sql_result": result}
    marker = window_substitution_in(bus)
    assert marker is not None
    assert marker["actual_latest"] == "2025-03-09 23:55:00"


@pytest.mark.asyncio
async def test_an_explicit_past_window_is_unchanged(monkeypatch):
    """Naming a past period must keep working exactly as it did: no substitution.

    Two independent reasons block it here — the window is explicit, so the default-range
    test fails — and the question names a period. Both are asserted through the observable
    outcome rather than either internal flag.
    """
    agent = _agent(monkeypatch, in_window=[], fallback_rows=OLD_ROWS)

    result = await _ask(
        agent,
        "What was the CO2 in that space yesterday?",
        start="2026-09-16 00:00:00",
        end="2026-09-16 23:59:59",
    )

    assert agent._test_fallback_sql == []
    assert result["window_substituted"] is None
    assert "not as current" not in result["formatted_response"]


@pytest.mark.asyncio
async def test_a_question_with_data_in_its_window_is_untouched(monkeypatch):
    """The commonest case: nothing was substituted, so nothing is said."""
    agent = _agent(monkeypatch, in_window=FRESH_ROWS, fallback_rows=OLD_ROWS)

    result = await _ask(agent, "What is the CO2 in that space right now?")

    assert agent._test_fallback_sql == []
    assert result["window_substituted"] is None
    assert result["results"]["data"] == FRESH_ROWS
    assert substitution_note(result["window_substituted"]) == ""
    assert "not as current" not in result["formatted_response"]


@pytest.mark.asyncio
async def test_a_substitution_across_two_stores_reports_the_whole_span(monkeypatch):
    """Two groups substituting must widen one span, not report two disconnected ones."""
    import orchestrator.agents.sql_agent as mod

    adapter = _Adapter([], [[OLD_ROWS[0]], [OLD_ROWS[1]]])

    class _TwoStoreRegistry(_Registry):
        def _resolve_storage_key(self, storage: str) -> str:
            return str(storage).split(":")[-1]

    monkeypatch.setattr(mod, "adapter_registry", _TwoStoreRegistry(adapter), raising=True)
    agent = SQLAgent()

    async def _format(rows, query, label, metadata=None):
        return f"{len(rows)} reading(s)."

    monkeypatch.setattr(agent, "_format_results", _format, raising=True)
    calls = adapter.fallback_queries

    result = await agent.fetch_data_for_uuids(
        [POINT, OTHER_POINT],
        "What is the CO2 in that space?",
        {POINT: "bldg:storeA", OTHER_POINT: "bldg:storeB"},
        None,
        None,
    )

    marker = result["window_substituted"]
    assert marker is not None
    assert len(calls) == 2
    assert marker["actual_earliest"] == "2025-01-01 00:00:00"
    assert marker["actual_latest"] == "2025-03-09 23:55:00"
    assert marker["rows"] == 2
    assert sorted(marker["stores"]) == ["storeA", "storeB"]


# ── the disclosure wording, in isolation ────────────────────────────────────────────────


def test_note_is_empty_when_nothing_was_substituted():
    assert substitution_note(None) == ""
    assert substitution_note({}) == ""
    assert substitution_note({"substituted": False}) == ""


def test_note_states_the_requested_period_and_the_real_one():
    note = substitution_note(
        {
            "substituted": True,
            "requested_label": "2026-09-17 00:00:00 to 2026-09-17 23:59:59",
            "actual_earliest": "2025-01-01 00:00:00",
            "actual_latest": "2025-03-09 23:55:00",
            "rows": 480,
        }
    )
    assert "2026-09-17 00:00:00 to 2026-09-17 23:59:59" in note
    assert "2025-01-01 00:00:00" in note
    assert "2025-03-09 23:55:00" in note
    assert "480 reading(s)" in note


def test_note_says_so_even_when_the_span_cannot_be_read():
    """An unreadable span is MORE alarming, not less — it must never fall silent."""
    note = substitution_note({"substituted": True, "requested_label": "the last 30 days"})
    assert note.strip()
    assert "the last 30 days" in note
    assert "not as current" in note


def test_note_never_raises_on_a_malformed_marker():
    """A disclosure that threw would leave the substituted figures on screen alone."""

    class _Hostile(dict):
        def get(self, key, default=None):
            if key == "actual_latest":
                raise RuntimeError("unreadable")
            return super().get(key, default)

    marker = _Hostile(substituted=True)
    note = substitution_note(marker)
    assert "not from the period this question asked about" in note


def test_window_substitution_in_reads_only_structured_markers():
    """Prose is never the signal — that is how a grader came to count the '2' in a
    building id as a reading (BUG-191)."""
    assert window_substitution_in(None) is None
    assert window_substitution_in({"sql_result": "the data may be old"}) is None
    assert window_substitution_in({"sql_result": {"window_substituted": None}}) is None
    assert window_substitution_in({"sql_result": {"window_substituted": {}}}) is None
    found = window_substitution_in(
        {"analytics_result": {"window_substituted": {"substituted": True, "rows": 1}}}
    )
    assert found == {"substituted": True, "rows": 1}


def test_row_span_reads_datetimes_and_strings_alike():
    earliest, latest = SQLAgent._row_span(
        [
            {"timestamp": datetime(2025, 3, 9, 23, 55)},
            {"Datetime": "2025-01-01T00:00:00"},
            {"value": 1.0},
        ]
    )
    assert earliest == "2025-01-01 00:00:00"
    assert latest == "2025-03-09 23:55:00"


def test_row_span_is_empty_when_no_row_carries_a_timestamp():
    assert SQLAgent._row_span([{"value": 1.0}, "not a row"]) == ("", "")
    assert SQLAgent._row_span([]) == ("", "")


def test_requested_label_reports_only_bounds_the_query_honoured():
    agent = SQLAgent()
    # An unresolved relative phrase is DISCARDED by the query builder; naming it here
    # would tell the user a bound was applied that never was.
    assert agent._requested_window_label("now-1d", None) == (
        f"the last {DEFAULT_LOOKBACK_DAYS} days"
    )
    assert agent._requested_window_label("2026-09-16", "2026-09-17") == ("2026-09-16 to 2026-09-17")
    assert agent._requested_window_label("2026-09-16", None) == (
        "the period from 2026-09-16 onwards"
    )
    assert agent._requested_window_label(None, "2026-09-17") == ("the period up to 2026-09-17")
