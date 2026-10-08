"""Automatic encrypted backups of the active building's user state, run inside the orchestrator.

Triggered by answers, not by a clock: every answer route calls ``request()`` after it has
persisted the turn. Requests are COALESCED: at most one backup run starts per
``min_interval_s``, and a request that arrives during an interval is run once the interval
ends. A busy building therefore produces one archive every interval, not one per answer.

What one archive holds (the orchestrator container's view; the host script is separate):
  db/postgres/<table>.jsonl   every public table of the Postgres user-data database, one JSON
                              row per line (users, conversations, messages, turn_memory,
                              reports, tickets, audit). A logical export: the schema is
                              recreated by PostgresManager._init_schema, not stored.
  config/input/**             the active building's input/ tree (TTL, manifests, documents)
  config/env                  the active .env. It is ENCRYPTED inside the archive like everything
                              else (owner decision, 2026-10-06). The archive passphrase is itself
                              in that .env, so this member adds nothing a holder of the .env does
                              not already have; it is kept so that a restore has the whole config.

Not included, by design: the sensor store (MySQL sensordb, ~9 GB), Redis, Qdrant, Ollama,
Open WebUI / Mongo transcripts, and the GraphDB raw store (the TTL files in input/ rebuild it).

Failure never reaches the answer path: every error is logged at ERROR with its reason and
counted. The archive is written under ``<name>.partial`` and renamed only when complete.

The passphrase comes from ``BACKUP_PASSPHRASE`` in the environment only. Nothing here reads a
credential store.
"""

import asyncio
import datetime as dt
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from orchestrator.services.backup_format import MIN_PASSPHRASE_LENGTH, write_archive
from shared.utils import get_logger

logger = get_logger(__name__)

FORMAT_NAME = "ontosage-encrypted-backup"
FORMAT_VERSION = 1
ARCHIVE_PREFIX = "ontosage-auto-"
ARCHIVE_SUFFIX = ".enc"
#: Pause between a request and its run, so the answer's own writes (the assistant message is
#: saved after the turn-memory hook) land before the dump reads the database.
SETTLE_S = 20.0
EXCLUDED_BY_DESIGN = [
    "sensor data (MySQL sensordb)",
    "redis (cache and sessions)",
    "qdrant (vector index)",
    "ollama (model weights)",
    "open-webui and mongo (chat transcripts)",
    "graphdb raw store (rebuilt from input/*.ttl)",
]

Member = Tuple[str, Path]


class BackupError(Exception):
    """A run could not produce an archive. The reason is logged; nothing is raised past run."""


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


async def export_postgres(pool: Any, staging: Path) -> List[Member]:
    """Write every public table of the user-data database as JSON lines under staging.

    One REPEATABLE READ transaction, so the tables describe the same instant. The tables are
    discovered from pg_tables rather than listed here, so a table added later is backed up
    without a code change.
    """
    members: List[Member] = []
    async with pool.acquire() as conn:
        async with conn.transaction(isolation="repeatable_read"):
            names = [
                rec["tablename"]
                for rec in await conn.fetch(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1"
                )
            ]
            for index, name in enumerate(names):
                quoted = '"' + name.replace('"', '""') + '"'
                # The staging file is named by position: a table name is not always a legal
                # filename (a quote is legal in Postgres and illegal on Windows).
                path = staging / f"table_{index:03d}.jsonl"
                safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
                # Rows are written as they arrive, so one large table is never held in memory.
                # The write is small, synchronous and local; acceptable on the event loop.
                with open(path, "w", encoding="utf-8") as fh:
                    async for rec in conn.cursor(
                        f"SELECT row_to_json(t)::text AS j FROM {quoted} AS t"
                    ):
                        fh.write(rec["j"] + "\n")
                # The position prefix keeps member names unique even if two names sanitise alike.
                members.append((f"db/postgres/{index:03d}_{safe}.jsonl", path))
    return members


def config_members(app_root: Path) -> Tuple[List[Member], List[dict]]:
    """The building's input/ tree and .env, or a skipped note for each that is absent."""
    members: List[Member] = []
    skipped: List[dict] = []
    input_dir = app_root / "input"
    if input_dir.is_dir():
        for path in sorted(p for p in input_dir.rglob("*") if p.is_file()):
            rel = path.relative_to(input_dir).as_posix()
            members.append((f"config/input/{rel}", path))
    else:
        skipped.append({"source": "config/input", "reason": "input/ is not present"})
    env_path = app_root / ".env"
    if env_path.is_file():
        members.append(("config/env", env_path))
    else:
        skipped.append({"source": "config/env", "reason": ".env is not present"})
    return members, skipped


def prune_auto(out_dir: Path, keep: int) -> List[Path]:
    """Delete the oldest ontosage-auto-*.enc archives beyond the newest `keep`.

    Touches nothing else in the folder. `keep` is floored at 1: a misconfigured zero must not
    delete the only good backup.
    """
    keep = max(1, int(keep))
    archives = sorted(out_dir.glob(f"{ARCHIVE_PREFIX}*{ARCHIVE_SUFFIX}"))
    doomed = archives[:-keep] if len(archives) > keep else []
    for path in doomed:
        path.unlink()
    return doomed


