# -*- coding: utf-8 -*-
"""CAVEAT-207: one Brick class, two sensor populations, two scales.

bldg1 instruments CO2 twice. Its physical hardware is typed CO2_Level_Sensor and
labelled "CO2 Level Sensor installed-node 5.01", reading an index around 50-80;
the SATURATE provisioner adds CO2_Level_Sensor instances labelled
"Room 4.66 - Academic Office co2 (simulated) [ppm]" reading 400-2510 ppm. Class
alone cannot separate them, so both landed in the `co2` modality and were scored
against the same 420-1500 ppm band — every index sensor sits below 420, scores a
perfect 1.0, and the ranking degenerates to a tie.

`label_contains` could NAME one population but not EXCLUDE it from the other.
"""

from __future__ import annotations

import textwrap

import pytest

from orchestrator.services.deliberation.coverage_audit import (
    ModalitySpec,
    load_modalities,
)

pytestmark = pytest.mark.unit

HARDWARE = "CO2 Level Sensor installed-node 5.01"
PROVISIONED = "Room 4.66 - Academic Office co2 (simulated) [ppm]"


class TestExclusionSplitsOneClassIntoTwo:
    def test_the_ppm_modality_rejects_the_hardware_population(self):
        ppm = ModalitySpec(
            name="co2", brick_classes=["CO2_Level_Sensor"], label_excludes=["installed-node"]
        )
        assert ppm.matches("CO2_Level_Sensor", PROVISIONED) is True
        assert ppm.matches("CO2_Level_Sensor", HARDWARE) is False

    def test_the_index_modality_claims_only_the_hardware(self):
        idx = ModalitySpec(
            name="co2_index", brick_classes=["CO2_Level_Sensor"], label_contains=["installed-node"]
        )
        assert idx.matches("CO2_Level_Sensor", HARDWARE) is True
        assert idx.matches("CO2_Level_Sensor", PROVISIONED) is False

    def test_together_they_partition_the_class(self):
        """No sensor may fall in both, and none may fall in neither."""
        ppm = ModalitySpec("co2", ["CO2_Level_Sensor"], label_excludes=["installed-node"])
        idx = ModalitySpec("co2_index", ["CO2_Level_Sensor"], label_contains=["installed-node"])
        for label in (HARDWARE, PROVISIONED):
            claims = [m.name for m in (ppm, idx) if m.matches("CO2_Level_Sensor", label)]
            assert len(claims) == 1, f"{label!r} claimed by {claims}"


class TestExclusionWins:
    def test_a_sensor_named_by_both_lists_is_excluded(self):
        """Ambiguity must narrow a ranking, never silently corrupt one."""
        spec = ModalitySpec(
            "co2",
            ["CO2_Level_Sensor"],
            label_contains=["co2"],
            label_excludes=["installed-node"],
        )
        assert spec.matches("CO2_Level_Sensor", "co2 sensor installed-node 1.02") is False


class TestNothingElseChanges:
    def test_a_spec_without_exclusions_behaves_exactly_as_before(self):
        spec = ModalitySpec("co2", ["CO2_Level_Sensor"])
        assert spec.matches("CO2_Level_Sensor", HARDWARE) is True
        assert spec.matches("CO2_Level_Sensor", "anything at all") is True

    def test_class_mismatch_still_short_circuits(self):
        spec = ModalitySpec("co2", ["CO2_Level_Sensor"], label_excludes=["installed-node"])
        assert spec.matches("Temperature_Sensor", PROVISIONED) is False

    def test_label_contains_alone_is_unaffected(self):
        spec = ModalitySpec("door_contact", ["Contact_Sensor"], label_contains=["door"])
        assert spec.matches("Contact_Sensor", "front door contact") is True
        assert spec.matches("Contact_Sensor", "window contact") is False


class TestItLoadsFromConfig:
    def test_an_overlay_can_declare_exclusions(self, tmp_path, monkeypatch):
        overlay = tmp_path / "saturation_modalities.yaml"
        overlay.write_text(
            textwrap.dedent(
                """
                modalities:
                  co2:
                    brick_classes: [CO2_Level_Sensor]
                    label_excludes: ["installed-node"]
                  co2_index:
                    brick_classes: [CO2_Level_Sensor]
                    label_contains: ["installed-node"]
                    anchors: {lo: 40, hi: 95, citation: "vendor index scale"}
                """
            ),
            encoding="utf-8",
        )
        import orchestrator.services.deliberation.coverage_audit as ca

        monkeypatch.setattr(ca, "resolve_building_file", lambda bid, name: overlay)
        specs = {s.name: s for s in load_modalities("bldgX")}
        assert specs["co2"].label_excludes == ["installed-node"]
        assert specs["co2_index"].label_contains == ["installed-node"]
        assert specs["co2"].matches("CO2_Level_Sensor", HARDWARE) is False
        assert specs["co2_index"].matches("CO2_Level_Sensor", HARDWARE) is True
