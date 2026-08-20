"""
A normalised entity model shared by both front-ends.

The pipeline reads two very different sources - DXF via ezdxf, and DWG via the
LibreDWG WebAssembly dump - but the geometry and semantics logic downstream
should not care which one it got. Both readers flatten to `NormEntity`, and
everything after that is source-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NormEntity:
    """One CAD entity, reduced to the fields the knowledge graph needs."""

    type: str                                   # LWPOLYLINE | TEXT | INSERT | DIMENSION | ...
    layer: str = ""
    handle: str = ""
    paper_space: bool = False

    # Polyline / boundary geometry, already scaled to metres.
    points: list[tuple[float, float]] = field(default_factory=list)
    closed: bool = False

    # Text-bearing entities.
    text: str = ""

    # Block references.
    block_name: str | None = None
    attribs: dict[str, str] = field(default_factory=dict)

    # A single anchor point (insertion point, centre, text position), in metres.
    point: tuple[float, float] | None = None

    # DIMENSION only. `measurement` is what AutoCAD computed from the geometry,
    # scaled to metres; `text_override` is what the drafter typed, if anything.
    measurement: float | None = None
    text_override: str | None = None
    dimension_type: int | None = None
    dimension_points: list[tuple[float, float]] = field(default_factory=list)

    # Extended entity data - occasionally carries real asset semantics.
    xdata: Any = None

    def is_text(self) -> bool:
        return self.type in ("TEXT", "MTEXT")