class AutoBackupService:
    """Coalescing, non-blocking scheduler and runner for automatic backups."""

    def __init__(
        self,
        *,
        enabled: bool,
        passphrase: str,
        out_dir: Path,
        min_interval_s: float,
        keep: int,
        pool_getter: Callable[[], Any],
        app_root: Path,
        building_id: str,
        settle_s: float = SETTLE_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._out_dir = Path(out_dir)
        self._passphrase = passphrase or ""
        self._min_interval_s = float(min_interval_s)
        self._keep = int(keep)
        self._pool_getter = pool_getter
        self._app_root = Path(app_root)
        self._building_id = building_id
        self._settle_s = float(settle_s)
        self._clock = clock
        self._sleep = sleep

        self._requested = False
        self._worker: Optional[asyncio.Task] = None
        self._last_start: Optional[float] = None
        self._last_success_mono: Optional[float] = None

        self.successes = 0
        self.failures = 0
        self.last_success_utc: Optional[str] = None
        self.last_attempt_utc: Optional[str] = None

        self.enabled = False
        if not enabled:
            logger.info("[auto_backup] disabled by AUTO_BACKUP_ENABLED=false")
        elif not self._passphrase:
            logger.warning(
                "[auto_backup] DISABLED: BACKUP_PASSPHRASE is not set. Automatic backups are "
                "off until it is set in the active .env."
            )
        elif len(self._passphrase) < MIN_PASSPHRASE_LENGTH:
            logger.error(
                f"[auto_backup] DISABLED: BACKUP_PASSPHRASE is shorter than "
                f"{MIN_PASSPHRASE_LENGTH} characters. Set a longer one in the active .env."
            )
        else:
            self.enabled = True
            logger.info(
                f"[auto_backup] enabled: every >= {self._min_interval_s:.0f}s after an answer, "
                f"keep newest {max(1, self._keep)} in {self._out_dir}"
            )

    # ----- scheduling -------------------------------------------------------------------

    def request(self) -> None:
        """Ask for a backup. Returns at once; never raises."""
        if not self.enabled:
            return
        self._requested = True
        if self._worker is not None and not self._worker.done():
            return  # the running worker will see the flag and run once more after the interval
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("[auto_backup] request outside a running event loop; not scheduled")
            return
        self._worker = loop.create_task(self._worker_main())

    async def _worker_main(self) -> None:
        try:
            await self._worker_loop()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - _run_once already catches everything
            self.failures += 1
            logger.error(f"[auto_backup] scheduler stopped: {type(exc).__name__}: {exc}")

    async def _worker_loop(self) -> None:
        while self._requested:
            if self._last_start is not None:
                wait = self._last_start + self._min_interval_s - self._clock()
                if wait > 0:
                    await self._sleep(wait)
                    continue
            self._requested = False
            self._last_start = self._clock()
            if self._settle_s > 0:
                await self._sleep(self._settle_s)
            await self._run_once()

    # ----- one run ----------------------------------------------------------------------

    async def _run_once(self) -> None:
        """One backup run. Never raises (except cancellation): failures are logged and counted."""
        now = _utc_now()
        self.last_attempt_utc = now.isoformat()
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        out_path = self._out_dir / f"{ARCHIVE_PREFIX}{stamp}{ARCHIVE_SUFFIX}"
        staging = Path(tempfile.mkdtemp(prefix="ontosage-auto-stage-"))
        try:
            pool = self._pool_getter()
            if pool is None:
                raise BackupError("PostgreSQL is not connected; the user data cannot be exported")
            self._out_dir.mkdir(parents=True, exist_ok=True)

            db_members = await export_postgres(pool, staging)
            cfg_members, skipped = config_members(self._app_root)
            members = db_members + cfg_members
            header = {
                "format": FORMAT_NAME,
                "format_version": FORMAT_VERSION,
                "building_id": self._building_id,
                "created_utc": now.isoformat(),
                "scope": "automatic",
                "skipped": skipped,
                "excluded_by_design": EXCLUDED_BY_DESIGN,
            }
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, write_archive, out_path, self._passphrase, members, header
            )
            pruned = await loop.run_in_executor(None, prune_auto, self._out_dir, self._keep)
            size = out_path.stat().st_size
            self.successes += 1
            self.last_success_utc = now.isoformat()
            self._last_success_mono = self._clock()
            logger.info(
                f"[auto_backup] wrote {out_path.name} ({size} bytes, {len(members)} members, "
                f"{len(skipped)} skipped, {len(pruned)} pruned)"
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.failures += 1
            logger.error(
                f"[auto_backup] backup FAILED ({type(exc).__name__}): {exc}. "
                f"Failures so far: {self.failures}."
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    # ----- observability ----------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """The /health `backup` block. Carries no error text: /health is unauthenticated."""
        age = None
        if self._last_success_mono is not None:
            age = round(self._clock() - self._last_success_mono, 1)
        return {
            "enabled": self.enabled,
            "last_success_utc": self.last_success_utc,
            "last_success_age_s": age,
            "last_attempt_utc": self.last_attempt_utc,
            "successes": self.successes,
            "failures": self.failures,
            "pending": self._requested,
            "min_interval_s": self._min_interval_s,
            "keep": max(1, self._keep),
        }


_service: Optional[AutoBackupService] = None


def get_service(pool_getter: Callable[[], Any]) -> AutoBackupService:
    """The process-wide service, built once from shared.config.settings on first use."""
    global _service
    if _service is None:
        from shared.config import settings

        _service = AutoBackupService(
            enabled=settings.AUTO_BACKUP_ENABLED,
            passphrase=settings.BACKUP_PASSPHRASE or "",
            out_dir=Path(settings.AUTO_BACKUP_DIR),
            min_interval_s=settings.AUTO_BACKUP_MIN_INTERVAL_S,
            keep=settings.AUTO_BACKUP_KEEP,
            pool_getter=pool_getter,
            # orchestrator/services/auto_backup.py -> parents[2] is the app root: /app in the
            # container, where input/ and .env are mounted.
            app_root=Path(__file__).resolve().parents[2],
            building_id=settings.BUILDING_ID,
        )
    return _service
