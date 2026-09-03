"""
generator.py — deterministic synthetic time-series for toggleable data sources.

Two layers:
  * ``generate_point_series`` / ``SyntheticDataService.generate_rows`` — PURE,
    offline, deterministic (seeded per point UUID). Produces narrow
    ``(uuid, "YYYY-MM-DD HH:MM:SS", value)`` rows with realistic diurnal/weekly
    profiles and optional *labeled* anomalies (ground truth).
  * ``SyntheticDataService.load_to_db`` / ``regenerate`` — writes those rows into
    the narrow per-modality MySQL table (same schema as
    scripts/load_timeseries_to_db.py). Requires a live DB; guarded + best-effort.

Kinds map 1:1 to the ``generator.kind`` field in datasources.yaml.
"""

from __future__ import annotations

import math
import os
import random
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from shared.db_clock import UTC_SESSION_INIT
from shared.models import DataSourcePoint, DataSourceSpec
from shared.utils import get_logger

logger = get_logger(__name__)

Row = Tuple[str, str, float]  # (uuid, "YYYY-MM-DD HH:MM:SS", value)

_TS_FMT = "%Y-%m-%d %H:%M:%S"


# ── Shape helpers ──────────────────────────────────────────────────────────────


def _is_weekend(dt: datetime) -> bool:
    return dt.weekday() >= 5


def _diurnal(dt: datetime, open_h: float, close_h: float) -> float:
    """Raised-cosine 0..1 bump during opening hours, ~0 otherwise."""
    h = dt.hour + dt.minute / 60.0
    if h <= open_h or h >= close_h:
        return 0.0
    # peak in the middle of the open window
    frac = (h - open_h) / max(close_h - open_h, 1e-6)
    return 0.5 - 0.5 * math.cos(2 * math.pi * frac)  # 0 at edges, 1 at midpoint


def _solar(dt: datetime, sunrise: float, sunset: float) -> float:
    """0..1 daylight curve (independent of occupancy)."""
    h = dt.hour + dt.minute / 60.0
    if h <= sunrise or h >= sunset:
        return 0.0
    frac = (h - sunrise) / max(sunset - sunrise, 1e-6)
    return math.sin(math.pi * frac)


def _noisy(value: float, noise: float, rng: random.Random, floor: float = 0.0) -> float:
    v = value * (1.0 + rng.uniform(-noise, noise))
    return round(max(floor, v), 3)


# ── Per-kind value functions: (dt, params, rng) -> value ────────────────────────


def _occupancy(dt: datetime, p: Dict[str, Any], rng: random.Random) -> float:
    peak = p.get("weekend_peak", 0.15) if _is_weekend(dt) else p.get("weekday_peak", 0.85)
    shape = _diurnal(dt, p.get("opening_hour", 8), p.get("closing_hour", 20))
    return _noisy(100.0 * peak * shape, p.get("noise", 0.08), rng)


def _load(dt: datetime, p: Dict[str, Any], rng: random.Random, low_k: str, high_k: str) -> float:
    low, high = p.get(low_k, 0.0), p.get(high_k, 1.0)
    wk = 0.35 if _is_weekend(dt) else 1.0
    shape = _diurnal(dt, p.get("opening_hour", 8), p.get("closing_hour", 20)) * wk
    return _noisy(low + (high - low) * shape, p.get("noise", 0.1), rng, floor=0.0)


def _energy(dt, p, rng):
    return _load(dt, p, rng, "base_kwh", "peak_kwh")


def _noise(dt, p, rng):
    # noise floor is always present; occupancy adds on top
    low, high = p.get("quiet_db", 38.0), p.get("busy_db", 68.0)
    shape = _diurnal(dt, p.get("opening_hour", 8), p.get("closing_hour", 20))
    shape *= 0.4 if _is_weekend(dt) else 1.0
    return _noisy(low + (high - low) * shape, p.get("noise", 0.12), rng, floor=low * 0.8)


