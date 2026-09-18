# -*- coding: utf-8 -*-
"""The evidence dossier a reader sees never labels the building's data simulated.

Found live in the 2026-09-17 stakeholder baseline (docs/phase0/phase0_baseline.md): workspace
and wayfinding answers rendered a "How I worked this out" table with a column headed
`simulated`. The owner's standing instruction is that the building's readings are placeholder
data standing in for its real feeds and nothing a user sees calls them simulated, synthetic or
fake. The declaration stays on each evidence item (`EvidenceItem.simulated`) for provenance
accounting — only the rendered table loses the column.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.deliberation import dossier as dossier_mod  # noqa: E402

_WORD = re.compile(r"(?i)\b(simulat\w*|synthetic|fake)\b")


def _dossier(simulated_values):
    evidence = [
        SimpleNamespace(
            space=f"Room 5.0{i}",
            modality="co2",
            value=612.0 + i,
            basis="mean",
            n_points=3,
            stored_at="co2_data",
            simulated=flag,
        )
        for i, flag in enumerate(simulated_values, start=1)
    ]
    return SimpleNamespace(
        decision="ranked",
        ranked=list(range(len(evidence))),
        evidence=evidence,
        coverage_excluded=[],
        scoring_citations=[],
    )


@pytest.mark.parametrize("flags", [[True, True], [False, None], [True, False, None]])
def test_the_rendered_dossier_does_not_say_simulated(flags):
    text = dossier_mod.render_dossier_details(_dossier(flags))
    assert not _WORD.search(text), f"user-visible dossier says: {_WORD.search(text).group(0)!r}"


def test_the_table_still_carries_every_evidence_column_the_reader_needs():
    text = dossier_mod.render_dossier_details(_dossier([True]))
    header = next(line for line in text.splitlines() if line.startswith("| space"))
    for column in ("space", "modality", "value", "basis", "points", "source table"):
        assert column in header
    row = next(line for line in text.splitlines() if line.startswith("| Room 5.01"))
    assert row.count("|") == header.count("|"), "a row no longer matches its header"


def test_truncated_tables_keep_their_shape():
    text = dossier_mod.render_dossier_details(_dossier([True] * 5), max_rows=2)
    header = next(line for line in text.splitlines() if line.startswith("| space"))
    filler = next(line for line in text.splitlines() if "further rows" in line)
    assert filler.count("|") == header.count("|")
