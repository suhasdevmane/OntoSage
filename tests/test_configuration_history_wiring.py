# -*- coding: utf-8 -*-
"""Configuration history, from the graph to the answer (V6-T07 wiring).

`history.py` has done the arithmetic for acceptance scenario 3 since 2026-08-21 — resolve a
reading against the configuration in force WHEN IT WAS TAKEN, flag a window that spans a change
— and it was **wired and inert**. Two independent gaps, either of which alone was enough:

1. **Nothing loaded a period.** `assemble._configuration_periods` reads `_config_periods` off
   the bus "when the sparql lane starts supplying it". No lane ever did, so `assess_trend`
   received `[]` and every trend came back REPORTABLE no matter what had been moved.

2. **The reader could not have used them anyway.** It constructs
   `ConfigurationPeriod(subject=...)` against a dataclass that had **no `subject` field**. The
   resulting `TypeError` would have been swallowed by its own broad `except` and returned an
   empty list — so supplying data would have changed nothing, and the fix for gap 1 would have
   looked like it had failed.

Gap 2 is the more instructive one: it was undetectable while gap 1 existed, because the code
path could never run. Two dormant defects in series look exactly like one working feature.
"""

from datetime import datetime

import pytest

from orchestrator.services.evidence.history import (
    ConfigurationPeriod,
    _parse_dt,
    caveat_for_uuids,
    periods_from_rows,
    periods_query,
)

pytestmark = pytest.mark.unit

NS = "http://example.org/bldg#"
POINT = f"{NS}Air_Temperature_Sensor_5.16"


# ── the dataclass the reader actually needs ──────────────────────────────────


def test_a_period_can_carry_its_subject():
    """Gap 2. Without this field the bus reader raises TypeError into its own except and
    returns [], so supplying periods would have changed nothing at all."""
    period = ConfigurationPeriod(effective_from=datetime(2026, 1, 1), subject=POINT)
    assert period.subject == POINT


def test_the_bus_reader_constructs_a_period_without_raising():
    """The end-to-end version of the test above: drive the real reader with a real bus entry."""
    from orchestrator.services.evidence.assemble import _configuration_periods

    got = _configuration_periods(
        {
            "_config_periods": [
                {
                    "subject": POINT,
                    "location": f"{NS}Room5.16",
                    "effective_from": "2026-04-01T00:00:00",
                    "effective_to": "",
                    "change": "relocation",
                }
            ]
        }
    )
    assert len(got) == 1, "the bus reader still yields nothing for a well-formed entry"
    assert got[0].change == "relocation"
    assert got[0].location == f"{NS}Room5.16"


# ── loading from the graph ───────────────────────────────────────────────────


def test_the_query_projects_the_uuid_an_answer_actually_carries():
    """A period reachable only by point IRI would be correct and never matched: answers carry
    timeseries uuids, not IRIs. The present-but-invisible failure, one layer along."""
    q = periods_query(NS)
    assert "ontosage:ConfigurationPeriod" in q
    assert "ref:hasTimeseriesId ?uuid" in q
    assert "ontosage:effectiveFrom" in q


def test_rows_parse_from_raw_sparql_json():
    payload = {
        "results": {
            "bindings": [
                {
                    "point": {"value": POINT},
                    "uuid": {"value": "u1"},
                    "from": {"value": "2026-01-01T00:00:00"},
                    "location": {"value": f"{NS}Room5.01"},
                    "change": {"value": "first_observed"},
                }
            ]
        }
    }
    got = periods_from_rows(payload)
    assert got["uuid_to_point"] == {"u1": POINT}
    assert got["by_point"][POINT][0].location == f"{NS}Room5.01"
    assert got["by_point"][POINT][0].subject == POINT


def test_rows_parse_from_the_rows_shape_too():
    """Both executor conventions are live in this codebase; writing for one and being handed
    the other is BUG-259."""
    got = periods_from_rows(
        {"ok": True, "rows": [{"point": POINT, "uuid": "u1", "from": "2026-01-01T00:00:00"}]}
    )
    assert got["by_point"][POINT]


def test_an_unparseable_date_drops_the_period_rather_than_guessing():
    """A period placed at "now" or at the epoch misattributes readings exactly the way a
    missing one does, while looking authoritative."""
    got = periods_from_rows({"ok": True, "rows": [{"point": POINT, "from": "not-a-date"}]})
    assert got["by_point"] == {}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-04-01T00:00:00", datetime(2026, 4, 1)),
        ("2026-04-01T00:00:00Z", datetime(2026, 4, 1)),
        ("2026-04-01 00:00:00", datetime(2026, 4, 1)),
        ("", None),
        ("garbage", None),
    ],
)
def test_date_parsing_is_strict(raw, expected):
    assert _parse_dt(raw) == expected


