# -*- coding: utf-8 -*-
"""No chart, no caption and no 'I summarised the data' without a fetched series (2D-16, C19).

* A question about notification provisions produced "The bar chart compares the availability of
  audible alerts ... across monitoring scenarios" plus an image link, with NO data behind it.
* Another answer ended "I summarised the data above but couldn't render the chart this time" after
  an answer that held no data.

Offline: the plotting service, the model and the executor are never reached.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS

import pytest

from orchestrator.agents import visualization_agent as mod
from orchestrator.services import viz_honesty as vh

pytestmark = pytest.mark.unit

SERIES = {"data": [{"timestamp": "2026-09-15 03:08:06", "uuid": "u", "value": 704}]}
BINDINGS = {
    "head": {"vars": ["s"]},
    "results": {"bindings": [{"s": {"type": "uri", "value": "http://x/AudibleAlert"}}]},
}


# ── what counts as a series ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        [],
        {"data": []},
        BINDINGS,
        [{"s": {"type": "uri", "value": "http://x/A"}}],
        {"data": [{"timestamp": "2026-09-15", "uuid": "u", "value": "n/a"}]},
        [{"name": "Audible alert", "kind": "sounder"}],
        "just text",
    ],
)
def test_rows_without_a_measured_value_are_not_a_series(data):
    assert not vh.has_plottable_series(data)


@pytest.mark.parametrize(
    "data",
    [
        SERIES,
        [{"floor_name": "Ground", "average": 21.4}, {"floor_name": "One", "average": 22.0}],
        {"data": [{"timestamp": "t", "value": "21.5"}]},
    ],
)
def test_rows_with_a_number_are_a_series(data):
    assert vh.has_plottable_series(data)


def test_an_identifier_that_happens_to_be_numeric_is_not_a_measurement():
    assert not vh.has_plottable_series([{"floor_id": 3, "label": "Third floor"}])


# ── the agent draws nothing and asks no model when there is nothing to draw ──


def _agent(monkeypatch):
    calls = []

    async def fake_generate(prompt, **kw):
        calls.append(prompt)
        return "The bar chart compares the availability of audible alerts across scenarios."

    monkeypatch.setattr(mod.llm_manager, "generate", fake_generate)
    agent = mod.VisualizationAgent.__new__(mod.VisualizationAgent)

    async def boom(code):
        raise AssertionError("nothing may be executed for a chart with no data")

    agent._execute_viz_code = boom
    return agent, calls


def test_graph_bindings_produce_no_chart_and_no_model_call(monkeypatch):
    agent, calls = _agent(monkeypatch)
    state = NS(intermediate_results={}, building_id=None)
    out = asyncio.run(
        agent.create_visualization(state, "chart the notification provisions", BINDINGS)
    )
    assert out["success"] is False and out["skipped"] == "no_data"
    assert "media" not in out and "formatted_response" not in out
    assert calls == [], "the model must not be asked to plot or describe nothing"


def test_an_empty_series_produces_no_chart(monkeypatch):
    agent, calls = _agent(monkeypatch)
    out = asyncio.run(
        agent.create_visualization(
            NS(intermediate_results={}, building_id=None), "plot it", {"data": []}
        )
    )
    assert out["skipped"] == "no_data" and calls == []


# ── plotting code that invents its own data is refused ───────────────────────


def test_code_with_figures_that_are_not_in_the_data_is_flagged():
    code = "values = [83.4, 91.2, 77.9, 65.0]\nplt.bar(names, values)\nfigsize=(10, 6)"
    assert vh.invented_numbers(code, [{"floor": "Ground", "average": 21.4}]) == [
        "83.4",
        "91.2",
        "77.9",
        "65.0",
    ]


def test_code_that_plots_only_the_supplied_figures_is_fine():
    data = [{"floor": "Ground", "average": 21.4}, {"floor": "One", "average": 22.0}]
    code = "values = [21.4, 22.0, 21.4]\nplt.figure(figsize=(10, 6), dpi=100)\nx = [0, 1, 2, 3]"
    assert vh.invented_numbers(code, data) == []


def test_generated_code_that_invents_data_is_refused_before_it_runs(monkeypatch):
    agent, calls = _agent(monkeypatch)
    rows = [{"floor_name": "Ground", "average": 21.4}, {"floor_name": "One", "average": 22.0}]

    async def _determine(query, data=None):
        return "bar_chart"

    async def _generate(query, data, chart_type, filename):
        return "values = [83.4, 91.2, 77.9]\nprint('PLOT_BASE64: x')"

    agent._determine_chart_type = _determine
    agent._generate_viz_code = _generate
    out = asyncio.run(
        agent.create_visualization(NS(intermediate_results={}, building_id=None), "bar chart", rows)
    )
    assert out["skipped"] == "invented_data" and "media" not in out


# ── captions ─────────────────────────────────────────────────────────────────


def test_a_caption_without_computed_statistics_is_deterministic_and_states_no_figure(monkeypatch):
    seen = []

    async def fake_generate(prompt, **kw):
        seen.append(prompt)
        return "A dramatic surge across monitoring scenarios."

    monkeypatch.setattr(mod.llm_manager, "generate", fake_generate)
    agent = mod.VisualizationAgent.__new__(mod.VisualizationAgent)
    rows = [{"floor_name": "Ground", "average": 21.4}, {"floor_name": "One", "average": 22.0}]
    caption = asyncio.run(
        agent._generate_description(
            "chart the floors",
            "bar_chart",
            rows,
            state=NS(intermediate_results={}, building_id=None),
        )
    )
    assert caption == "A bar chart of the 2 value(s) retrieved."
    assert seen == [], "no statistics means nothing for a model to describe"


def test_a_caption_with_computed_statistics_still_uses_the_model(monkeypatch):
    seen = []

    async def fake_generate(prompt, **kw):
        seen.append(prompt)
        return "caption"

    monkeypatch.setattr(mod.llm_manager, "generate", fake_generate)
    agent = mod.VisualizationAgent.__new__(mod.VisualizationAgent)
    state = NS(
        intermediate_results={"sensor_metadata": {"u": {"label": "CO2", "unit": "ppm"}}},
        building_id=None,
    )
    asyncio.run(agent._generate_description("Plot CO2", "line_chart", SERIES, state=state))
    assert seen and "minimum 704" in seen[0]


# ── the note about a chart that was not drawn ────────────────────────────────

FIGURES = "The mean CO2 was 704 ppm and the maximum 916 ppm, with 21.5 °C in the room."
DECLINE = "I couldn't find anything about audible alerts in Example Building's records."


def _note(answer, *, wants=True, media=False, viz=None):
    return vh.chart_note(wants_chart=wants, has_media=media, viz_result=viz, answer=answer)


def test_no_chart_asked_means_no_note():
    assert _note(FIGURES, wants=False) == ""


def test_a_chart_that_exists_needs_no_note():
    assert _note(FIGURES, media=True) == ""


def test_a_failed_render_over_an_answer_with_figures_says_so_once_and_claims_nothing_more():
    note = _note(FIGURES, viz={"success": False, "error": "executor down"})
    assert "couldn't render the chart" in note
    assert "summarised" not in note
    assert "5.27" not in note, "no building's sensor id belongs in this text"
    assert _note(FIGURES + note) == "", "the note is never appended twice"


def test_no_data_to_plot_is_said_as_no_data_never_as_a_summary():
    note = _note(DECLINE, viz={"success": False, "skipped": "no_data"})
    assert "No chart was drawn" in note and "summarised" not in note
    # No viz result at all, over an answer with no figures: the same honest line.
    assert "No chart was drawn" in _note(DECLINE, viz=None)


def test_a_place_name_is_not_mistaken_for_figures():
    text = "I couldn't find Room 9.99 or Floor 12 in the building's records."
    assert not vh.answer_states_figures(text)
    assert "No chart was drawn" in _note(text)


def test_the_old_summary_claim_is_gone_from_the_workflow():
    import inspect

    from orchestrator.workflow import _orchestrator as orch

    src = inspect.getsource(orch.WorkflowOrchestrator._response_node)
    assert "I summarised the data above" not in src
    assert "plot sensor 5.27" not in src
    assert "chart_note(" in src
