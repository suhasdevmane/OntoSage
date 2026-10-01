# -*- coding: utf-8 -*-
"""A column a LIVE feed writes is not the publisher's to invent (BUG-888).

`input/feeds.yaml` declares three Open-Meteo `rest_poll` feeds for Cardiff. They poll every
300 s and their readings land in `sensordb.sensor_data`, in a column named for each feed's
derived UUID — the write path is real and was verified against the store.

The dev publisher reads the wide table's columns from `information_schema` and generates a
value for every one of them, so it wrote over those three columns every 30 s. Measured
2026-09-29 against the live store and the live API:

    15:26:15 UTC   21.90 degC / 71.00 % / 19.40 km/h   <- the feed; Open-Meteo said 22.0/70/19.4
    15:26:41 UTC   24.06      / 56.80   /  7.08        <- the publisher
    15:27:11 UTC   24.15      / 56.92   /  7.02        <- the publisher
    15:27:41 UTC   24.23      / 56.21   /  7.08        <- the publisher
    15:28:11 UTC   24.31      / 55.77   /  7.04        <- the publisher

Ten samples in eleven were fabricated, so every "what is the outdoor temperature right now?"
read a number nobody measured. Generating a value for a sensor that has no live source is
this service's job (BUG-144); generating one on top of a source that IS live is a
fabrication, which design contract 4 forbids.

The two traps these tests hold:

* **The derivation must match.** The publisher derives md5("<building>:<feed_id>")
  independently of `FeedRegistry._derive_uuid`. If the two ever disagree the exclusion set
  matches no column, nothing is protected, and nothing fails — so the agreement is asserted
  directly against the orchestrator's own function.
* **A wrong BUILDING_ID looks like success.** It derives well-formed UUIDs that match
  nothing, so `load_columns` must report the count it ACTUALLY removed, not the count it was
  handed (lesson #126).
"""

import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent
_PUBLISHER_DIR = _ROOT / "mysql-dummy-publish-dev"
sys.path.insert(0, str(_PUBLISHER_DIR))

pub = pytest.importorskip("mysql_dummy_publisher")


def _feeds_yaml() -> Path:
    """The active building's feeds.yaml, flat layout first then a parked building's."""
    flat = _ROOT / "input" / "feeds.yaml"
    if flat.exists():
        return flat
    parked = sorted(_ROOT.glob("bldg*/feeds.yaml"))
    if not parked:
        pytest.skip("no feeds.yaml in this tree")
    return parked[0]


def _live_feed_ids(path: Path):
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [
        str(e["id"])
        for e in (data.get("feeds") or [])
        if isinstance(e, dict)
        and e.get("enabled", True) is not False
        and str(e.get("type", "")) in pub._LIVE_FEED_TYPES
        and e.get("id")
    ]


def test_derivation_matches_the_feed_registry_exactly():
    """The publisher and the registry must derive the same UUID or nothing is protected."""
    registry = pytest.importorskip("orchestrator.services.feeds.registry")
    for building in ("bldg1", "bldg2", "other-building_7"):
        for feed_id in ("outside_weather_temp", "a.feed-with.punctuation", "x"):
            assert pub._derive_feed_uuid(building, feed_id) == registry._derive_uuid(
                building, feed_id
            )


def test_enabled_rest_poll_feeds_are_owned():
    path = _feeds_yaml()
    ids = _live_feed_ids(path)
    if not ids:
        pytest.skip("this building declares no enabled live feeds")
    owned = pub.feed_owned_uuids(str(path), "bldg1")
    assert len(owned) == len(ids)
    for feed_id in ids:
        assert pub._derive_feed_uuid("bldg1", feed_id) in owned


