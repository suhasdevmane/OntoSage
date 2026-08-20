"""
floor_plan_watcher.py — Async file watcher for auto-ingestion of floor plan files.

Watches /app/input/ for new or modified .pdf and .dwg files and triggers the
registry (which runs DWG + PDF pipelines and merges results) automatically.
Started as a background task in main.py lifespan.

Opt-out: set FLOOR_PLAN_WATCHER=false to disable (useful for CI/tests).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from shared.utils import get_logger

logger = get_logger(__name__)

_INPUT_DIR = Path("/app/input")
_DEBOUNCE_SECONDS = 3  # Wait this long after last change before ingesting
_WATCHED_SUFFIXES = {".pdf", ".dwg"}


async def watch_forever(
    input_dir: Optional[Path] = None,
    registry=None,
) -> None:
    """
    Watch input_dir for .pdf and .dwg file additions / modifications and reingest.

    When a PDF changes  → re-run PDF pipeline for that file, then re-merge with DWG.
    When a DWG changes  → re-run DWG pipeline for that file, then re-merge with PDF.
    Both use the FloorPlanRegistry so the merged manifest is always up-to-date.

    Runs forever as a background task.  Logs errors and continues — never
    raises so it doesn't take down the application.
    """
    from shared.config import settings

    if getattr(settings, "FLOOR_PLAN_WATCHER", "true").lower() == "false":
        logger.info("[watcher] Floor plan file watcher disabled (FLOOR_PLAN_WATCHER=false)")
        return

    try:
        from watchfiles import awatch
    except ImportError:
        logger.warning("[watcher] watchfiles not installed — auto-ingestion disabled")
        return

    watch_dir = input_dir or _INPUT_DIR
    if not watch_dir.exists():
        logger.warning(f"[watcher] Watch directory not found: {watch_dir} — watcher not started")
        return

    if registry is None:
        from orchestrator.services.floor_plan_registry import get_floor_plan_registry

        registry = get_floor_plan_registry()

    logger.info(f"[watcher] Watching {watch_dir} for PDF and DWG floor plan changes …")

    pending: dict = {}  # path → asyncio.Task for debounce

    async def _ingest_debounced(path: Path) -> None:
        """Wait for debounce period, then ingest via registry if no further changes."""
        await asyncio.sleep(_DEBOUNCE_SECONDS)
        pending.pop(str(path), None)
        try:
            logger.info(f"[watcher] Detected change: {path.name} — re-ingesting via registry …")
            suffix = path.suffix.lower()

            # Imports available to both PDF and DWG branches
            from orchestrator.services.dwg_pipeline import get_dwg_pipeline
            from orchestrator.services.floor_plan_pipeline import (
                get_floor_plan_pipeline,
            )

            if suffix == ".pdf":
                # Re-run PDF pipeline for this file only
                pdf_manifest = await get_floor_plan_pipeline().ingest_file(path)
                if pdf_manifest:
                    # Attempt merge with any existing DWG manifest for same floor
                    dwg_manifest = get_dwg_pipeline().load_manifest(
                        pdf_manifest.building_id, pdf_manifest.floor
                    )
                    merged = registry._merge(dwg_manifest, pdf_manifest)
                    if merged:
                        await registry._write_manifest(merged)
                    logger.info(
                        f"[watcher] Re-ingested {path.name} → "
                        f"{len(pdf_manifest.spaces)} spaces, "
                        f"schema={merged.schema_version if merged else '?'}"
                    )
                else:
                    logger.debug(f"[watcher] {path.name} skipped (not a floor-plan PDF)")

            elif suffix == ".dwg":
                # Re-run DWG pipeline for this file only
                dwg_manifest = await get_dwg_pipeline().ingest_file(path)
                if dwg_manifest:
                    # Attempt merge with any existing PDF manifest for same floor
                    pdf_manifest = get_floor_plan_pipeline().load_manifest(
                        dwg_manifest.building_id, dwg_manifest.floor
                    )
                    merged = registry._merge(dwg_manifest, pdf_manifest)
                    if merged:
                        await registry._write_manifest(merged)
                    logger.info(
                        f"[watcher] Re-ingested {path.name} → "
                        f"{len(dwg_manifest.spaces)} spaces, "
                        f"schema={merged.schema_version if merged else '?'}"
                    )
                else:
                    logger.debug(f"[watcher] {path.name} skipped (not a floor-plan DWG)")

        except Exception as e:
            logger.error(f"[watcher] Ingest failed for {path.name}: {e}", exc_info=True)

    try:
        async for changes in awatch(str(watch_dir)):
            for _change_type, str_path in changes:
                path = Path(str_path)
                if path.suffix.lower() not in _WATCHED_SUFFIXES:
                    continue
                # Cancel any existing debounce task for this file
                existing = pending.pop(str(path), None)
                if existing and not existing.done():
                    existing.cancel()
                # Schedule a new debounce task
                task = asyncio.create_task(_ingest_debounced(path))
                pending[str(path)] = task
    except asyncio.CancelledError:
        logger.info("[watcher] File watcher cancelled — shutting down")
    except Exception as e:
        logger.error(f"[watcher] Unexpected error in file watcher: {e}", exc_info=True)