def _iaq(dt, p, rng):
    low, high = p.get("base_ppm", 420.0), p.get("peak_ppm", 1100.0)
    shape = _diurnal(dt, p.get("opening_hour", 8), p.get("closing_hour", 20))
    shape *= 0.3 if _is_weekend(dt) else 1.0
    return _noisy(low + (high - low) * shape, p.get("noise", 0.06), rng, floor=low * 0.9)


def _light(dt, p, rng):
    low, high = p.get("night_lux", 5.0), p.get("day_lux", 850.0)
    shape = _solar(dt, p.get("sunrise_hour", 7), p.get("sunset_hour", 18))
    return _noisy(low + (high - low) * shape, p.get("noise", 0.15), rng, floor=0.0)


def _equipment(dt, p, rng):
    return _load(dt, p, rng, "idle_kw", "running_kw")


def _water(dt, p, rng):
    return _load(dt, p, rng, "base_m3", "peak_m3")


GENERATOR_KINDS: Dict[str, Callable[[datetime, Dict[str, Any], random.Random], float]] = {
    "occupancy_profile": _occupancy,
    "energy_load": _energy,
    "noise_profile": _noise,
    "iaq_profile": _iaq,
    "light_profile": _light,
    "equipment_profile": _equipment,
    "water_profile": _water,
}


# ── Anomaly injection ──────────────────────────────────────────────────────────


def _apply_anomalies(
    rows: List[Row], anomalies: List[Dict[str, Any]], interval_minutes: int
) -> None:
    """Mutate rows in place per labeled anomalies. Types: spike, flatline, drift."""
    if not anomalies:
        return
    ts_index = {r[1]: i for i, r in enumerate(rows)}
    for a in anomalies:
        at = str(a.get("at", "")).replace("T", " ")[:19]
        atype = a.get("type", "spike")
        mag = float(a.get("magnitude", 1.5))
        # find nearest sample at/after `at`
        idx = ts_index.get(at)
        if idx is None:
            # linear scan for the first sample >= at
            idx = next((i for i, r in enumerate(rows) if r[1] >= at), None)
        if idx is None:
            continue
        if atype == "spike":
            u, t, v = rows[idx]
            rows[idx] = (u, t, round(v * mag, 3))
        elif atype == "flatline":
            span = int(a.get("duration_min", 120) / max(interval_minutes, 1))
            hold = rows[idx][2]
            for j in range(idx, min(idx + span, len(rows))):
                u, t, _ = rows[j]
                rows[j] = (u, t, hold)
        elif atype == "drift":
            span = int(a.get("duration_min", 240) / max(interval_minutes, 1))
            for k, j in enumerate(range(idx, min(idx + span, len(rows)))):
                u, t, v = rows[j]
                rows[j] = (u, t, round(v * (1.0 + (mag - 1.0) * (k / max(span, 1))), 3))


# ── Pure generation ──────────────────────────────────────────────────────────


def generate_point_series(
    point: DataSourcePoint,
    kind: str,
    *,
    window_days: int = 30,
    interval_minutes: int = 15,
    params: Optional[Dict[str, Any]] = None,
    anomalies: Optional[List[Dict[str, Any]]] = None,
    end: Optional[datetime] = None,
) -> List[Row]:
    """Deterministic narrow rows for one point. Seeded by the point UUID."""
    fn = GENERATOR_KINDS.get(kind)
    if fn is None:
        raise ValueError(f"unknown generator kind '{kind}'")
    params = params or {}
    rng = random.Random(f"{point.uuid}:{kind}")
    end = (end or datetime.utcnow()).replace(second=0, microsecond=0)
    start = end - timedelta(days=window_days)
    step = timedelta(minutes=interval_minutes)

    rows: List[Row] = []
    dt = start
    while dt <= end:
        rows.append((point.uuid or "", dt.strftime(_TS_FMT), fn(dt, params, rng)))
        dt += step
    _apply_anomalies(rows, anomalies or [], interval_minutes)
    return rows


