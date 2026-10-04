# -*- coding: utf-8 -*-
"""E1 (QA-trial plan, 2026-10-02): a conflict the CURRENT turn's record carries must reach
the answer that contains it, not only a later provenance follow-up.

This turned out to need no new wiring: D11's inline panel already renders
`record['conflicts']` (answer_provenance.render), and D18's "suppress an empty panel"
guard cannot suppress one that has a conflict in it, because the conflicts line is what
makes `len(lines) > 2` in the first place. The two rows compose for free.
"""
import pytest

from orchestrator.services.answer_provenance import render

pytestmark = pytest.mark.unit


class TestAConflictOnTheCurrentTurnIsDisclosedInline:
    def test_a_conflict_alone_is_enough_to_produce_a_panel(self):
        """A record with NOTHING else -- no status, no operation, no sources -- but a
        conflict must still render, proving D18's empty-guard cannot eat it."""
        rec = {"conflicts": ["booking says occupied, the room sensor reads empty"]}
        text = render(rec, inline=True)
        assert text
        assert "booking says occupied" in text

    def test_the_conflict_line_is_present_on_an_ordinary_figure_bearing_answer_too(self):
        rec = {
            "status": "observed",
            "operation": "observation",
            "sources": [{"source_id": "u1", "kind": "sensor"}],
            "conflicts": ["sensor says empty, booking says occupied"],
        }
        text = render(rec, inline=True)
        assert "Disagreements between sources" in text
        assert "sensor says empty, booking says occupied" in text

    def test_no_conflict_means_no_disagreement_line(self):
        rec = {"status": "observed", "operation": "observation", "sources": [{"source_id": "u1"}]}
        text = render(rec, inline=True)
        assert "Disagreements between sources" not in text
