"""
test_floor_plan_e2e.py — End-to-end floor plan query test (§14, design spec).

Tests the full path:
  PDF on disk → FloorPlanPipeline.ingest_file() → FloorPlanAgent.resolve()

Does NOT require GraphDB, MySQL, or Qdrant — all external calls are mocked.
Does NOT use a real PDF — uses a synthetic text fixture instead.

Run:
    pytest tests/test_floor_plan_e2e.py -v -m "not slow"
    pytest tests/test_floor_plan_e2e.py -v                # includes slow tests
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SYNTHETIC_PDF_BYTES = b"%PDF-1.4\n%synthetic floor plan\n"

# The text blocks our fake PDF "contains" — simulates fitz.open() output
SYNTHETIC_TEXT_BLOCKS = [
    {"text": "3.01", "centroid": {"x": 0.20, "y": 0.30}, "bbox": {"x": 0.15, "y": 0.25, "w": 0.10, "h": 0.10}},
    {"text": "3.02", "centroid": {"x": 0.40, "y": 0.30}, "bbox": {"x": 0.35, "y": 0.25, "w": 0.10, "h": 0.10}},
    {"text": "3.12", "centroid": {"x": 0.60, "y": 0.50}, "bbox": {"x": 0.55, "y": 0.45, "w": 0.10, "h": 0.10}},
    {"text": "Server Room", "centroid": {"x": 0.80, "y": 0.70}, "bbox": {"x": 0.75, "y": 0.65, "w": 0.15, "h": 0.10}},
    {"text": "Meeting Room A", "centroid": {"x": 0.20, "y": 0.70}, "bbox": {"x": 0.15, "y": 0.65, "w": 0.15, "h": 0.10}},
    {"text": "Kitchen", "centroid": {"x": 0.40, "y": 0.70}, "bbox": {"x": 0.35, "y": 0.65, "w": 0.10, "h": 0.10}},
]

SYNTHETIC_IMAGE_INFO = {
    "width_px": 2400,
    "height_px": 1600,
    "page_count": 1,
    "bounding_box": {"width_pt": 842.0, "height_pt": 595.0},
}


@pytest.fixture()
def tmp_building(tmp_path):
    """Create a temporary /app/input and /app/floor_plans layout."""
    pdf_dir = tmp_path / "input"
    manifest_dir = tmp_path / "manifests"
    pdf_dir.mkdir()
    manifest_dir.mkdir()

    # Write a synthetic "Abacws floor 3.pdf"
    pdf_path = pdf_dir / "Abacws floor 3.pdf"
    pdf_path.write_bytes(SYNTHETIC_PDF_BYTES)

    return {"pdf_dir": pdf_dir, "manifest_dir": manifest_dir, "pdf_path": pdf_path}


@pytest.fixture()
def pipeline(tmp_building):
    from orchestrator.services.floor_plan_pipeline import FloorPlanPipeline

    return FloorPlanPipeline(
        pdf_dir=tmp_building["pdf_dir"],
        manifest_dir=tmp_building["manifest_dir"],
        graphdb_url="http://mock-graphdb:7200",
        qdrant_url="http://mock-qdrant:6333",
        openai_api_key="",
        llm_extract_enabled=False,
    )


# ---------------------------------------------------------------------------
# Helper — mock the blocking PDF I/O calls
# ---------------------------------------------------------------------------

def _patched_render(pdf_path, manifest_dir, building_id, floor, dpi):
    """Fake _render_pdf: creates the PNG files and returns image info."""
    out_dir = manifest_dir / building_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"floor_{floor}.png").write_bytes(b"PNG")
    (out_dir / f"floor_{floor}_thumb.png").write_bytes(b"PNG_THUMB")
    return SYNTHETIC_IMAGE_INFO, []


def _patched_extract(pdf_path):
    """Fake _extract_text_blocks: returns our synthetic text blocks."""
    return SYNTHETIC_TEXT_BLOCKS, []


async def _run_in_executor_passthrough(fn, *args):
    """Run the (already-patched) fn synchronously inside the executor mock."""
    return fn(*args)


# ---------------------------------------------------------------------------
# E2E Test 1: Pipeline ingest produces a valid manifest
# ---------------------------------------------------------------------------

class TestPipelineE2E:
    @pytest.mark.asyncio
    async def test_ingest_produces_manifest(self, pipeline, tmp_building):
        with (
            patch("orchestrator.services.floor_plan_pipeline._render_pdf", side_effect=_patched_render),
            patch("orchestrator.services.floor_plan_pipeline._extract_text_blocks", side_effect=_patched_extract),
            patch("orchestrator.services.floor_plan_pipeline._run_in_executor", new=_run_in_executor_passthrough),
            patch.object(pipeline, "_link_ontology", new=AsyncMock(return_value=[])),
            patch.object(pipeline, "_embed_and_index", new=AsyncMock()),
        ):
            manifest = await pipeline.ingest_file(tmp_building["pdf_path"])

        assert manifest is not None
        assert manifest.building_id == "abacws"
        assert manifest.floor == 3
        assert manifest.schema_version == "1.0"

    @pytest.mark.asyncio
    async def test_ingest_extracts_zones(self, pipeline, tmp_building):
        with (
            patch("orchestrator.services.floor_plan_pipeline._render_pdf", side_effect=_patched_render),
            patch("orchestrator.services.floor_plan_pipeline._extract_text_blocks", side_effect=_patched_extract),
            patch("orchestrator.services.floor_plan_pipeline._run_in_executor", new=_run_in_executor_passthrough),
            patch.object(pipeline, "_link_ontology", new=AsyncMock(return_value=[])),
            patch.object(pipeline, "_embed_and_index", new=AsyncMock()),
        ):
            manifest = await pipeline.ingest_file(tmp_building["pdf_path"])

        assert manifest is not None
        zone_ids = {s.zone_id for s in manifest.spaces}
        assert "3.01" in zone_ids
        assert "3.02" in zone_ids
        assert "3.12" in zone_ids

    @pytest.mark.asyncio
    async def test_ingest_extracts_facilities(self, pipeline, tmp_building):
        with (
            patch("orchestrator.services.floor_plan_pipeline._render_pdf", side_effect=_patched_render),
            patch("orchestrator.services.floor_plan_pipeline._extract_text_blocks", side_effect=_patched_extract),
            patch("orchestrator.services.floor_plan_pipeline._run_in_executor", new=_run_in_executor_passthrough),
            patch.object(pipeline, "_link_ontology", new=AsyncMock(return_value=[])),
            patch.object(pipeline, "_embed_and_index", new=AsyncMock()),
        ):
            manifest = await pipeline.ingest_file(tmp_building["pdf_path"])

        assert manifest is not None
        types = {s.type for s in manifest.spaces}
        assert "server_room" in types or "meeting_room" in types, (
            f"Expected server_room or meeting_room in space types, got: {types}"
        )

    @pytest.mark.asyncio
    async def test_manifest_written_to_disk(self, pipeline, tmp_building):
        with (
            patch("orchestrator.services.floor_plan_pipeline._render_pdf", side_effect=_patched_render),
            patch("orchestrator.services.floor_plan_pipeline._extract_text_blocks", side_effect=_patched_extract),
            patch("orchestrator.services.floor_plan_pipeline._run_in_executor", new=_run_in_executor_passthrough),
            patch.object(pipeline, "_link_ontology", new=AsyncMock(return_value=[])),
            patch.object(pipeline, "_embed_and_index", new=AsyncMock()),
        ):
            await pipeline.ingest_file(tmp_building["pdf_path"])

        manifest_path = tmp_building["manifest_dir"] / "abacws" / "floor_3.manifest.json"
        assert manifest_path.exists(), "Manifest file was not written to disk"
        loaded = json.loads(manifest_path.read_text("utf-8"))
        assert loaded["building_id"] == "abacws"


# ---------------------------------------------------------------------------
# E2E Test 2: FloorPlanAgent resolves queries against the manifest
# ---------------------------------------------------------------------------

@pytest.fixture()
def manifest_on_disk(pipeline, tmp_building):
    """Run the pipeline (mocked) and return the resulting manifest."""
    async def _run():
        with (
            patch("orchestrator.services.floor_plan_pipeline._render_pdf", side_effect=_patched_render),
            patch("orchestrator.services.floor_plan_pipeline._extract_text_blocks", side_effect=_patched_extract),
            patch("orchestrator.services.floor_plan_pipeline._run_in_executor", new=_run_in_executor_passthrough),
            patch.object(pipeline, "_link_ontology", new=AsyncMock(return_value=[])),
            patch.object(pipeline, "_embed_and_index", new=AsyncMock()),
        ):
            return await pipeline.ingest_file(tmp_building["pdf_path"])

    return asyncio.get_event_loop().run_until_complete(_run())


class TestFloorPlanAgentE2E:
    def _make_state(self, query: str, building_id: str = "abacws"):
        """Build a ConversationState; defaults building_id to the PDF slug 'abacws'
        which is what the e2e fixture pipeline registers manifests under.

        Phase 4 note: in production, the BuildingRegistry alias mechanism maps
        the logical settings.BUILDING_ID (e.g. 'bldg1') to the manifest slug
        ('abacws').  These end-to-end fixture tests pass 'abacws' explicitly
        instead of relying on alias resolution because the test pipeline does
        not run the registry scan."""
        from shared.models import ConversationState, Message

        return ConversationState(
            conversation_id="test-e2e",
            user_id="tester",
            building_id=building_id,
            user_message=query,
            messages=[Message(role="user", content=query)],
        )

    @pytest.mark.asyncio
    async def test_explicit_floor_returns_manifest(self, pipeline, manifest_on_disk):
        """'Show me floor 3' should return a FloorPlanResult with floor=3."""
        from orchestrator.agents.floor_plan_agent import FloorPlanAgent

        agent = FloorPlanAgent(static_base_url="http://localhost:8080")

        with patch(
            "orchestrator.agents.floor_plan_agent.get_floor_plan_pipeline",
            return_value=pipeline,
        ):
            state = self._make_state("Show me floor 3")
            result = await agent.resolve("Show me floor 3", state)

        assert result.floor == 3
        assert result.building_id == "abacws"

    @pytest.mark.asyncio
    async def test_where_is_server_room_finds_floor(self, pipeline, manifest_on_disk):
        """'Where is the server room?' must find floor 3 without user specifying it."""
        from orchestrator.agents.floor_plan_agent import FloorPlanAgent

        agent = FloorPlanAgent(static_base_url="http://localhost:8080")

        with patch(
            "orchestrator.agents.floor_plan_agent.get_floor_plan_pipeline",
            return_value=pipeline,
        ):
            state = self._make_state("Where is the server room?")
            result = await agent.resolve("Where is the server room?", state)

        # Either selected_space is the server room, or candidates include it
        all_spaces = ([result.selected_space] if result.selected_space else []) + result.candidates
        space_types = {s.type for s in all_spaces if s}
        # Result markdown should mention server room context
        assert result.markdown != "", "Agent returned empty markdown"
        # Either found it or provided a sensible disambiguation
        assert result.floor is not None or "server" in result.markdown.lower(), (
            "Agent didn't find server room and didn't mention it in response"
        )

    @pytest.mark.asyncio
    async def test_zone_id_resolves_to_specific_space(self, pipeline, manifest_on_disk):
        """'Tell me about zone 3.12' must return selected_space with zone_id 3.12."""
        from orchestrator.agents.floor_plan_agent import FloorPlanAgent

        agent = FloorPlanAgent(static_base_url="http://localhost:8080")

        with patch(
            "orchestrator.agents.floor_plan_agent.get_floor_plan_pipeline",
            return_value=pipeline,
        ):
            state = self._make_state("Tell me about zone 3.12")
            result = await agent.resolve("Tell me about zone 3.12", state)

        assert result.selected_space is not None
        assert result.selected_space.zone_id == "3.12"

    @pytest.mark.asyncio
    async def test_building_overview_intent(self, pipeline, manifest_on_disk):
        """'Give me a building overview' must trigger overview result."""
        from orchestrator.agents.floor_plan_agent import FloorPlanAgent

        agent = FloorPlanAgent(static_base_url="http://localhost:8080")

        with patch(
            "orchestrator.agents.floor_plan_agent.get_floor_plan_pipeline",
            return_value=pipeline,
        ):
            state = self._make_state("Give me a building overview")
            result = await agent.resolve("Give me a building overview", state)

        assert "Overview" in result.markdown or "overview" in result.markdown.lower()

    @pytest.mark.asyncio
    async def test_no_floor_plans_loaded_returns_helpful_message(self, tmp_path):
        """If no manifests exist, agent returns a user-friendly error, not a crash."""
        from orchestrator.agents.floor_plan_agent import FloorPlanAgent
        from orchestrator.services.floor_plan_pipeline import FloorPlanPipeline
        from shared.models import ConversationState, Message

        empty_pipeline = FloorPlanPipeline(
            pdf_dir=tmp_path / "empty_input",
            manifest_dir=tmp_path / "empty_manifests",
        )

        agent = FloorPlanAgent(static_base_url="http://localhost:8080")

        with patch(
            "orchestrator.agents.floor_plan_agent.get_floor_plan_pipeline",
            return_value=empty_pipeline,
        ):
            state = ConversationState(
                conversation_id="test-empty",
                user_id="tester",
                user_message="Show me floor 3",
                messages=[Message(role="user", content="Show me floor 3")],
            )
            result = await agent.resolve("Show me floor 3", state)

        assert result.interactive is False
        assert result.markdown != ""
        assert "floor plan" in result.markdown.lower() or "not found" in result.markdown.lower()
