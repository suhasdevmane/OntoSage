"""D5 — evidence is always on: the read-back does not depend on DATASOURCE_TOGGLES_ENABLED.

The flag gates the toggleable data-source feature. Measured 2026-10-06 it ALSO gates the
per-source provenance chips appended in `_response_node`; those are deliberately left gated
here (an owner call, recorded in the flag's description), so this file pins the evidence
path itself and not the chips.
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.services import answer_provenance
from orchestrator.services.answer_provenance import render

pytestmark = pytest.mark.unit

RECORD = {
    "status": "observed",
    "operation": "observation",
    "sources": [{"source_id": "sensor-uuid-1", "kind": "sensor", "owner": "BMS"}],
    "latest_evidence_at": "2026-10-06T09:00:00",
    "retrieved_at": "2026-10-06T09:01:00",
    "gates_applied": ["freshness"],
}


def test_flag_default_is_false_and_its_description_says_evidence_is_not_gated():
    from shared.config import Settings

    field = Settings.model_fields["DATASOURCE_TOGGLES_ENABLED"]
    assert field.default is False
    assert "EVIDENCE IS NOT GATED BY THIS FLAG" in field.description


def test_read_back_renders_with_the_flag_false(monkeypatch):
    from shared.config import settings

    monkeypatch.setattr(settings, "DATASOURCE_TOGGLES_ENABLED", False)
    text = render(RECORD, question="how do you know that?")
    assert text is not None
    assert "How that answer was arrived at" in text
    # The source is shown as its readable label (D15), which title-cases the id.
    assert "sensor-uuid-1" in text.lower()


def test_provenance_module_never_reads_the_datasource_flag():
    source = inspect.getsource(answer_provenance)
    assert "DATASOURCE_TOGGLES_ENABLED" not in source


def test_evidence_endpoint_never_reads_the_datasource_flag():
    from orchestrator import main

    assert "DATASOURCE_TOGGLES_ENABLED" not in inspect.getsource(main.get_turn_evidence)
