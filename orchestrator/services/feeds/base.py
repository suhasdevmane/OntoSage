"""
feeds/base.py — FeedSpec model, FeedRecord dataclass, FeedAdapter ABC.

Feed spec fields:
  id           Unique identifier within the building  (required)
  type         "rest_poll" | "csv_drop"               (required)
  url          HTTP endpoint for rest_poll             (rest_poll only)
  path         File path for csv_drop                  (csv_drop only)
  auth_env     Name of the env-var holding the token/key (never the value)
  interval_s   Polling cadence in seconds              (default: 60)
  field_map    {source_field: metric_name} JSON extraction mapping
  brick_class  Brick class URI for the generated point (e.g. brick:Temperature_Sensor)
  location     Building URI of the sensor location     (e.g. bldg:room_501)
  unit         Physical unit string                    (e.g. "degC", "ppm")
  storage      storedAt URI routed through adapter_registry (e.g. "bldg:database1")
  uuid         Deterministic UUID for the time-series; auto-derived if absent
  enabled      Whether this feed is active             (default: true)
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from shared.utils import get_logger

logger = get_logger(__name__)


class FeedSpec(BaseModel):
    """Pydantic model for one entry in feeds.yaml."""

    id: str = Field(..., min_length=1)
    type: str = Field(..., pattern=r"^(rest_poll|csv_drop)$")
    url: Optional[str] = None
    path: Optional[str] = None
    auth_env: Optional[str] = None
    interval_s: int = Field(default=60, ge=1)
    field_map: Dict[str, str] = Field(default_factory=dict)
    brick_class: str = "brick:Sensor"
    location: Optional[str] = None
    unit: Optional[str] = None
    storage: str = ""
    uuid: Optional[str] = None
    enabled: bool = True

    @field_validator("url", "path", mode="before")
    @classmethod
    def _expand_env(cls, v: Optional[str]) -> Optional[str]:
        """Expand $ENV_VAR references in url/path at load time."""
        if v and "$" in v:
            return os.path.expandvars(v)
        return v

    def auth_header(self) -> Optional[str]:
        """Read the bearer token from the configured env-var (never log it)."""
        if not self.auth_env:
            return None
        token = os.environ.get(self.auth_env)
        if not token:
            logger.warning(f"[feeds] auth_env='{self.auth_env}' is set but empty")
        return token


@dataclass
class FeedRecord:
    """One data point emitted by a FeedAdapter.poll() call."""

    feed_id: str
    uuid: str
    timestamp: datetime
    value: float
    metric: str = "value"
    unit: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


class FeedAdapter(ABC):
    """Abstract base class for all feed source adapters.

    Subclasses implement poll(); the registry calls write() to persist results.
    """

    def __init__(self, spec: FeedSpec) -> None:
        self.spec = spec

    @abstractmethod
    async def poll(self) -> List[FeedRecord]:
        """Fetch new data from the source.  Must never raise — catch and log."""
        ...

    async def poll_safe(self) -> List[FeedRecord]:
        """poll() with blanket exception guard so the polling loop stays alive."""
        try:
            return await self.poll()
        except Exception as e:
            logger.error(f"[feeds] {self.spec.id} poll failed: {e}", exc_info=True)
            return []

    def _make_record(
        self, value: float, metric: str = "value", ts: Optional[datetime] = None
    ) -> FeedRecord:
        """Convenience constructor using this adapter's spec."""
        from datetime import timezone

        return FeedRecord(
            feed_id=self.spec.id,
            uuid=self.spec.uuid or self.spec.id,
            timestamp=ts or datetime.now(tz=timezone.utc),
            value=value,
            metric=metric,
            unit=self.spec.unit,
        )
