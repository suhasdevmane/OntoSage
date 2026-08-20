"""
feeds/csv_drop.py — CSV file drop adapter.

Reads rows from a CSV file at spec.path.  Tracks how many rows have been
consumed so repeated poll() calls return only NEW rows (append-mode files).

field_map: {csv_column_name -> metric_name}
  If the CSV has a 'timestamp' or 'datetime' column it is parsed as ISO-8601.
  Otherwise, the current UTC time is used.

The offset (last consumed row index) is kept in memory — reset on restart,
which causes the whole file to be re-read once and then only new rows.
This is intentional: the adapter registry upstream deduplicates by uuid+ts.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from orchestrator.services.feeds.base import FeedAdapter, FeedRecord, FeedSpec
from shared.utils import get_logger

logger = get_logger(__name__)

_TIMESTAMP_COLS = {"timestamp", "datetime", "time", "ts", "date"}


def _parse_ts(value: str) -> Optional[datetime]:
    """Parse an ISO-8601-like datetime string; return None on failure."""
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(value.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


class CsvDropAdapter(FeedAdapter):
    """Read new rows from a CSV file and emit FeedRecords."""

    def __init__(self, spec: FeedSpec, *, input_root: str = "/app/input") -> None:
        super().__init__(spec)
        self._input_root = Path(input_root)
        self._offset: int = 0  # rows consumed so far (header not counted)

    def _resolve_path(self) -> Optional[Path]:
        if not self.spec.path:
            logger.warning(f"[feeds] {self.spec.id}: csv_drop requires path")
            return None
        p = Path(self.spec.path)
        if p.is_absolute():
            return p
        # Relative path: resolve against input_root
        return self._input_root / p

    async def poll(self) -> List[FeedRecord]:
        csv_path = self._resolve_path()
        if csv_path is None:
            return []
        if not csv_path.exists():
            logger.debug(f"[feeds] {self.spec.id}: CSV not found at {csv_path}")
            return []

        try:
            text = csv_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning(f"[feeds] {self.spec.id} could not read {csv_path}: {e}")
            return []

        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            return []

        # Identify timestamp column (case-insensitive)
        ts_col: Optional[str] = None
        for col in reader.fieldnames:
            if col.lower() in _TIMESTAMP_COLS:
                ts_col = col
                break

        # Identify which field_map columns exist
        field_map = self.spec.field_map
        if not field_map:
            # Auto-map first non-timestamp column to "value"
            for col in reader.fieldnames:
                if col.lower() not in _TIMESTAMP_COLS:
                    field_map = {col: "value"}
                    break

        now = datetime.now(tz=timezone.utc)
        all_rows = list(reader)
        new_rows = all_rows[self._offset :]
        self._offset = len(all_rows)

        records: List[FeedRecord] = []
        for row in new_rows:
            ts = now
            if ts_col and row.get(ts_col):
                parsed = _parse_ts(row[ts_col])
                if parsed:
                    ts = parsed

            for src_col, metric_name in field_map.items():
                raw = row.get(src_col)
                if raw is None:
                    continue
                try:
                    value = float(raw)
                except (ValueError, TypeError):
                    continue
                records.append(self._make_record(value, metric_name, ts))

        return records
