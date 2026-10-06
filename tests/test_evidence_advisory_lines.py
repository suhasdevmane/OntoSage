"""E7 — each fired advisory gate is one line in the evidence read-back, with its reason.

An advisory failure changes no answer, so the read-back is the only place it is visible. A
single comma-joined line named the gates but not what each objected to.
"""

from __future__ import annotations

import pytest

from orchestrator.services.answer_provenance import render

pytestmark = pytest.mark.unit


def _record(advisory):
    return {
        "status": "observed",
        "operation": "observation",
        "sources": [{"source_id": "sensor-1", "kind": "sensor"}],
        "gates_applied": ["freshness"],
        "gates_advisory": advisory,
    }


def test_each_advisory_gate_gets_its_own_line_with_its_reason():
    text = render(
        _record(
            [
                "freshness: the newest reading is 41 hours old",
                "sampling_density: 3 of 96 expected samples present",
            ]
        )
    )
    lines = text.splitlines()
    assert "    - `freshness` — the newest reading is 41 hours old" in lines
    assert "    - `sampling_density` — 3 of 96 expected samples present" in lines


def test_a_bare_gate_name_renders_without_a_dangling_separator():
    text = render(_record(["freshness"]))
    assert "    - `freshness`" in text.splitlines()
    assert " — " not in text.split("advisory mode")[-1].splitlines()[1]


def test_no_advisory_section_when_nothing_flagged():
    assert "advisory mode" not in render(_record([]))


@pytest.mark.parametrize("count", [1, 3])
def test_one_line_per_gate_up_to_six(count):
    text = render(_record([f"gate_{i}: reason {i}" for i in range(count)]))
    assert sum(1 for ln in text.splitlines() if ln.startswith("    - `gate_")) == count
