# -*- coding: utf-8 -*-
"""V5-T10 / BUG-179: never mint a class name into Brick's namespace unchecked.

The provisioner used to emit ``a brick:<name>`` for whatever the modality config
said. Where Brick has no such class that invents a term inside someone else's
namespace — bldg2 accumulated 52 instances of ``brick:Sound_Level_Sensor``, which
a Brick validator rejects. A modality Brick does not cover must now name an
explicitly prefixed class declared in OntoSage's own TBox.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from orchestrator.services.deliberation.saturation import _qualify_class

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]
_CONFIG = _REPO / "config" / "saturation_modalities.yaml"
_OCBV = _REPO / "ontology" / "ontosage_schema.ttl"

#: Bare (unprefixed) names mean brick:<name>, so each one is a claim that Brick
#: defines that class. Verified against the loaded Brick TBox on 2026-08-18.
#: Adding a name here without checking is how BUG-179 happened — check first.
VERIFIED_BRICK_CLASSES = {
    "Zone_Air_Temperature_Sensor",
    "Relative_Humidity_Sensor",
    "CO2_Level_Sensor",
    "Occupancy_Count_Sensor",
    "Illuminance_Sensor",
    "Contact_Sensor",
    "PM2.5_Level_Sensor",
    "Electrical_Meter",
    "Water_Meter",
    "Availability_Status",
}


def _modalities():
    return yaml.safe_load(_CONFIG.read_text(encoding="utf-8"))["modalities"]


# ── the qualifier itself ─────────────────────────────────────────────────────


def test_bare_names_still_mean_brick():
    assert _qualify_class("Illuminance_Sensor") == "brick:Illuminance_Sensor"


def test_prefixed_names_are_emitted_verbatim():
    assert _qualify_class("ontosage:Sound_Level_Sensor") == "ontosage:Sound_Level_Sensor"


def test_a_full_iri_is_not_rewritten():
    iri = "<https://brickschema.org/schema/Brick#Sensor>"
    assert _qualify_class(iri) == iri


# ── the config ───────────────────────────────────────────────────────────────


def test_every_provisioned_class_is_verified_brick_or_explicitly_prefixed():
    unverified = []
    for name, spec in _modalities().items():
        cls = (spec.get("sat") or {}).get("brick_class")
        if not cls:
            continue
        if ":" in cls:
            continue  # explicitly namespaced — checked by the OCBV test below
        if cls not in VERIFIED_BRICK_CLASSES:
            unverified.append(f"{name} -> brick:{cls}")
    assert not unverified, (
        "these modalities would mint an UNVERIFIED class into Brick's namespace: "
        + ", ".join(unverified)
        + " — confirm Brick defines it and add it to VERIFIED_BRICK_CLASSES, or "
        "declare the class in ontology/ontosage_schema.ttl and prefix it."
    )


def test_ontosage_prefixed_classes_are_declared_in_the_ocbv_tbox():
    ttl = _OCBV.read_text(encoding="utf-8")
    for name, spec in _modalities().items():
        cls = (spec.get("sat") or {}).get("brick_class") or ""
        if cls.startswith("ontosage:"):
            assert f"{cls} a owl:Class" in ttl, (
                f"modality '{name}' provisions {cls}, which is not declared in "
                "ontology/ontosage_schema.ttl"
            )


def test_noise_is_provisioned_in_ontosage_namespace_not_brick():
    """Regression pin for BUG-179 — Brick defines no acoustic sensor class."""
    noise = _modalities()["noise"]
    assert noise["sat"]["brick_class"] == "ontosage:Sound_Level_Sensor"
    # matching must still find the legacy brick:-typed instances by local name
    assert "Sound_Level_Sensor" in noise["brick_classes"]


def test_every_modality_declares_what_the_provisioner_needs():
    for name, spec in _modalities().items():
        sat = spec.get("sat") or {}
        assert spec.get("brick_classes"), f"{name} has no brick_classes to match on"
        assert sat.get("table"), f"{name} has no narrow table"
        assert sat.get("brick_class"), f"{name} has no class to provision"


def test_scope_uses_the_vocabulary_the_auditor_actually_checks():
    """coverage_audit treats anything != 'room' as out of the per-room matrix.

    So a plausible-looking typo ('space', 'per_room') silently drops the modality
    from every room's coverage instead of failing — pin the vocabulary here.
    """
    for name, spec in _modalities().items():
        scope = str((spec.get("sat") or {}).get("scope", "room")).lower()
        assert scope in ("room", "floor", "building"), (
            f"modality '{name}' declares scope '{scope}'; the auditor only understands "
            "room / floor / building, and treats anything else as non-room"
        )