def test_a_disabled_or_non_polling_feed_owns_nothing(tmp_path):
    """Only a feed that actually writes owns a column — the rest keep the old behaviour."""
    path = tmp_path / "feeds.yaml"
    path.write_text(
        "feeds:\n"
        "  - id: live_one\n"
        "    type: rest_poll\n"
        "    url: https://example.invalid/x\n"
        "  - id: switched_off\n"
        "    type: rest_poll\n"
        "    url: https://example.invalid/y\n"
        "    enabled: false\n"
        "  - id: a_file_source\n"
        "    type: timetable\n"
        "    path: x.csv\n",
        encoding="utf-8",
    )
    owned = pub.feed_owned_uuids(str(path), "bldg1")
    assert owned == {pub._derive_feed_uuid("bldg1", "live_one")}


def test_an_explicit_uuid_in_the_yaml_wins_over_the_derivation(tmp_path):
    path = tmp_path / "feeds.yaml"
    path.write_text(
        "feeds:\n"
        "  - id: pinned\n"
        "    type: rest_poll\n"
        "    url: https://example.invalid/x\n"
        "    uuid: 11111111-2222-3333-4444-555555555555\n",
        encoding="utf-8",
    )
    assert pub.feed_owned_uuids(str(path), "bldg1") == {"11111111-2222-3333-4444-555555555555"}


def test_a_missing_or_unreadable_feeds_file_owns_nothing(tmp_path):
    """Fail-open is the OLD behaviour, so it must be reachable — and it says so on the way."""
    assert pub.feed_owned_uuids(str(tmp_path / "absent.yaml"), "bldg1") == set()
    broken = tmp_path / "feeds.yaml"
    broken.write_text("feeds: [ this: is: not: yaml\n", encoding="utf-8")
    assert pub.feed_owned_uuids(str(broken), "bldg1") == set()


class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *a, **k):
        return None

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _Cur(self._rows)


def _col(name, dtype="decimal"):
    return {
        "cname": name,
        "dtype": dtype,
        "ctype": f"{dtype}(6,2)",
        "isnull": "YES",
        "nprec": 6,
        "nscale": 2,
    }


def test_load_columns_drops_the_feed_owned_columns(monkeypatch, capsys):
    owned_uuid = pub._derive_feed_uuid("bldg1", "outside_weather_temp")
    rows = [
        _col("Datetime", "timestamp"),
        _col("aaaaaaaa-0000-0000-0000-000000000001"),
        _col(owned_uuid),
    ]
    monkeypatch.setattr(pub, "feed_owned_uuids", lambda *a, **k: {owned_uuid})
    ts_col, cols = pub.load_columns(_Conn(rows), {"db": "sensordb", "table": "sensor_data"})
    assert ts_col == "Datetime"
    names = [c["cname"] for c in cols]
    assert owned_uuid not in names
    assert "aaaaaaaa-0000-0000-0000-000000000001" in names
    assert "held back from the wide table: 1" in capsys.readouterr().out


def test_load_columns_warns_when_it_excluded_nothing(monkeypatch, capsys):
    """A count of what it was ASKED to exclude would have reported success here."""
    rows = [_col("Datetime", "timestamp"), _col("aaaaaaaa-0000-0000-0000-000000000001")]
    monkeypatch.setattr(
        pub, "feed_owned_uuids", lambda *a, **k: {"ffffffff-0000-0000-0000-000000000009"}
    )
    _, cols = pub.load_columns(_Conn(rows), {"db": "sensordb", "table": "sensor_data"})
    assert len(cols) == 1
    out = capsys.readouterr().out
    assert "held back from the wide table: 0" in out
    assert "WARNING" in out


def test_no_exclusion_leaves_every_column_alone(monkeypatch):
    rows = [_col("Datetime", "timestamp"), _col("aaaaaaaa-0000-0000-0000-000000000001")]
    monkeypatch.setattr(pub, "feed_owned_uuids", lambda *a, **k: set())
    _, cols = pub.load_columns(_Conn(rows), {"db": "sensordb", "table": "sensor_data"})
    assert [c["cname"] for c in cols] == ["aaaaaaaa-0000-0000-0000-000000000001"]
