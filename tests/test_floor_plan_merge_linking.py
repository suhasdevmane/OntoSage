# -*- coding: utf-8 -*-
"""Ontology linking belongs to the merge, not to one of the two ingest paths.

Linking used to run only over PDF spaces, so a DWG space acquired an IRI purely
by being merged with a PDF space that already had one. A floor whose PDF carries
no text layer -- a scan, an image-only export, or a plan whose rooms are named
only in the CAD -- linked nothing at all. Worse, the /reingest endpoint had its
own private copy of the merged-set linking step while boot-time ingest did not,
so identical inputs produced a fully-linked floor or an unlinked one depending on
which path happened to run.
"""

import pytest

from orchestrator.services.floor_plan_registry import FloorPlanRegistry
from shared.models import FloorPlanManifest, RenderedImage, Space

pytestmark = pytest.mark.unit


def _space(zone_id, iri=None):
    return Space(
        id=f"b.{zone_id}",
        zone_id=zone_id,
        label=f"Room {zone_id}",
        type="office",
        source="dwg",
        confidence=0.9,
        ontology_iri=iri,
    )


def _manifest(spaces):
    return FloorPlanManifest(
        building_id="b",
        building_name="B",
        floor=0,
        floor_label="Floor 0",
        source_pdf="b0.pdf",
        source_sha256="0" * 64,
        generated_at="2026-08-20T00:00:00Z",
        rendered_image=RenderedImage(
            png_url="/f/b0.png",
            thumbnail_url="/f/b0_t.png",
            width_px=1000,
            height_px=800,
            dpi=150,
        ),
        pdf_url="/f/b0.pdf",
        schema_version="2.0",
        data_sources=["dwg"],
        spaces=spaces,
        ontology_links={s.zone_id: s.ontology_iri for s in spaces if s.ontology_iri},
    )


class _FakePdfPipeline:
    """Stands in for the real linker; records what it was asked to resolve."""

    def __init__(self, resolve):
        self._resolve, self.asked = resolve, None

    async def _link_ontology(self, spaces, building_id, floor):
        self.asked = [s.zone_id for s in spaces]
        for s in spaces:
            iri = self._resolve.get(s.zone_id)
            if iri:
                s.ontology_iri = iri
        return []


def _registry(resolve):
    reg = FloorPlanRegistry.__new__(FloorPlanRegistry)
    reg._pdf_pipeline = _FakePdfPipeline(resolve)
    return reg


@pytest.mark.asyncio
async def test_dwg_only_floor_gets_linked_without_any_pdf_text():
    reg = _registry({"0.01": "http://ex#Room0.01", "0.34": "http://ex#Room0.34"})
    m = _manifest([_space("0.01"), _space("0.34")])

    await reg.link_unlinked_spaces(m)

    assert [s.ontology_iri for s in m.spaces] == [
        "http://ex#Room0.01",
        "http://ex#Room0.34",
    ]


@pytest.mark.asyncio
async def test_ontology_links_map_is_rebuilt_not_left_stale():
    """The map is assembled at merge time; newly-linked spaces must appear in it."""
    reg = _registry({"0.01": "http://ex#Room0.01"})
    m = _manifest([_space("0.01"), _space("0.99", "http://ex#Room0.99")])
    assert m.ontology_links == {"0.99": "http://ex#Room0.99"}

    await reg.link_unlinked_spaces(m)

    assert m.ontology_links == {
        "0.01": "http://ex#Room0.01",
        "0.99": "http://ex#Room0.99",
    }


@pytest.mark.asyncio
async def test_already_linked_spaces_are_not_re_resolved():
    reg = _registry({})
    m = _manifest([_space("0.01", "http://ex#Room0.01")])

    await reg.link_unlinked_spaces(m)

    assert reg._pdf_pipeline.asked is None


@pytest.mark.asyncio
async def test_only_unlinked_spaces_are_sent_to_the_resolver():
    reg = _registry({"0.02": "http://ex#Room0.02"})
    m = _manifest([_space("0.01", "http://ex#Room0.01"), _space("0.02")])

    await reg.link_unlinked_spaces(m)

    assert reg._pdf_pipeline.asked == ["0.02"]


@pytest.mark.asyncio
async def test_a_linker_failure_leaves_the_manifest_usable():
    """A floor plan with unresolved IRIs is still a floor plan; losing it is worse."""

    class _Boom:
        async def _link_ontology(self, *_a, **_k):
            raise RuntimeError("graphdb down")

    reg = FloorPlanRegistry.__new__(FloorPlanRegistry)
    reg._pdf_pipeline = _Boom()
    m = _manifest([_space("0.01")])

    await reg.link_unlinked_spaces(m)

    assert len(m.spaces) == 1
    assert m.spaces[0].ontology_iri is None


def test_both_ingest_paths_call_the_shared_step():
    """Pin the invariant: neither path may grow a private copy again."""
    from pathlib import Path

    registry_src = Path("orchestrator/services/floor_plan_registry.py").read_text("utf-8")
    main_src = Path("orchestrator/main.py").read_text("utf-8")

    assert "await self.link_unlinked_spaces(result)" in registry_src, "boot ingest"
    assert "await registry.link_unlinked_spaces(merged)" in main_src, "reingest endpoint"
    assert "_link_ontology(unlinked" not in main_src, "reingest re-grew a private copy"
