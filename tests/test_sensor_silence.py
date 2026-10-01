# -*- coding: utf-8 -*-
"""W3-05 — which sensors have stopped reporting, and when each was last seen.

Two things are pinned here, and they fail in different ways:

* the DERIVATION, which must never turn "I could not ask" into "nothing is wrong"; and
* the ROUTING, because the derivation existing is not the same as the question reaching it —
  the measured failure was that the question went to the reading pipeline and was answered
  "none of them appear to have stopped reporting" over a sensor twelve days dead.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from orchestrator.services.observability import (
    is_observability_question,
    is_silence_question,
)
from orchestrator.services.routing_contract import apply_contract
from orchestrator.services.sensor_silence import (
    SensorSilence,
    SilenceReport,
    _store_modality,
    declared_sensors,
    derive_silence,
    format_silence_answer,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 29, 15, 45)


def _row(uuid="u1", label="Sensor One", store="temperature_data", minutes_ago=None, limit=15.0):
    last = None if minutes_ago is None else NOW - timedelta(minutes=minutes_ago)
    return SensorSilence(
        uuid=uuid, label=label, store=store, last_seen=last, limit_minutes=limit, measured_at=NOW
    )


# ── the question reaches the lane ────────────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "Which sensors have stopped reporting, and when was each last seen?",
        "Which sensors stopped reporting and when?",
        "Which sensors have gone silent?",
        "Are any sensors offline?",
        "Which meters are no longer reporting?",
        "When did each sensor last report?",
        "Have any devices stopped sending data?",
        "Which sensors haven't reported recently?",
        "which data points are not recording any more",
    ],
)
def test_silence_questions_are_recognised(question):
    assert is_silence_question(question)
    assert is_observability_question(question)


@pytest.mark.parametrize(
    "question",
    [
        "What is the temperature in room 5.01?",
        "Which sensors are in room 3.01?",
        "How many sensors does the building have?",
        "The light in 2.15 has stopped working.",
        "Report a broken light in the corridor.",
        "When was the lift last serviced?",
        "When was this sensor last calibrated?",
        "Compare floor 3 and floor 4 temperature.",
        "How much energy did the building use last week?",
        # A DOCUMENT, not a health sweep. The bare word "report" is accepted only after the
        # instruments, so this must stay out.
        "Where is the last report on the sensors?",
    ],
)
def test_ordinary_questions_are_not_silence_questions(question):
    assert not is_silence_question(question)


def test_the_measured_question_routes_to_observability():
    """The live failure: classified `sensor_data`, answered from a window of readings.

    A window of readings cannot evidence silence — a sensor that stopped is simply absent from
    it — so the lane that reasons from readings can only ever conclude everything is fine. That
    is verbatim what it concluded.
    """
    norm = {"intent": "sensor_data", "entities": [], "analytics": False, "general": False}
    applied = apply_contract(
        "Which sensors have stopped reporting, and when was each last seen?",
        norm,
        stage="parse",
    )
    assert norm["intent"] == "observability"
    assert "observability_query" in applied


def test_a_reading_question_still_routes_to_the_data_pipeline():
    norm = {"intent": "sensor_data", "entities": [], "analytics": False, "general": False}
    apply_contract("What is the temperature in room 5.01?", norm, stage="parse")
    assert norm["intent"] == "sensor_data"


# ── the derivation ───────────────────────────────────────────────────────────


def test_age_is_measured_at_the_sweep_not_at_read_time():
    """A row read back later must still report the age it was measured at."""
    row = _row(minutes_ago=120)
    assert row.age_minutes == 120.0
    assert row.is_silent


def test_a_sensor_inside_its_limit_is_not_silent():
    assert not _row(minutes_ago=5, limit=15.0).is_silent


def test_a_sensor_with_no_rows_is_never_rather_than_silent():
    """Never-reported and stopped-reporting are different facts and different jobs.

    "Stopped reporting" of a sensor that never wrote a row would send someone to look at an
    instrument when the missing thing is the link between the graph and the store.
    """
    row = _row(minutes_ago=None)
    assert row.age_minutes is None
    assert not row.is_silent


def test_store_modality_is_derived_from_the_key_not_hardcoded():
    assert _store_modality("temperature_data") == "temperature"
    assert _store_modality("bldg:noise_data") == "noise"
    assert _store_modality("http://example.org/ns#co2_data") == "co2"
    # A key that implies no modality falls through to the policy default rather than guessing.
    assert _store_modality("database1") == "database1"


def test_declared_sensors_dedupes_the_multiply_keyed_map(tmp_path):
    """The sensor map keys the same entry by IRI, local name and label."""
    entry = {
        "uri": "http://x#S1",
        "uuid": "u-1",
        "storage": "temperature_data",
        "label": "Temp 1",
    }
    p = tmp_path / "map.json"
    p.write_text(json.dumps({"S1": entry, "Temp 1": entry, "http://x#S1": entry}))
    by_store, labels = declared_sensors(str(p))
    assert by_store == {"temperature_data": {"u-1"}}
    assert labels == {"u-1": "Temp 1"}


def test_an_unreadable_sensor_map_yields_nothing_rather_than_raising(tmp_path):
    by_store, labels = declared_sensors(str(tmp_path / "missing.json"))
    assert by_store == {} and labels == {}


@pytest.mark.asyncio
async def test_no_sensor_map_means_cannot_say_not_all_clear(monkeypatch):
    monkeypatch.setattr(
        "orchestrator.services.sensor_silence.declared_sensors", lambda _p: ({}, {})
    )
    assert await derive_silence() is None


# ── the wording ──────────────────────────────────────────────────────────────


def test_an_unavailable_check_never_reads_as_an_all_clear():
    text = format_silence_answer(None)
    assert "not an all-clear" in text
    assert "no sensor" not in text.lower()


def test_the_answer_names_each_silent_sensor_and_when_it_was_last_seen():
    """The shape of the real finding, with the numbers the real store gave on 2026-09-29.

    One of 3,543 declared sensors was silent: the Water Main Flow Sensor in
    ``sensor_data_synth``, last row 2026-09-16 17:22:39 UTC, confirmed by hand against MySQL
    with the session pinned to +00:00.
    """
    report = SilenceReport(measured_at=NOW, declared=3543, reporting=3542)
    report.silent.append(
        SensorSilence(
            uuid="00000000-wm01-0000-0000-000000000002",
            label="Water Main Flow Sensor",
            store="database1_synth",
            last_seen=datetime(2026, 9, 16, 17, 22, 39),
            limit_minutes=15.0,
            measured_at=NOW,
        )
    )
    text = format_silence_answer(report, "UTC")
    assert "Water Main Flow Sensor" in text
    assert "2026-09-16 17:22" in text  # the time it was last seen, not the time of asking
    assert "12.9 days" in text
    assert "1 of 3543" in text  # every count states its denominator


def test_a_clean_sweep_states_its_denominator():
    report = SilenceReport(measured_at=NOW, declared=40, reporting=40)
    text = format_silence_answer(report, "UTC")
    assert "40 of 40" in text


def test_never_reported_is_worded_as_never_not_as_stopped():
    report = SilenceReport(measured_at=NOW, declared=2, reporting=1)
    report.never.append(_row(label="Orphan Sensor", minutes_ago=None))
    text = format_silence_answer(report, "UTC")
    assert "never reported rather than stopped" in text
    assert "Orphan Sensor" in text


def test_a_store_that_could_not_be_asked_is_named_as_unknown():
    report = SilenceReport(measured_at=NOW, declared=10, reporting=4)
    report.not_probed.append("noise_data: no adapter (6 sensors)")
    text = format_silence_answer(report, "UTC")
    assert "unknown rather than healthy" in text
    assert "noise_data" in text
    assert not report.complete


def test_a_long_list_is_capped_and_says_how_many_it_left_out():
    from orchestrator.services.sensor_silence import NAMED_LIMIT

    report = SilenceReport(measured_at=NOW, declared=500, reporting=0)
    for i in range(NAMED_LIMIT + 7):
        report.silent.append(_row(uuid=f"u{i}", label=f"Sensor {i}", minutes_ago=600))
    text = format_silence_answer(report, "UTC")
    assert f"{NAMED_LIMIT + 7} of 500" in text
    assert "7 further sensors are silent" in text


# ── the wide store answers per sensor, at a cost it only pays when it must ───

#: Real-shaped ids: both adapters refuse anything that is not uuid-shaped, so a test using a
#: short placeholder would pass while measuring the refusal rather than the query.
UA = "0f4f8d11-1111-4111-8111-111111111111"
UB = "0f4f8d11-2222-4222-8222-222222222222"
UC = "0f4f8d11-3333-4333-8333-333333333333"


class _Result:
    def __init__(self, success, data):
        self.success, self.data = success, data


def _wide_adapter(monkeypatch, responses):
    """A wide MySQLAdapter whose queries are answered from `responses`, in order."""
    from orchestrator.services.adapters.mysql_adapter import MySQLAdapter

    ad = MySQLAdapter.__new__(MySQLAdapter)
    ad._table = "sensor_data"
    sent = []

    async def _cols():
        return {"Datetime", UA, UB, UC}

    async def _exec(sql):
        sent.append(sql)
        return responses[min(len(sent) - 1, len(responses) - 1)]

    monkeypatch.setattr(ad, "get_columns", _cols, raising=False)
    monkeypatch.setattr(ad, "execute_query", _exec, raising=False)
    return ad, sent


@pytest.mark.asyncio
async def test_a_fresh_wide_sensor_is_answered_by_the_windowed_pass_alone(monkeypatch):
    """The cheap pass is one range scan; on bldg1 that is 0.0s against 136.3s unbounded."""
    fresh = datetime(2026, 9, 29, 15, 34)
    ad, sent = _wide_adapter(
        monkeypatch, [_Result(True, [{"c0": fresh, "c1": fresh, "c2": fresh}])]
    )
    out = await ad.latest_by_uuid_exhaustive([UA, UB, UC])
    assert out == {UA: fresh, UB: fresh, UC: fresh}
    assert len(sent) == 1
    assert "INTERVAL 24 HOUR" in sent[0]


@pytest.mark.asyncio
async def test_only_the_silent_columns_pay_for_the_full_scan(monkeypatch):
    """Cost is proportional to how much is WRONG, not to the size of the building."""
    fresh = datetime(2026, 9, 29, 15, 34)
    old = datetime(2026, 9, 16, 17, 22, 39)
    ad, sent = _wide_adapter(
        monkeypatch,
        [
            _Result(True, [{"c0": fresh, "c1": None, "c2": None}]),  # windowed
            _Result(True, [{"c0": old, "c1": None}]),  # unbounded, for the two silent
        ],
    )
    out = await ad.latest_by_uuid_exhaustive([UA, UB, UC])
    assert out[UA] == fresh
    assert out[UB] == old
    # Nothing at all in the whole table: proof of absence, so None rather than missing.
    assert out[UC] is None
    assert len(sent) == 2
    assert "INTERVAL" not in sent[1]


@pytest.mark.asyncio
async def test_a_uuid_that_is_not_a_column_is_omitted_not_reported_dead(monkeypatch):
    ad, _ = _wide_adapter(monkeypatch, [_Result(True, [{}])])
    assert await ad.latest_by_uuid_exhaustive(["not-a-column-here"]) == {}


@pytest.mark.asyncio
async def test_a_failed_wide_query_reports_nothing_rather_than_everything_dead(monkeypatch):
    ad, _ = _wide_adapter(monkeypatch, [_Result(False, None)])
    assert await ad.latest_by_uuid_exhaustive([UA]) == {}


def test_the_wide_per_sensor_probe_is_not_called_latest_by_uuid():
    """The SQL lane probes for `latest_by_uuid` and skips its store check when it finds one.

    Exposing the wide per-column scan under that name would change what every wide-store
    reading turn sets aside, and could put the full scan on a chat turn.
    """
    from orchestrator.services.adapters.mysql_adapter import MySQLAdapter

    assert not hasattr(MySQLAdapter, "latest_by_uuid")
    assert hasattr(MySQLAdapter, "latest_by_uuid_exhaustive")


@pytest.mark.asyncio
async def test_the_narrow_adapter_does_not_inherit_the_wide_column_scan(monkeypatch):
    """A narrow table's sensors are ROWS; the inherited query would name them as columns."""
    from orchestrator.services.adapters.mysql_narrow_adapter import MySQLNarrowAdapter

    ad = MySQLNarrowAdapter.__new__(MySQLNarrowAdapter)
    ad._table = "temperature_data"
    sent = []

    async def _exec(sql):
        sent.append(sql)
        return _Result(True, [{"uuid": UA, "latest": datetime(2026, 9, 29, 15, 34)}])

    monkeypatch.setattr(ad, "execute_query", _exec, raising=False)
    out = await ad.latest_by_uuid_exhaustive([UA])
    assert out == {UA: datetime(2026, 9, 29, 15, 34)}
    assert len(sent) == 1
    assert "GROUP BY" in sent[0] and "CASE WHEN" not in sent[0]


# ── the lane asks the right probe, and says so when it cannot ────────────────


class _Adapter:
    def __init__(self, **probes):
        for name, value in probes.items():
            setattr(self, name, value)


@pytest.mark.asyncio
async def test_the_exhaustive_probe_is_preferred_over_the_cheap_one():
    from orchestrator.services.sensor_silence import _last_seen_for_store

    async def cheap(_u):
        return {"u": None}

    async def exact(_u):
        return {"u": datetime(2026, 9, 16, 17, 22)}

    ad = _Adapter(latest_by_uuid=cheap, latest_by_uuid_exhaustive=exact)
    assert await _last_seen_for_store(ad, ["u"]) == {"u": datetime(2026, 9, 16, 17, 22)}


@pytest.mark.asyncio
async def test_an_adapter_with_no_per_sensor_probe_is_a_named_gap():
    from orchestrator.services.sensor_silence import _last_seen_for_store

    assert await _last_seen_for_store(_Adapter(), ["u"]) is None
