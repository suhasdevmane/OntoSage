"""
floor_plan_watcher.py — Async file watcher for auto-ingestion of floor plan PDFs.

Watches /app/input/ for new or modified .pdf files and triggers the pipeline
automatically.  Started as a background task in main.py lifespan.

Opt-out: set FLOOR_PLAN_WATCHER=false to disable (useful for CI/tests).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from shared.utils import get_logger

logger = get_logger(__name__)

_PDF_DIR = Path("/app/input")
_DEBOUNCE_SECONDS = 3  # Wait this long after last change before ingesting


async def watch_forever(
    pdf_dir: Optional[Path] = None,
    pipeline=None,
) -> None:
    """
    Watch pdf_dir for .pdf file additions / modifications and reingest.

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

    watch_dir = pdf_dir or _PDF_DIR
    if not watch_dir.exists():
        logger.warning(f"[watcher] Watch directory not found: {watch_dir} — watcher not started")
        return

    if pipeline is None:
        from orchestrator.services.floor_plan_pipeline import get_floor_plan_pipeline

        pipeline = get_floor_plan_pipeline()

    logger.info(f"[watcher] Watching {watch_dir} for floor plan PDF changes …")

    pending: dict = {}  # path → asyncio.Task for debounce

    async def _ingest_debounced(path: Path) -> None:
        """Wait for debounce period, then ingest if no further changes."""
        await asyncio.sleep(_DEBOUNCE_SECONDS)
        pending.pop(str(path), None)
        try:
            logger.info(f"[watcher] Detected change: {path.name} — re-ingesting …")
            manifest = await pipeline.ingest_file(path)
            if manifest:
                logger.info(
                    f"[watcher] Re-ingested {path.name} → "
                    f"{len(manifest.spaces)} spaces, {len(manifest.warnings)} warnings"
                )
            else:
                logger.debug(f"[watcher] {path.name} skipped (not a floor-plan PDF)")
        except Exception as e:
            logger.error(f"[watcher] Ingest failed for {path.name}: {e}", exc_info=True)

    try:
        async for changes in awatch(str(watch_dir)):
            for _change_type, str_path in changes:
                path = Path(str_path)
                if path.suffix.lower() != ".pdf":
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
