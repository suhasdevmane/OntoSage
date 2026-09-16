"""BUG-606: narration presented one property as evidence about another, and contradicted itself.

Stakeholder run #3 and the 3x rehearsal:
  #40 "which plant items are running outside their normal schedule right now?" answered with
      items running BELOW their commissioned duty — a different property entirely;
  #55 invented "current AHU runtime is 0.65 HR" and a compliance verdict from it;
  #67 named Floor 4 the highest consumer at 3.56 kWh while listing Floor 3 at 3.59.
"""

import inspect

import pytest

pytestmark = pytest.mark.unit


def test_the_analytics_narration_forbids_property_substitution_and_contradiction():
    from orchestrator.agents import analytics_agent

    src = inspect.getsource(analytics_agent.AnalyticsAgent._format_analysis)
    assert "Reports ONLY the property that was measured" in src
    assert "duty is not an operating schedule" in src
    assert "must be the highest or" in src


def test_the_recommendation_narration_forbids_invented_figures_and_contradiction():
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    src = inspect.getsource(WorkflowOrchestrator._recommend_node)
    assert "Do not derive a runtime" in src
    assert "a duty is not a schedule" in src
    assert "the series you call highest must be the highest" in src.lower()