# ── the caveat ───────────────────────────────────────────────────────────────


def _history():
    return {
        "uuid_to_point": {"u1": POINT},
        "by_point": {
            POINT: [
                ConfigurationPeriod(
                    effective_from=datetime(2026, 1, 1),
                    effective_to=datetime(2026, 4, 1),
                    location=f"{NS}Room5.01",
                    change="first_observed",
                    subject=POINT,
                ),
                ConfigurationPeriod(
                    effective_from=datetime(2026, 4, 1),
                    location=f"{NS}Room5.09",
                    change="relocation",
                    subject=POINT,
                ),
            ]
        },
    }


def test_a_window_spanning_a_relocation_is_caveated_and_names_the_sensor():
    text = caveat_for_uuids(_history(), ["u1"], datetime(2026, 3, 1), datetime(2026, 5, 1))
    assert text, "a window spanning a relocation produced no caveat"
    assert "relocation" in text
    assert "Air_Temperature_Sensor_5.16" in text, "the caveat does not say which sensor moved"
    assert "indistinguishable from a real change" in text


def test_a_window_inside_one_configuration_is_silent():
    """A caveat on every answer is furniture, and furniture is not read."""
    assert not caveat_for_uuids(_history(), ["u1"], datetime(2026, 2, 1), datetime(2026, 3, 1))


def test_an_unknown_uuid_produces_no_caveat():
    """An unrelated relocation elsewhere in the building must never caveat this answer."""
    assert not caveat_for_uuids(_history(), ["other"], datetime(2026, 3, 1), datetime(2026, 5, 1))


def test_no_history_is_silent_rather_than_alarming():
    assert not caveat_for_uuids({}, ["u1"], datetime(2026, 3, 1), datetime(2026, 5, 1))


def test_one_sensor_is_caveated_once_even_with_several_uuids():
    history = _history()
    history["uuid_to_point"]["u2"] = POINT
    text = caveat_for_uuids(history, ["u1", "u2"], datetime(2026, 3, 1), datetime(2026, 5, 1))
    assert text.count("Air_Temperature_Sensor_5.16") == 1


# ── reachability: the half that makes the other half true ────────────────────


class TestReachability:
    """Gap 1. Every assertion above passed for three days while the feature did nothing,
    because no caller existed. These are the tests that would have caught that."""

    def test_a_lane_populates_the_bus_key_the_reader_expects(self):
        from pathlib import Path

        src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
        assert "_load_configuration_periods" in src
        body = src[src.index("async def _load_configuration_periods") :][:2600]
        assert 'results["_config_periods"]' in body, (
            "nothing writes the bus key assemble._configuration_periods reads; the trend "
            "integrity verdict will keep seeing an empty list"
        )

    def test_the_loader_runs_before_the_record_is_assembled(self):
        """Loaded after assembly, the periods would reach the caveat but never the evidence
        record — the gate would stay silent while the prose warned."""
        from pathlib import Path

        src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
        load_at = src.index("await self._load_configuration_periods(results)")
        assemble_at = src.index('results["evidence_record"] = record_for_response')
        assert load_at < assemble_at

    def test_only_contributing_sensors_are_loaded(self):
        from pathlib import Path

        src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
        body = src[src.index("async def _load_configuration_periods") :][:2600]
        assert (
            "contributing_uuids" in body
        ), "the loader would caveat an answer with an unrelated sensor's relocation"

    def test_the_caveat_reuses_the_loaded_history_rather_than_querying_again(self):
        """Two views of one fact drift apart; this keeps the prose and the evidence record
        reading the same periods."""
        from pathlib import Path

        src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
        body = src[src.index("async def _configuration_caveat") :][:2200]
        assert "_config_history" in body
        assert "for_building" not in body, "the caveat queries the graph a second time"

    def test_the_caveat_is_appended_after_persona_formatting(self):
        """A caveat an LLM may reword is a caveat that can vanish — measured in V6-T27 when the
        meter boundary was paraphrased out of the answer."""
        from pathlib import Path

        src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
        fmt = src.index("Persona formatting (first pass)")
        note = src.index("_history_note = await self._configuration_caveat")
        assert note > fmt

    def test_history_never_costs_the_answer(self):
        from pathlib import Path

        src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
        for marker in ("async def _load_configuration_periods", "async def _configuration_caveat"):
            start = src.index(marker)
            rest = src[start + len(marker) :]
            # Bound at the next sibling method. An unbounded slice reads the NEXT method's
            # guard and reports a defended function that is not — the same measurement error
            # that made a score assertion read the wrong numbers in V6-T26.
            ends = [i for i in (rest.find("\n    async def "), rest.find("\n    def ")) if i > 0]
            body = rest[: min(ends)] if ends else rest
            assert "except Exception" in body, f"{marker} can raise into the response node"
