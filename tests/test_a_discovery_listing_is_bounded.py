"""BUG-1461: the discovery fallback listed every label as its own kind -- 141,957 characters.

DEV D010 (v1, 2026-10-08), "Which facilities records and eligible telemetry can support the
competent authority's post-incident timeline?", reached discovery with no ontology census (the
census is keyed to the question's words, and a records question names no sensor class), so the
lane grouped by LABEL. On a building whose labels do not end in an identifier, nearly every
label is its own "kind", and the answer listed thousands of them. The fallback now shows the
largest groups and states the remainder as one line.
"""

import pytest

from orchestrator.workflow._orchestrator import WorkflowOrchestrator

pytestmark = pytest.mark.unit


def _orchestrator_with(labels):
    orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    orch.sensor_map = {
        f"http://example.org/b#p{i}": {"uri": f"http://example.org/b#p{i}", "label": label}
        for i, label in enumerate(labels)
    }
    return orch


def test_thousands_of_label_kinds_are_summarised_not_listed():
    labels = [f"Room {i} sensor installed-node" for i in range(3000)]  # every label its own kind
    out = _orchestrator_with(labels)._handle_sensor_discovery(None, None, census=None)
    cap = WorkflowOrchestrator.DISCOVERY_MAX_KINDS
    assert out.count("\n- **") == cap
    assert f"{3000 - cap} more sensors under {3000 - cap} other labels" in out
    assert len(out) < 5000


def test_a_listing_within_the_cap_is_unchanged():
    # 30 points whose labels end in an identifier: one kind of 30, nothing hidden.
    orch = _orchestrator_with([f"Zone Air Temperature Sensor {i}" for i in range(30)])
    out = orch._handle_sensor_discovery(None, None, census=None)
    assert "more sensors under" not in out
    assert "**Zone Air Temperature Sensor**: 30 sensors" in out
