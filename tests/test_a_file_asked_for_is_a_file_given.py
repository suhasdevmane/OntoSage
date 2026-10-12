"""A file asked for is a file given, linked, with its sensors named (2026-10-11).

Artifact check: "Export ... as CSV" and "... as a PDF report" were summarised in prose with no file;
then the CSV was written but the reply carried no link; "... as a PDF report" came out as CSV; and
"Give me a Word document summarising ..." reached the report planner and declined.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from orchestrator.agents import sql_agent
from orchestrator.agents.data_export_agent import _readings_summary
from orchestrator.services import routing_contract as rc
from orchestrator.workflow import _orchestrator as orch

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "q, fmt",
    [
        ("Export the energy use per floor last week as a PDF report", "pdf"),
        ("Give me a Word document summarising yesterday's energy use", "docx"),
        ("Export the temperature readings for floor 3 yesterday as CSV", "csv"),
        ("Put the CO2 for floor 2 in a spreadsheet", "csv"),
        ("Export the readings", None),
    ],
)
def test_the_format_the_reader_names_wins(q, fmt):
    assert orch._export_format_named(q) == fmt


def test_a_file_request_keeps_the_aggregate_lane_out():
    assert sql_agent._FILE_REQUEST_RE.search("Export the temperature for floor 3 as CSV")
    assert not sql_agent._FILE_REQUEST_RE.search("What was the temperature on floor 3 yesterday?")


@pytest.mark.parametrize(
    "intent, q, want",
    [
        ("report", "Give me a Word document summarising yesterday's energy use", "export"),
        ("analytics", "Show the CO2 for floor 2 last week as a PDF", "export"),
        ("register", "Send me a PDF of the cost register", None),
        ("analytics", "What was the CO2 on floor 2 last week?", None),
    ],
)
def test_a_readings_question_naming_a_format_is_an_export(intent, q, want):
    ctx = SimpleNamespace(intent=intent, query=q)
    assert rc._r_file_request_is_an_export(ctx) == want


def test_rows_carry_their_sensor_and_the_document_its_figures():
    rows = orch._label_export_rows(
        [{"uuid": "u1", "value": 21.0, "timestamp": "2026-10-10T08:00:00"}],
        {"u1": {"label": "Room 3.10 temperature", "unit": "°C"}},
    )
    assert rows[0]["sensor"] == "Room 3.10 temperature" and rows[0]["unit"] == "°C"
    summary, span = _readings_summary(rows)
    assert summary == {
        "Room 3.10 temperature (°C)": {"count": 1, "min": 21.0, "avg": 21.0, "max": 21.0}
    }
    assert span.startswith("2026-10-10 08:00")


def test_the_reply_links_the_file_and_never_previews_a_binary():
    src = inspect.getsource(orch.WorkflowOrchestrator._response_node)
    assert "[Download {er['filename']}]({_dl})" in src
    assert "isinstance(_content, str)" in src
