"""A figure per day or per hour, reduced in the store (BUG-1563).

"Give me the daily average temperature in room X for the last 7 days" was answered with one mean
for the whole week, and the relevance gate rightly replaced it with a decline. Synthetic data, no
building, no live store.
"""

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from orchestrator.services import aggregate_breakdown as ab
from orchestrator.services import aggregate_lane as al

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "q,want",
    [
        ("Give me the daily average temperature in room 1.01 for the last 7 days.", "day"),
        ("What did the CO2 in room 1.01 look like hour by hour yesterday?", "hour"),
        ("Show the hourly humidity in room 1.01 today", "hour"),
        ("Average noise per day on floor 2 this week", "day"),
    ],
)
def test_a_breakdown_word_names_its_period(q, want):
    assert ab.per_period_bucket(q)[1] == want


@pytest.mark.parametrize(
    "q",
    [
        "What is the average temperature in room 1.01 this week?",
        "What is the daily pattern of CO2 in room 1.01?",
        "When is room 1.01 busiest during the day?",
        "What's the typical hourly profile of noise on floor 2?",
    ],
)
def test_a_summary_or_a_pattern_is_not_a_breakdown(q):
    assert ab.per_period_bucket(q) is None


def test_a_day_starts_at_the_building_s_midnight_not_at_the_window_s_start():
    # 14:19 UTC on a BST day is 15:19 local; local midnight is 23:00 UTC the evening before.
    got = ab.aligned_start(datetime(2026, 10, 10, 14, 19), ab.DAY, "Europe/London")
    assert got == datetime(2026, 10, 9, 23, 0)
    hour = ab.aligned_start(datetime(2026, 10, 10, 14, 19), ab.HOUR, "Europe/London")
    assert hour == datetime(2026, 10, 10, 14, 0)


def _run(buckets, window, kind=("day", ab.DAY), uuids=("a", "b")):
    async def ready(members, storage_map, adapter_for, store_key):
        return {"s": (object(), list(members))}, []

    async def run_buckets(adapter, group, aligned, bucket_s, bands):
        assert bucket_s == kind[1]
        return [al.SensorBucket(u, i, n, t) for (u, i, n, t) in buckets], []

    facts = {u: SimpleNamespace(unit="°C") for u in uuids}
    orig = (al._stores_ready, al.run_buckets)
    al._stores_ready, al.run_buckets = ready, run_buckets
    try:
        return asyncio.run(
            ab.answer_breakdown(
                question="daily average temperature in room 1.01 for the last 3 days",
                bucket=(kind[1], kind[0]),
                uuids=list(uuids),
                facts=facts,
                storage_map={u: "s" for u in uuids},
                window=window,
                tz_name="UTC",
                adapter_for=lambda k: None,
                store_key=lambda k: k,
                bands=None,
                quantity="temperature",
                place="Room 1.01",
            )
        )
    finally:
        al._stores_ready, al.run_buckets = orig


def test_sensors_are_pooled_by_total_over_count_one_row_per_day():
    window = al.Window("2026-10-07 12:00:00", "2026-10-10 12:00:00", "over the last 3 days")
    # a: 10 readings summing 200 (20.0) on day 0; b: 30 readings summing 660 (22.0) on day 0.
    # Pooled day 0 = 860 / 40 = 21.5, not the mean of means (21.0).
    res = _run(
        [("a", 0, 10, 200.0), ("b", 0, 30, 660.0), ("a", 1, 10, 230.0), ("a", 3, 5, 120.0)],
        window,
    )
    assert res and res["aggregate_lane"] is True
    text = res["formatted_response"]
    assert "| Wed 07 Oct | 21.5 | 40 | 2 |" in text
    assert "| Thu 08 Oct | 23.0 | 10 | 1 |" in text
    assert text.startswith("**Daily average temperature in Room 1.01")
    # The window started at noon and ends at noon: the first day is moved back to midnight and
    # shown whole, the last is still in progress -- and the answer says both.
    assert "the first day is shown whole" in text
    assert "The last day is still in progress" in text


def test_too_many_rows_is_left_to_the_other_paths():
    window = al.Window("2026-08-01 00:00:00", "2026-10-10 00:00:00", "since August")
    assert _run([("a", 0, 1, 1.0), ("a", 1, 1, 1.0)], window) is None


def test_one_period_is_not_a_breakdown():
    window = al.Window("2026-10-10 00:00:00", "2026-10-10 12:00:00", "today")
    assert _run([("a", 0, 1, 1.0)], window) is None
