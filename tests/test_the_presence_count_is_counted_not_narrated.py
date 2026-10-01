# -*- coding: utf-8 -*-
""""Which rooms are occupied at the moment?" is COUNTED in code, over a stated denominator.

BUG-954 (P1). The question holds no statistic word, so `parse_intent` returned None, `wants_lane`
declined, and the turn left the count to the narration. Measured live on 2026-09-30, twice per
phrasing with `resp_cache` flushed between, the orchestrator logged for all four turns:

    [aggregate] not claimed: measurand=occupancy place=False per_sensor=False readings=True

and the answers that came back named five rooms under a headline of five while quoting their own
statistics: "131 of 234 sensors" read zero in one turn and "137 of 467 sensors" in the other. Both
denominators were real and correctly fetched; what nothing computed was the count.

The tests below pin the properties that make a count trustworthy, and each one is a defect that
was live:

* the count is derived from ONE list, and the names printed are that list's members, so a headline
  and the names under it cannot disagree (the defect itself);
* the denominator is PLACES and the answer states it -- a series is not a room, some rooms carry
  two occupancy series and some carry none (lesson #139, BUG-883);
* a FLOOR counter is not a room's and is neither counted as a place nor dropped in silence;
* where a space's people counter and its presence flag disagree, the answer says so rather than
  picking one silently -- on bldg1 that is 136 of 233 spaces, so a number that hid it would be
  reporting one instrument as though the other did not exist;
* a question that names another quantity ("...during an approved occupied period") is left to the
  branch that answers it.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytest

from orchestrator.services import aggregate_lane as al
from orchestrator.services.aggregate_support import presence_question
from orchestrator.services.database_adapter import AdapterType, QueryResult

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 30, 6, 40, 0)  # store (UTC) time
TZ = "Europe/London"
STORE = "http://example.org/bldg#occupancy_data"


class FakeNarrow:
    """A narrow occupancy store that answers a `latest` statement from a value table."""

    adapter_type = AdapterType.MYSQL
    table = "occupancy_data"

    def __init__(self, values: Dict[str, float]):
        self.values = values
        self.sql: List[str] = []

    async def execute_query(self, sql: str) -> QueryResult:
        self.sql.append(sql)
        rows = [
            {"uuid": u, "value": self.values[u], "ts": NOW}
            for u in dict.fromkeys(re.findall(r"'([a-z0-9-]{8,})'", sql))
            if u in self.values
        ]
        return QueryResult(success=True, data=rows, row_count=len(rows), query=sql)


def _binding(uuid: str, place: str, on_floor: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {"uuid": {"value": uuid}}
    if place:
        out["locLabel"] = {"value": place}
        out["onFloor"] = {"value": "true" if on_floor else "false"}
    return out


async def _answer(
    question: str,
    series: List[Dict[str, Any]],
    *,
    aggregate_only: bool = False,
) -> Optional[Dict[str, Any]]:
    """Run the lane over `series`, each {uuid, label, place, value, on_floor}."""
    values = {s["uuid"]: s["value"] for s in series}
    adapter = FakeNarrow(values)
    metadata = {
        s["uuid"]: {"label": s["label"], "unit": "", "kind": "Occupancy_Sensor"} for s in series
    }
    bindings = [_binding(s["uuid"], s.get("place", ""), s.get("on_floor", False)) for s in series]

    async def sparql_exec(_q: str) -> Dict[str, Any]:
        return {"results": {"bindings": bindings}}

    return await al.try_answer(
        question=question,
        uuids=[s["uuid"] for s in series],
        storage_map={s["uuid"]: STORE for s in series},
        metadata=metadata,
        start_date=None,
        end_date=None,
        budget_hit=False,
        tz_name=TZ,
        adapter_for=lambda _uri: adapter,
        store_key=lambda _uri: "occupancy_data",
        sparql_exec=sparql_exec,
        now=NOW,
        aggregate_only=aggregate_only,
    )


def _room(n: int, value: float, *, status: bool = False) -> Dict[str, Any]:
    kind = "occupancy_status" if status else "occupancy"
    return {
        "uuid": f"series-{'s' if status else 'c'}-{n:04d}",
        "label": f"Room{n} {kind}",
        "place": f"Room {n}",
        "value": value,
    }


# ─────────────────────────────────────────────────────────────────────────────
# The shape, decided without a store
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Which rooms are occupied at the moment?", "occupied"),
        ("which rooms are occupied at the moment", "occupied"),
        ("Which rooms are empty at the moment?", "empty"),
        ("Which rooms are unoccupied?", "empty"),
        ("How many spaces are vacant right now?", "empty"),
        ("How many rooms are occupied right now?", "occupied"),
        ("Which zones are in use at the moment?", "occupied"),
        ("List the rooms that are empty", "empty"),
    ],
)
def test_a_presence_question_is_recognised_by_its_shape(question: str, expected: str) -> None:
    assert presence_question(question) == expected


@pytest.mark.parametrize(
    "question",
    [
        # ONE named room is a lookup, and a lookup has no denominator to state.
        "Is room 1.25 occupied?",
        "How many people are in Room 1.06 right now?",
        # No state word at all.
        "Which rooms have a CO2 sensor?",
        "Which floor has the most people?",
        # A state word with no set of spaces asked for.
        "The building is occupied between 8am and 6pm.",
    ],
)
def test_a_question_that_is_not_a_presence_count_is_not_claimed(question: str) -> None:
    assert presence_question(question) is None


def test_unoccupied_is_empty_not_occupied() -> None:
    """The two words share five letters and mean the opposite; the lookbehind is load-bearing."""
    assert presence_question("Which rooms are unoccupied at the moment?") == "empty"


@pytest.mark.parametrize(
    "question",
    [
        "Which rooms were occupied yesterday?",
        "Which rooms were empty last week?",
        "Which rooms are occupied over the weekend?",
        "Which spaces were vacant overnight?",
    ],
)
def test_a_question_about_a_past_period_is_not_answered_from_the_newest_reading(
    question: str,
) -> None:
    """A presence count is over each series' NEWEST value, so it answers about now and only now.

    Claiming "which rooms were occupied yesterday" and answering it from the latest reading is
    BUG-480's defect in a new place: real figures, captioned with the wrong day.
    """
    assert presence_question(question) is None


# ─────────────────────────────────────────────────────────────────────────────
# The count itself
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_headline_count_matches_the_places_it_names() -> None:
    """THE DEFECT. Five rooms were named under a headline of five, beside statistics saying 103.

    The count and the names come from one list here, so the test can check them against each
    other: every place named is in the list the headline counts, and the "and N more" closes the
    gap exactly.
    """
    series = [_room(n, 1.0 if n < 7 else 0.0, status=True) for n in range(1, 21)]
    out = await _answer("Which rooms are occupied at the moment?", series)
    assert out is not None
    text = out["formatted_response"]
    assert "**6 of the 20 spaces" in text
    named = re.search(r"Occupied: (.+?)\.\n", text + "\n")
    assert named is not None
    listed = named.group(1)
    for n in range(1, 7):
        assert f"Room {n}" in listed
    assert "Room 7" not in listed
    assert "more" not in listed  # six fit under the limit, so nothing is elided


@pytest.mark.asyncio
async def test_the_named_places_and_the_remainder_add_up_to_the_headline() -> None:
    """A truncated list still accounts for every place the headline counts."""
    series = [_room(n, 1.0 if n <= 30 else 0.0, status=True) for n in range(1, 51)]
    out = await _answer("Which rooms are occupied at the moment?", series)
    assert out is not None
    text = out["formatted_response"]
    assert "**30 of the 50 spaces" in text
    shown = len(re.findall(r"Room \d+", text.split("Occupied:")[1].split(".\n")[0]))
    more = int(re.search(r"and (\d+) more", text).group(1))
    assert shown + more == 30


@pytest.mark.asyncio
async def test_the_denominator_is_places_and_is_stated() -> None:
    """A room with two occupancy series is ONE room. Counting series would say four, not two."""
    series = [
        _room(1, 1.0, status=True),
        _room(1, 5.0),
        _room(2, 0.0, status=True),
        _room(2, 0.0),
    ]
    out = await _answer("Which rooms are empty at the moment?", series)
    assert out is not None
    assert "**1 of the 2 spaces" in out["formatted_response"]


@pytest.mark.asyncio
async def test_a_floor_counter_is_not_counted_as_a_room_and_is_not_dropped() -> None:
    series = [_room(1, 1.0, status=True), _room(2, 0.0, status=True)]
    series.append(
        {
            "uuid": "series-floor-0001",
            "label": "Floor 1 occupancy",
            "place": "Floor 1",
            "value": 40.0,
            "on_floor": True,
        }
    )
    out = await _answer("Which rooms are occupied at the moment?", series)
    assert out is not None
    text = out["formatted_response"]
    assert "**1 of the 2 spaces" in text
    assert "1 occupancy series count a whole floor" in text
    assert "Floor 1" not in text.split("Occupied:")[1].split(".\n")[0]


@pytest.mark.asyncio
async def test_a_series_the_graph_does_not_place_is_disclosed_not_counted() -> None:
    series = [_room(1, 1.0, status=True), _room(2, 0.0, status=True)]
    series.append(
        {"uuid": "series-loose-001", "label": "Roving occupancy", "place": "", "value": 3.0}
    )
    out = await _answer("Which rooms are occupied at the moment?", series)
    assert out is not None
    text = out["formatted_response"]
    assert "**1 of the 2 spaces" in text
    assert "1 occupancy series returned a reading but are not placed in a space" in text


@pytest.mark.asyncio
async def test_two_instruments_in_one_space_that_disagree_are_reported_not_resolved() -> None:
    """On bldg1 this is 136 of 233 spaces, so an answer that hid it would hide the larger fact."""
    series = [
        _room(1, 0.0, status=True),
        _room(1, 14.0),  # the counter says fourteen people; the flag says nobody
        _room(2, 1.0, status=True),
        _room(2, 3.0),
    ]
    out = await _answer("Which rooms are empty at the moment?", series)
    assert out is not None
    text = out["formatted_response"]
    assert "**1 of the 2 spaces" in text
    assert "1 of these spaces carry a second occupancy series that disagrees" in text
    assert "14 people" in text


@pytest.mark.asyncio
async def test_a_space_with_only_a_counter_is_counted_by_its_counter() -> None:
    """No presence flag anywhere means the counter IS the presence evidence, and is named as it."""
    series = [_room(1, 6.0), _room(2, 0.0), _room(3, 2.0)]
    out = await _answer("Which rooms are occupied at the moment?", series)
    assert out is not None
    text = out["formatted_response"]
    assert "**2 of the 3 spaces" in text
    assert "people counter" in text


@pytest.mark.asyncio
async def test_the_denominator_does_not_claim_an_instrument_every_space_lacks() -> None:
    """Most spaces have a presence flag; one has only a counter. The answer counts both kinds.

    The lead sentence says "spaces with an occupancy sensor", which is true of all four, and the
    split is stated rather than the commonest instrument being attributed to every space.
    """
    series = [
        _room(1, 1.0, status=True),
        _room(2, 0.0, status=True),
        _room(3, 1.0, status=True),
        _room(4, 9.0),  # a counter and no flag
    ]
    out = await _answer("Which rooms are occupied at the moment?", series)
    assert out is not None
    text = out["formatted_response"]
    assert "**3 of the 4 spaces with an occupancy sensor" in text
    assert (
        "3 of these spaces are decided by an occupancy-presence sensor and 1 by a people counter"
        in text
    )


@pytest.mark.asyncio
async def test_a_reader_held_to_aggregates_gets_the_count_and_no_map() -> None:
    """`aggregate_only` means a list of which rooms hold people is a map of where they are."""
    series = [_room(n, 1.0 if n < 4 else 0.0, status=True) for n in range(1, 11)]
    out = await _answer("Which rooms are occupied at the moment?", series, aggregate_only=True)
    assert out is not None
    text = out["formatted_response"]
    assert "**3 of the 10 spaces" in text
    assert "Occupied:" not in text


@pytest.mark.asyncio
async def test_the_answer_is_marked_so_no_later_lane_rewrites_it() -> None:
    series = [_room(1, 1.0, status=True), _room(2, 0.0, status=True)]
    out = await _answer("Which rooms are occupied at the moment?", series)
    assert out is not None
    assert out["aggregate_lane"] is True
    assert out["analytics_required"] is False
    assert out["aggregate"]["stat"] == "presence"
    assert out["aggregate"]["group"] == "room"


@pytest.mark.asyncio
async def test_a_question_about_another_quantity_is_left_to_its_own_branch() -> None:
    """The frame and the word "occupied" are both present; the question is about CO2."""
    series = [_room(n, 1.0, status=True) for n in range(1, 6)]
    out = await _answer(
        "Which zones show sustained elevated CO2 during an approved occupied period?", series
    )
    assert out is None or out["aggregate"]["stat"] != "presence"


@pytest.mark.asyncio
async def test_no_readings_means_no_answer_rather_than_a_count_of_zero() -> None:
    """A store that returns nothing must not be narrated as "every room is empty"."""
    series = [_room(1, 1.0, status=True)]
    values: Dict[str, float] = {}
    adapter = FakeNarrow(values)

    async def sparql_exec(_q: str) -> Dict[str, Any]:
        return {"results": {"bindings": [_binding(series[0]["uuid"], "Room 1")]}}

    out = await al.try_answer(
        question="Which rooms are empty at the moment?",
        uuids=[series[0]["uuid"]],
        storage_map={series[0]["uuid"]: STORE},
        metadata={series[0]["uuid"]: {"label": series[0]["label"], "unit": ""}},
        start_date=None,
        end_date=None,
        budget_hit=False,
        tz_name=TZ,
        adapter_for=lambda _uri: adapter,
        store_key=lambda _uri: "occupancy_data",
        sparql_exec=sparql_exec,
        now=NOW,
    )
    assert out is None


@pytest.mark.asyncio
async def test_the_store_is_asked_for_the_newest_reading_not_for_rows() -> None:
    """The count is over each series' latest value; a row-level read is what this lane exists
    to avoid."""
    series = [_room(n, 1.0, status=True) for n in range(1, 4)]
    values = {s["uuid"]: s["value"] for s in series}
    adapter = FakeNarrow(values)

    async def sparql_exec(_q: str) -> Dict[str, Any]:
        return {"results": {"bindings": [_binding(s["uuid"], s["place"]) for s in series]}}

    await al.try_answer(
        question="Which rooms are occupied at the moment?",
        uuids=[s["uuid"] for s in series],
        storage_map={s["uuid"]: STORE for s in series},
        metadata={s["uuid"]: {"label": s["label"], "unit": ""} for s in series},
        start_date=None,
        end_date=None,
        budget_hit=False,
        tz_name=TZ,
        adapter_for=lambda _uri: adapter,
        store_key=lambda _uri: "occupancy_data",
        sparql_exec=sparql_exec,
        now=NOW,
    )
    assert adapter.sql, "the lane never reached the store"
    joined = " ".join(adapter.sql)
    assert "MAX(`datetime`)" in joined
    assert "SELECT *" not in joined


def test_the_module_names_no_building() -> None:
    """Building-agnostic (design contract #3): nothing here names bldg1's rooms or namespace."""
    from pathlib import Path

    source = Path(al.__file__).read_text(encoding="utf-8")
    body = source[source.index("class PresenceCount") : source.index("def render_extreme")]
    for literal in ("abacws", "bldg1", "Room 1.25", "Room1."):
        assert literal.lower() not in body.lower()
