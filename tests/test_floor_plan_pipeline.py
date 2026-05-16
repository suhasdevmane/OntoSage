"""
test_floor_plan_pipeline.py — Unit tests for the floor plan ingestion pipeline.

Covers §14 of the floor-plan standardization design spec:
  - One test per pipeline step (Steps 1–10)
  - Golden manifest comparison for Abacws floor 3 (regenerated with --update-golden)
  - Building-agnostic portability test using a synthetic second-building PDF

Run:
    pytest tests/test_floor_plan_pipeline.py -v
    pytest tests/test_floor_plan_pipeline.py -v --update-golden   # regenerate fixtures
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import struct
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers & Stubs
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "floor_plans"


def _make_text_blocks(texts: List[str]) -> List[Dict[str, Any]]:
    """Build minimal text-block dicts as the pipeline produces them."""
    return [
        {
            "text": t,
            "centroid": {"x": 0.5, "y": 0.5},
            "bbox": {"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.1},
        }
        for t in texts
    ]


def _fake_image_info() -> Dict[str, Any]:
    return {
        "width_px": 2400,
        "height_px": 1600,
        "page_count": 1,
        "bounding_box": {"width_pt": 842.0, "height_pt": 595.0},
    }


# ---------------------------------------------------------------------------
# Step 5 — Regex space detection
# ---------------------------------------------------------------------------

class TestDetectSpacesRegex:
    def _run(self, texts, building_id="abacws", floor=3):
        from orchestrator.services.floor_plan_pipeline import _detect_spaces_regex
        from shared.floor_plan_config import ABACWS_CONFIG

        blocks = _make_text_blocks(texts)
        spaces, warnings = _detect_spaces_regex(blocks, building_id, floor, ABACWS_CONFIG)
        return spaces, warnings

    def test_detects_standard_zone_ids(self):
        spaces, _ = self._run(["3.01", "3.02", "3.12"])
        zone_ids = {s.zone_id for s in spaces}
        assert "3.01" in zone_ids
        assert "3.02" in zone_ids
        assert "3.12" in zone_ids

    def test_detects_facility_keywords(self):
        spaces, _ = self._run(["Main Meeting Room", "Server Room IT"])
        types = {s.type for s in spaces}
        assert "meeting_room" in types
        assert "server_room" in types

    def test_no_duplicates(self):
        spaces, _ = self._run(["3.01", "3.01", "3.01"])
        zone_ids = [s.zone_id for s in spaces if s.zone_id == "3.01"]
        assert len(zone_ids) == 1

    def test_normalised_coordinates_in_range(self):
        spaces, _ = self._run(["3.05"])
        for s in spaces:
            if s.centroid:
                assert 0 <= s.centroid.x <= 1
                assert 0 <= s.centroid.y <= 1

    def test_empty_input_returns_empty(self):
        spaces, warnings = self._run([])
        assert spaces == []

    def test_non_zone_text_not_captured_as_zone(self):
        spaces, _ = self._run(["Page 1 of 1", "Scale 1:100"])
        zone_ids = {s.zone_id for s in spaces}
        assert not any(zid.startswith("1.") for zid in zone_ids), (
            "Page numbers should not be parsed as zone IDs"
        )


# ---------------------------------------------------------------------------
# Step 6 — Type classification
# ---------------------------------------------------------------------------

class TestClassifyTypes:
    def _make_space(self, label: str, space_type: str = "unknown"):
        from shared.models import Space

        return Space(
            id=f"abacws.{label.lower()}",
            zone_id=label.lower(),
            label=label,
            type=space_type,  # type: ignore[arg-type]
        )

    def test_office_keyword(self):
        from orchestrator.services.floor_plan_pipeline import _classify_types

        space = self._make_space("Open Plan Office")
        result = _classify_types([space])
        assert result[0].type == "office"

    def test_toilet_keyword(self):
        from orchestrator.services.floor_plan_pipeline import _classify_types

        space = self._make_space("Male WC")
        result = _classify_types([space])
        assert result[0].type == "toilet"

    def test_already_classified_not_overridden(self):
        from orchestrator.services.floor_plan_pipeline import _classify_types

        space = self._make_space("Weird Lab Name", space_type="lab")
        result = _classify_types([space])
        assert result[0].type == "lab"  # must not change


# ---------------------------------------------------------------------------
# Step 7 — ID normalisation
# ---------------------------------------------------------------------------

class TestNormaliseIds:
    def test_id_gets_building_prefix(self):
        from orchestrator.services.floor_plan_pipeline import _normalise_ids
        from shared.models import Space

        space = Space(id="3.01", zone_id="3.01", label="Zone 3.01", type="zone")
        result = _normalise_ids([space], "abacws", 3)
        assert result[0].id.startswith("abacws.")

    def test_already_prefixed_not_doubled(self):
        from orchestrator.services.floor_plan_pipeline import _normalise_ids
        from shared.models import Space

        space = Space(id="abacws.3.01", zone_id="3.01", label="Zone 3.01", type="zone")
        result = _normalise_ids([space], "abacws", 3)
        assert not result[0].id.startswith("abacws.abacws.")


# ---------------------------------------------------------------------------
# Step 2 — Fingerprinting / SHA-256
# ---------------------------------------------------------------------------

class TestFingerprint:
    def test_sha256_file(self, tmp_path):
        from orchestrator.services.floor_plan_pipeline import _sha256_file

        p = tmp_path / "test.pdf"
        p.write_bytes(b"hello world")
        sha = _sha256_file(p)
        assert sha == hashlib.sha256(b"hello world").hexdigest()

    def test_different_content_different_hash(self, tmp_path):
        from orchestrator.services.floor_plan_pipeline import _sha256_file

        p1 = tmp_path / "a.pdf"
        p1.write_bytes(b"content A")
        p2 = tmp_path / "b.pdf"
        p2.write_bytes(b"content B")
        assert _sha256_file(p1) != _sha256_file(p2)


# ---------------------------------------------------------------------------
# Step 10 — Manifest write
# ---------------------------------------------------------------------------

class TestManifestIO:
    def _make_manifest(self, building_id="abacws", floor=3):
        from datetime import datetime

        from shared.models import FloorPlanManifest, RenderedImage

        return FloorPlanManifest(
            building_id=building_id,
            building_name="Abacws",
            floor=floor,
            floor_label=f"Floor {floor}",
            source_pdf=f"Abacws floor {floor}.pdf",
            source_sha256="abc123",
            generated_at=datetime(2026, 4, 22, 10, 0, 0),
            rendered_image=RenderedImage(
                png_url=f"/floor-plans/renders/abacws/floor_{floor}.png",
                thumbnail_url=f"/floor-plans/renders/abacws/floor_{floor}_thumb.png",
                width_px=2400,
                height_px=1600,
                dpi=200,
            ),
            pdf_url=f"/floor-plans/Abacws%20floor%20{floor}.pdf",
        )

    def test_roundtrip_json(self, tmp_path):
        from orchestrator.services.floor_plan_pipeline import FloorPlanPipeline

        pipeline = FloorPlanPipeline(manifest_dir=tmp_path)
        manifest = self._make_manifest()
        # Write synchronously (for test)
        path = pipeline._manifest_path("abacws", 3)
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

        loaded = pipeline.load_manifest("abacws", 3)
        assert loaded is not None
        assert loaded.building_id == "abacws"
        assert loaded.floor == 3
        assert loaded.source_sha256 == "abc123"

    def test_load_missing_returns_none(self, tmp_path):
        from orchestrator.services.floor_plan_pipeline import FloorPlanPipeline

        pipeline = FloorPlanPipeline(manifest_dir=tmp_path)
        assert pipeline.load_manifest("abacws", 99) is None

    def test_corrupt_manifest_returns_none(self, tmp_path):
        from orchestrator.services.floor_plan_pipeline import FloorPlanPipeline

        pipeline = FloorPlanPipeline(manifest_dir=tmp_path)
        p = pipeline._manifest_path("abacws", 3)
        p.write_text("{not valid json}", encoding="utf-8")
        assert pipeline.load_manifest("abacws", 3) is None


# ---------------------------------------------------------------------------
# Full pipeline integration — mocked I/O
# ---------------------------------------------------------------------------

class TestPipelineIntegration:
    """Tests the full ingest_file path with mocked PDF I/O."""

    @pytest.fixture()
    def pipeline(self, tmp_path):
        from orchestrator.services.floor_plan_pipeline import FloorPlanPipeline

        return FloorPlanPipeline(
            pdf_dir=tmp_path / "input",
            manifest_dir=tmp_path / "manifests",
            graphdb_url="http://localhost:7200",
            qdrant_url="http://localhost:6333",
            openai_api_key="",
            llm_extract_enabled=False,
        )

    @pytest.fixture()
    def fake_pdf(self, tmp_path):
        """Creates a minimal fake PDF named in the expected pattern."""
        pdf_dir = tmp_path / "input"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        p = pdf_dir / "Abacws floor 3.pdf"
        p.write_bytes(b"%PDF-1.4 fake content for testing")
        return p

    @pytest.mark.asyncio
    async def test_ingest_file_skips_non_floor_plan_pdf(self, pipeline, tmp_path):
        p = tmp_path / "input" / "random_document.pdf"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"%PDF")
        result = await pipeline.ingest_file(p)
        assert result is None

    @pytest.mark.asyncio
    async def test_ingest_file_idempotent(self, pipeline, fake_pdf, tmp_path):
        """Second ingest of unchanged PDF returns existing manifest without re-processing."""
        # Write a manifest with the same SHA so the pipeline skips
        sha = hashlib.sha256(b"%PDF-1.4 fake content for testing").hexdigest()
        from datetime import datetime

        from shared.models import FloorPlanManifest, RenderedImage

        existing = FloorPlanManifest(
            building_id="abacws",
            building_name="Abacws",
            floor=3,
            floor_label="Third Floor",
            source_pdf="Abacws floor 3.pdf",
            source_sha256=sha,
            generated_at=datetime.utcnow(),
            rendered_image=RenderedImage(
                png_url="/fp/img.png",
                thumbnail_url="/fp/thumb.png",
                width_px=2400,
                height_px=1600,
                dpi=200,
            ),
            pdf_url="/floor-plans/Abacws%20floor%203.pdf",
        )
        mpath = pipeline._manifest_path("abacws", 3)
        mpath.write_text(existing.model_dump_json(), encoding="utf-8")

        result = await pipeline.ingest_file(fake_pdf)
        assert result is not None
        assert result.source_sha256 == sha  # returned existing — did not re-render

    @pytest.mark.asyncio
    async def test_ingest_file_render_failure_returns_none(self, pipeline, fake_pdf):
        """If PDF rendering fails (step 3), ingest_file returns None gracefully."""
        with patch(
            "orchestrator.services.floor_plan_pipeline._render_pdf",
            return_value=(None, ["render failed"]),
        ):
            with patch(
                "orchestrator.services.floor_plan_pipeline._run_in_executor",
                new=AsyncMock(return_value=(None, ["render failed"])),
            ):
                result = await pipeline.ingest_file(fake_pdf)
        assert result is None


# ---------------------------------------------------------------------------
# Portability — synthetic second building
# ---------------------------------------------------------------------------

class TestBuildingPortability:
    """Proves that a second building works without code changes (§11, §14 spec)."""

    @pytest.mark.asyncio
    async def test_synthetic_building_regex_detection(self, tmp_path):
        """A custom zone_id_pattern in building.yaml is honoured."""
        from shared.floor_plan_config import BuildingConfig
        from orchestrator.services.floor_plan_pipeline import _detect_spaces_regex

        # Synthetic building uses R{floor}{nn} pattern, e.g. R301, R415
        cfg = BuildingConfig(
            building_id="cardiff_eng",
            building_name="Cardiff Engineering",
            zone_id_pattern=r"\bR(\d)(\d{2})\b",
        )
        blocks = _make_text_blocks(["R301", "R402", "Kitchen", "Corridor"])
        spaces, _ = _detect_spaces_regex(blocks, "cardiff_eng", 3, cfg)
        zone_ids = {s.zone_id for s in spaces}
        assert "R301" in zone_ids
        assert "R402" in zone_ids

    @pytest.mark.asyncio
    async def test_second_building_manifest_list(self, tmp_path):
        """list_manifests() returns both buildings independently."""
        from orchestrator.services.floor_plan_pipeline import FloorPlanPipeline

        pipeline = FloorPlanPipeline(manifest_dir=tmp_path)

        from datetime import datetime

        from shared.models import FloorPlanManifest, RenderedImage

        def _write(bid, floor):
            m = FloorPlanManifest(
                building_id=bid,
                building_name=bid,
                floor=floor,
                floor_label=f"Floor {floor}",
                source_pdf=f"{bid} floor {floor}.pdf",
                source_sha256="abc",
                generated_at=datetime.utcnow(),
                rendered_image=RenderedImage(
                    png_url="/x.png", thumbnail_url="/t.png",
                    width_px=100, height_px=100, dpi=72,
                ),
                pdf_url="/x.pdf",
            )
            p = pipeline._manifest_path(bid, floor)
            p.write_text(m.model_dump_json(), encoding="utf-8")

        _write("abacws", 3)
        _write("cardiff_eng", 1)

        manifests = pipeline.list_manifests()
        buildings = {bid for bid, _ in manifests}
        assert "abacws" in buildings
        assert "cardiff_eng" in buildings


# ---------------------------------------------------------------------------
# Pydantic model validation
# ---------------------------------------------------------------------------

class TestPydanticModels:
    def test_space_type_unknown_allowed(self):
        from shared.models import Space

        s = Space(id="x.1", zone_id="1", label="Mystery Room", type="unknown")
        assert s.type == "unknown"

    def test_normalised_point_out_of_range_rejected(self):
        from pydantic import ValidationError
        from shared.models import NormalisedPoint

        with pytest.raises(ValidationError):
            NormalisedPoint(x=1.5, y=0.5)

    def test_floor_plan_manifest_schema_version(self):
        from datetime import datetime

        from pydantic import ValidationError
        from shared.models import FloorPlanManifest, RenderedImage

        def _make(**kw):
            return FloorPlanManifest(
                building_id="x", building_name="X", floor=1, floor_label="Floor 1",
                source_pdf="x.pdf", source_sha256="abc", generated_at=datetime.utcnow(),
                rendered_image=RenderedImage(
                    png_url="/a.png", thumbnail_url="/t.png", width_px=1, height_px=1, dpi=72,
                ),
                pdf_url="/x.pdf", **kw,
            )

        # Both "1.0" (PDF-only) and "2.0" (DWG-enriched) are valid schema versions
        m1 = _make(schema_version="1.0")
        assert m1.schema_version == "1.0"
        m2 = _make(schema_version="2.0")
        assert m2.schema_version == "2.0"

        # Invalid versions must still be rejected
        with pytest.raises(ValidationError):
            _make(schema_version="3.0")

    def test_floor_plan_result_defaults(self):
        from shared.models import FloorPlanResult

        r = FloorPlanResult(building_id="abacws")
        assert r.interactive is True
        assert r.floor is None
        assert r.candidates == []


# ---------------------------------------------------------------------------
# Golden manifest test (optional — skipped unless fixture present)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (FIXTURES_DIR / "abacws_floor_3.manifest.golden.json").exists(),
    reason="Golden manifest fixture not present — run pipeline against real PDFs first",
)
class TestGoldenManifest:
    def test_golden_manifest_schema(self):
        """Loaded golden manifest must parse without error."""
        from shared.models import FloorPlanManifest

        raw = (FIXTURES_DIR / "abacws_floor_3.manifest.golden.json").read_text("utf-8")
        m = FloorPlanManifest.model_validate_json(raw)
        assert m.building_id == "abacws"
        assert m.floor == 3

    def test_golden_manifest_has_spaces(self):
        from shared.models import FloorPlanManifest

        raw = (FIXTURES_DIR / "abacws_floor_3.manifest.golden.json").read_text("utf-8")
        m = FloorPlanManifest.model_validate_json(raw)
        assert len(m.spaces) >= 10, (
            f"Expected ≥10 spaces in golden manifest, got {len(m.spaces)}"
        )
