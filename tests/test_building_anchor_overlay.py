# -*- coding: utf-8 -*-
"""CAVEAT-162: a standards band read in the wrong unit ranks nothing.

DEFAULT_ANCHORS are physical standards in standard units — CO2 in ppm. Real
hardware does not always publish those units: some CO2 sensors report an
air-quality index around 60-90, a correct reading on its own scale that sits
entirely below the 420 ppm "good" edge. Every room then scores exactly 1.0 and
the ranking silently degenerates to whatever other cue is present. The readings
were never wrong; the BAND was being read in the wrong unit.
"""

from __future__ import annotations

import textwrap

import pytest

from orchestrator.services.deliberation.cqir import Constraint, Direction, Hardness
from orchestrator.services.deliberation.scorer import (
    DEFAULT_ANCHORS,
    ScoreAnchor,
    _utility,
    load_anchors,
)

pytestmark = pytest.mark.unit

INDEX_READINGS = [62.0, 71.0, 85.0, 90.0]  # four rooms on a vendor index scale


def _c(modality="co2", direction=Direction.MINIMIZE):
    return Constraint(modality=modality, direction=direction, hardness=Hardness.SOFT)


def _overlay(tmp_path, monkeypatch, body: str):
    """Point the loader at a building whose overlay declares its own band."""
    overlay = tmp_path / "saturation_modalities.yaml"
    overlay.write_text(textwrap.dedent(body), encoding="utf-8")
    import orchestrator.services.deliberation.coverage_audit as ca

    monkeypatch.setattr(ca, "resolve_building_file", lambda bid, name: overlay)
    return overlay


class TestTheDegeneracyItself:
    def test_index_readings_all_score_perfect_against_the_ppm_band(self):
        """The bug: four different rooms, one score."""
        c = _c()
        scores = {_utility(c, v, DEFAULT_ANCHORS["co2"]) for v in INDEX_READINGS}
        assert scores == {1.0}, "expected the saturation this overlay exists to fix"

    def test_a_calibrated_band_separates_them(self):
        band = ScoreAnchor(60.0, 95.0, "index scale, vendor datasheet")
        c = _c()
        scores = [_utility(c, v, band) for v in INDEX_READINGS]
        assert len(set(scores)) == len(INDEX_READINGS), f"still tied: {scores}"
        assert scores[0] > scores[-1], "lower index should still rank better for minimize"


class TestTheOverlayIsLoaded:
    def test_a_declared_band_replaces_the_standard_one(self, tmp_path, monkeypatch):
        _overlay(
            tmp_path,
            monkeypatch,
            """
            modalities:
              co2:
                anchors: {lo: 60, hi: 95, citation: "index scale, vendor datasheet"}
            """,
        )
        a = load_anchors("bldgX")["co2"]
        assert (a.lo, a.hi) == (60.0, 95.0)
        assert a.citation == "index scale, vendor datasheet"

    def test_unnamed_modalities_keep_their_standard_band(self, tmp_path, monkeypatch):
        _overlay(
            tmp_path,
            monkeypatch,
            """
            modalities:
              co2:
                anchors: {lo: 60, hi: 95}
            """,
        )
        anchors = load_anchors("bldgX")
        assert anchors["temperature"] == DEFAULT_ANCHORS["temperature"]
        assert anchors["noise"] == DEFAULT_ANCHORS["noise"]

    def test_an_uncited_band_still_gets_a_citation(self, tmp_path, monkeypatch):
        """An uncited band in a dossier is exactly the unfalsifiable number to avoid."""
        _overlay(
            tmp_path,
            monkeypatch,
            """
            modalities:
              co2:
                anchors: {lo: 60, hi: 95}
            """,
        )
        assert "bldgX" in load_anchors("bldgX")["co2"].citation


class TestBadOverlaysAreIgnoredNotObeyed:
    @pytest.mark.parametrize(
        "block",
        [
            "anchors: {lo: 95, hi: 60}",  # inverted
            "anchors: {lo: 60}",  # incomplete
            "anchors: {lo: low, hi: high}",  # non-numeric
            "anchors: not-a-mapping",
        ],
    )
    def test_a_broken_band_keeps_the_standard_one(self, tmp_path, monkeypatch, block):
        _overlay(tmp_path, monkeypatch, f"modalities:\n  co2:\n    {block}\n")
        assert load_anchors("bldgX")["co2"] == DEFAULT_ANCHORS["co2"]


class TestNoBuildingMeansNoChange:
    def test_without_a_building_the_standards_stand(self):
        assert load_anchors(None) == DEFAULT_ANCHORS

    def test_a_building_with_no_overlay_is_unchanged(self, tmp_path, monkeypatch):
        import orchestrator.services.deliberation.coverage_audit as ca

        monkeypatch.setattr(ca, "resolve_building_file", lambda bid, name: None)
        assert load_anchors("bldgNoOverlay") == DEFAULT_ANCHORS
