# -*- coding: utf-8 -*-
"""A recurrence table's `place` column names a place, or says there is none.

Measured on the 2026-09-19 held-out read. Asked to "prepare a concise, time-stamped evidence
summary of this recurring office problem for a facilities report", the lane produced a table whose
place column read::

    | d 7baf 689-b 028-5ba 7-91a 4-686a 66265659 | other | 556 | 2026-09-08 | 2026-09-15 | 0 |

beside real rows like "floor 2". `space_iri` is a free column and some intake rows carry a sensor
uuid rather than a space; `_place_label` then applied its digit-separating rule to the uuid, which
is what put the spaces in. A reader cannot go there, and a facilities report carrying it looks like
it names somewhere.

Two behaviours are pinned here, in the order the code tries them:

1. a uuid the GRAPH can place becomes that room or floor;
2. one it cannot is collected under "place not recorded" WITH ITS COUNT — never printed, never
   guessed at, and never merged into another place's row.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from orchestrator.services import event_query_service as eqs

pytestmark = pytest.mark.unit

UUID = "d7baf689-b028-5ba7-91a4-686a66265659"
OTHER_UUID = "a1b2c3d4-0000-4000-8000-000000000001"


def rows() -> List[Dict[str, Any]]:
    return [
        {
            "place": "floor 2",
            "category": "other",
            "n": 12,
            "first_seen": "2026-09-01",
            "last_seen": "2026-09-15",
            "closed": 3,
        },
        {
            "place": UUID,
            "category": "other",
            "n": 556,
            "first_seen": "2026-09-08",
            "last_seen": "2026-09-15",
            "closed": 0,
        },
        {
            "place": OTHER_UUID,
            "category": "other",
            "n": 4,
            "first_seen": "2026-09-02",
            "last_seen": "2026-09-14",
            "closed": 1,
        },
    ]


# ── 1. what counts as a place at all ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        UUID,
        UUID.upper(),
        "http://abacwsbuilding.cardiff.ac.uk/abacws#" + UUID,
        "0123456789abcdef0123",
        "556",
    ],
)
def test_an_internal_reference_is_not_a_place(value: str) -> None:
    assert eqs.is_opaque_reference(value)
    assert eqs._place_label(value) == "", "a reference must never be rendered as a place"


@pytest.mark.parametrize(
    "value, shown",
    [
        ("floor 2", "floor 2"),
        ("http://abacwsbuilding.cardiff.ac.uk/abacws#Room5.16", "Room 5.16"),
        ("bldg:Room2.14", "Room 2.14"),
        ("Level 3: east wing", "Level 3: east wing"),
        ("", "unspecified"),
    ],
)
def test_a_real_place_still_reads_as_it_always_did(value: str, shown: str) -> None:
    assert eqs._place_label(value) == shown


def test_the_uuid_from_the_read_never_survives_as_a_prettified_label() -> None:
    """The exact string a stakeholder was shown, and the shape that produced it."""
    assert "d 7baf 689" not in eqs._place_label(UUID)
    assert eqs._place_label(UUID) == ""


# ── 2. the table ────────────────────────────────────────────────────────────────────────────────


class FakeIntake:
    """The intake store's two reads, with no Postgres."""

    def __init__(self, recurring: List[Dict[str, Any]], placeless: int = 0):
        self._rows = recurring
        self._placeless = placeless

    async def recurring_reports(self, building_id: str, category: str = "") -> List[Dict[str, Any]]:
        return list(self._rows)

    async def placeless_report_count(self, building_id: str, category: str = "") -> int:
        return self._placeless


async def _answer(
    monkeypatch: pytest.MonkeyPatch,
    recurring: List[Dict[str, Any]],
    placed: Dict[str, Any] | None = None,
    placeless: int = 0,
) -> Dict[str, Any]:
    """Run the recurrence path with a fake intake store and a fake graph."""
    monkeypatch.setattr(
        "orchestrator.services.report_intake_service.get_report_intake_service",
        lambda: FakeIntake(recurring, placeless),
    )

    async def sparql_exec(query: str) -> Dict[str, Any]:
        bindings = [
            {
                "uuid": {"value": uuid},
                "locLabel": {"value": place.get("room", "")},
                "floorNum": {"value": place.get("floor", "")},
                "onFloor": {"value": "false"},
            }
            for uuid, place in (placed or {}).items()
            if uuid in query
        ]
        return {"results": {"bindings": bindings}}

    monkeypatch.setattr("orchestrator.services.deliberation.live.sparql_exec", sparql_exec)
    service = eqs.EventQueryService("bldg1", None, [])
    return await service._recurrence("Which problems keep recurring?", None, None, "", None)


@pytest.mark.asyncio
async def test_a_uuid_the_graph_can_place_becomes_that_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = await _answer(monkeypatch, rows(), placed={UUID: {"room": "Room 5.16"}})
    text = out["formatted_response"]
    assert "Room 5.16" in text and "556" in text
    assert UUID not in text and "d 7baf 689" not in text


@pytest.mark.asyncio
async def test_a_uuid_the_graph_cannot_place_is_counted_not_printed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = await _answer(monkeypatch, rows(), placed={})
    text = out["formatted_response"]
    assert UUID not in text and OTHER_UUID not in text and "d 7baf 689" not in text
    assert "Place not recorded" in text
    assert "2 repeat group(s)" in text and "560 report(s)" in text, "their count is stated"
    assert "floor 2" in text, "the places that ARE recorded are still answered"
    assert out["unlabelled_places"] == 2
    assert out["unlabelled_reports"] == 560, "every figure in the prose is in the payload"


@pytest.mark.asyncio
async def test_an_unplaceable_group_is_never_folded_into_another_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two unlabelled references are two different places; adding them up would invent a repeat."""
    out = await _answer(monkeypatch, rows(), placed={})
    assert out["total"] == 12, "the table's total counts only the rows it shows"
    assert [r["place"] for r in out["rows"]] == ["floor 2"]


@pytest.mark.asyncio
async def test_a_graph_that_cannot_be_read_leaves_the_rows_unplaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "orchestrator.services.report_intake_service.get_report_intake_service",
        lambda: FakeIntake(rows()),
    )

    async def sparql_exec(query: str) -> Dict[str, Any]:
        raise RuntimeError("graphdb down")

    monkeypatch.setattr("orchestrator.services.deliberation.live.sparql_exec", sparql_exec)
    out = await eqs.EventQueryService("bldg1", None, [])._recurrence(
        "Which problems keep recurring?", None, None, "", None
    )
    assert UUID not in out["formatted_response"]
    assert out["unlabelled_places"] == 2, "unreadable is unplaced, never guessed"


@pytest.mark.asyncio
async def test_when_every_repeat_is_unplaceable_the_answer_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    only_uuids = [r for r in rows() if eqs.is_opaque_reference(r["place"])]
    out = await _answer(monkeypatch, only_uuids, placed={})
    text = out["formatted_response"]
    assert UUID not in text
    assert "Place not recorded" in text and "No place has more than one" in text
    assert out["rows"] == []