# ── Service ──────────────────────────────────────────────────────────────────


class SyntheticDataService:
    """Generates rows for a data source and (optionally) loads them into MySQL."""

    def generate_rows(
        self, spec: DataSourceSpec, *, end: Optional[datetime] = None
    ) -> Dict[str, List[Row]]:
        """{point_local: rows} for every point in a timeseries source."""
        if spec.kind != "timeseries" or not spec.generator:
            return {}
        gen = spec.generator
        out: Dict[str, List[Row]] = {}
        for pt in spec.points:
            out[pt.local] = generate_point_series(
                pt,
                gen.kind,
                window_days=gen.window_days,
                interval_minutes=gen.interval_minutes,
                params=gen.params,
                anomalies=gen.anomalies,
                end=end,
            )
        return out

    def preview(
        self, spec: DataSourceSpec, *, limit: int = 48, end: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Sample series for the first point (no DB write) + summary counts."""
        rows_by_point = self.generate_rows(spec, end=end)
        first = next(iter(rows_by_point.values()), [])
        sample = [{"t": t, "v": v} for (_u, t, v) in first[-limit:]]
        total = sum(len(r) for r in rows_by_point.values())
        return {
            "source_id": spec.id,
            "points": len(spec.points),
            "rows_per_point": len(first),
            "total_rows": total,
            "ts_table": spec.ts_table,
            "sample": sample,
        }

    # ── Live DB load (guarded) ────────────────────────────────────────────────

    def load_to_db(self, rows_by_point: Dict[str, List[Row]], ts_table: str) -> int:
        """Upsert generated rows into the narrow MySQL table. Returns rows written."""
        try:
            import pymysql
        except ImportError:  # pragma: no cover
            logger.warning("[synthetic] pymysql not installed — cannot load to DB")
            return 0

        create_sql = (
            f"CREATE TABLE IF NOT EXISTS `{ts_table}` ("
            "`uuid` CHAR(36) NOT NULL, `datetime` DATETIME NOT NULL, `value` DOUBLE NULL, "
            "PRIMARY KEY (`uuid`, `datetime`), INDEX `idx_uuid` (`uuid`)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )
        upsert_sql = (
            f"INSERT INTO `{ts_table}` (`uuid`, `datetime`, `value`) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)"
        )
        conn = pymysql.connect(
            host=os.environ.get("MYSQL_HOST", "mysql"),
            port=int(os.environ.get("MYSQL_PORT", "3306")),
            user=os.environ.get("MYSQL_USER", "root"),
            password=os.environ.get("MYSQL_PASSWORD", "mysql"),
            database=os.environ.get("MYSQL_DATABASE", "sensordb"),
            connect_timeout=10,
            autocommit=False,
            # Same clock the rows are stamped in (BUG-403).
            init_command=UTC_SESSION_INIT,
        )
        written = 0
        try:
            with conn.cursor() as cur:
                cur.execute(create_sql)
            conn.commit()
            for rows in rows_by_point.values():
                if not rows:
                    continue
                with conn.cursor() as cur:
                    cur.executemany(upsert_sql, rows)
                conn.commit()
                written += len(rows)
        finally:
            conn.close()
        logger.info(f"[synthetic] loaded {written} rows into `{ts_table}`")
        return written

    def regenerate(self, spec: DataSourceSpec, *, end: Optional[datetime] = None) -> Dict[str, Any]:
        """Generate + load a source's rows. No-op for non-timeseries sources."""
        if spec.kind != "timeseries" or not spec.ts_table:
            return {"ok": True, "source_id": spec.id, "rows": 0, "note": "no timeseries"}
        rows_by_point = self.generate_rows(spec, end=end)
        written = self.load_to_db(rows_by_point, spec.ts_table)
        return {"ok": True, "source_id": spec.id, "rows": written, "ts_table": spec.ts_table}
