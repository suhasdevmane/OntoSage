# -*- coding: utf-8 -*-
"""A turn that states no figure carries no sampling disclaimer (BUG-1401).

MEASURED 2026-10-01, facility01 on /v1:

    Q 'What is the air pressure in room 2.01 right now?'
    A 'I'm sorry, but there is no air-pressure sensor recorded for Room 2.01, so I can't provide
       a current value. _At least one sensor returned the full 60 rows this question reads per
       sensor, so these readings are a SAMPLE of the newest data ... The readings used run from
       2026-10-01 04:22:18 to 2026-10-01 09:23:15._'

The first sentence is correct and verified against the graph. The disclaimer is correct
boilerplate on the wrong kind of turn: it tells the reader that readings informed a conclusion
drawn from their ABSENCE. The note exists so a truncated sample is not read as a total, so it
is suppressed ONLY where no total -- no figure at all -- is given.

Measured over 3,046 stored answers before landing: 57 carry the note, 5 would lose it, and all
5 state no figure (four pressure declines and "No purity measurement is available").
"""

import pytest

from orchestrator.services.disclosure_gate import gives_a_figure

pytestmark = pytest.mark.unit

DECLINE = (
    "I'm sorry, but there is no air-pressure sensor recorded for Room 2.01, so I can't provide "
    "a current value."
)
WITH_NOTE = DECLINE + (
    " _The readings query reached its row limit of 60 rows, so these readings are a SAMPLE of "
    "the newest data and their number is not a count of what the period holds. The readings "
    "used run from 2026-10-01 04:22:18 to 2026-10-01 09:23:15._"
    "\n\n---\n*Sources: `Building model` `Sensor data`*"
)


class TestNoFigure:
    def test_the_live_decline_states_no_figure(self):
        assert gives_a_figure(DECLINE) is False

    def test_the_notes_own_numbers_do_not_count(self):
        """'60 rows' and two timestamps live in the note itself; it is cut before counting."""
        assert gives_a_figure(WITH_NOTE) is False

    @pytest.mark.parametrize(
        "text",
        [
            "No purity measurement is available. These values describe flow, not water purity.",
            "There is no occupancy sensor recorded for Floor 3.",
            "The register holds WO-0012 and WO-0031; neither records a due date.",
            "Readings were taken on 1 October 2026 at 09:23 but no value could be summarised.",
            "![Analysis Plot](http://localhost:8080/static/plot_20261001_171806.png)",
            "",
        ],
    )
    def test_dates_times_ids_rooms_and_images_are_not_figures(self, text):
        assert gives_a_figure(text) is False


class TestAFigure:
    @pytest.mark.parametrize(
        "text",
        [
            "Mean 23.5 °C across 288 sensors on 2026-10-01.",
            "| Illuminance Sensor 5.01 | 705 | unit not recorded |",
            "CO2 peaked at 1,240 ppm in Room 2.01 at 09:23.",
            "Occupancy was 0 in every room.",
            "Energy this week: 3 861 kWh.",
        ],
    )
    def test_a_stated_number_is_a_figure(self, text):
        assert gives_a_figure(text) is True


class TestItIsWired:
    def test_the_sql_lane_checks_before_its_own_append(self):
        """The gate found the note still attached on 2026-10-02: the SQL lane appends it to its
        own prose before the response node runs, so the test has to be made there too."""
        import inspect

        from orchestrator.agents import sql_agent

        src = inspect.getsource(sql_agent)
        i_fig = src.index("rows_capped and not gives_a_figure(formatted)")
        i_note = src.index("formatted += truncation_note(")
        assert i_fig < i_note

    def test_the_response_node_consults_it_before_attaching_the_note(self):
        import inspect

        from orchestrator.workflow import _orchestrator

        src = inspect.getsource(_orchestrator)
        assert "gives_a_figure" in src
        i_fig = src.index("_gives_a_figure(final_response)")
        i_note = src.index("_cnote = _truncation_note(_cap)")
        assert i_fig < i_note, "the figure test must run BEFORE the note is rendered"
