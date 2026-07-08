"""Resolve per-building config files across the flat and nested input layouts.

The canonical layout is **FLAT**: a single building's files sit directly under
``input/`` (``input/building.yaml``, ``input/capability.yaml``,
``input/documents/``, ``input/*.ttl`` …). The **nested** layout
(``input/<building_id>/…``) is kept as a *fallback* for staging / multi-building
setups. Per-building loaders should use these helpers instead of hardcoding
either form, so a building works regardless of how its files are laid out.

Precedence: nested (``input/<id>/<name>``) is tried first so an explicit
per-building file wins; the flat (``input/<name>``) form is the fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union

_PathLike = Union[str, Path]


def _candidate_roots(input_root: Optional[_PathLike]) -> List[Path]:
    """Roots to search. When unspecified, prefer the container mount then the
    repo-relative dir (matches the convention used across the services)."""
    if input_root is not None:
        return [Path(input_root)]
    return [Path("/app/input"), Path("input")]


def resolve_building_file(
    building_id: str,
    filename: str,
    input_root: Optional[_PathLike] = None,
) -> Optional[Path]:
    """Return the first existing config FILE for ``building_id``.

    Tries the nested layout (``<root>/<building_id>/<filename>``) then the flat
    layout (``<root>/<filename>``) under each candidate root. Returns ``None``
    when neither exists.
    """
    for root in _candidate_roots(input_root):
        for candidate in (root / building_id / filename, root / filename):
            if candidate.is_file():
                return candidate
    return None


def resolve_building_dir(
    building_id: str,
    dirname: str,
    input_root: Optional[_PathLike] = None,
) -> Optional[Path]:
    """Like :func:`resolve_building_file` but for a DIRECTORY (e.g. ``documents``,
    ``data``). Returns the first existing directory, or ``None``."""
    for root in _candidate_roots(input_root):
        for candidate in (root / building_id / dirname, root / dirname):
            if candidate.is_dir():
                return candidate
    return None
