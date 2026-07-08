"""base.py — ActuationDriver abstract base class (T23).

All concrete drivers (SimDriver, BACnetDriver, …) implement this interface.
The interface is intentionally minimal: Phase G only needs set_point.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ActuationResult:
    """Returned by every set_point() call."""

    success: bool
    point_uri: str
    value: Any
    audit_id: Optional[str] = None
    message: str = ""
    error: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


class ActuationDriver(ABC):
    """Abstract interface for all actuation backends."""

    @abstractmethod
    async def set_point(
        self,
        point_uri: str,
        value: Any,
        *,
        user_id: str = "system",
        reason: str = "",
    ) -> ActuationResult:
        """Write a setpoint value.

        Returns ActuationResult with success=True on acceptance, False on
        rejection or error.  Implementations MUST be safe to call with any
        point_uri — if the point is unknown or not writable, return success=False.
        """

    @abstractmethod
    async def capabilities(self) -> List[str]:
        """Return list of writable point URIs this driver can control."""
