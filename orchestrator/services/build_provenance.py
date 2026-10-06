"""Which code is running: the image's baked BUILD_SHA and the git HEAD of the mounted source.

`code_sha` is what the image was built from (BUILD_SHA, baked by the Dockerfile; "unknown"
when the build did not pass GIT_SHA). `mounted_sha` is the HEAD commit of the git checkout
that the source tree belongs to, read straight from the .git files with no subprocess. It
is None when no .git directory is reachable. In a container that only bind-mounts
orchestrator/, there is no .git and mounted_sha is None. That is reported as None, never
guessed from code_sha.
"""

import os
import re
from pathlib import Path
from typing import Dict, Optional

_SHA_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_WALK_LIMIT = 6


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _git_dir(start: Path) -> Optional[Path]:
    """Locate the git directory for start, walking up a few levels; handles worktree files."""
    candidates = [start, *start.parents][:_WALK_LIMIT]
    for directory in candidates:
        marker = directory / ".git"
        if marker.is_dir():
            return marker
        if marker.is_file():
            text = _read_text(marker) or ""
            if not text.startswith("gitdir:"):
                return None
            target = Path(text[len("gitdir:") :].strip())
            if not target.is_absolute():
                target = directory / target
            return target if target.is_dir() else None
    return None


def _ref_sha(common: Path, ref: str) -> Optional[str]:
    loose = _read_text(common / ref)
    if loose and _SHA_RE.match(loose):
        return loose
    packed = _read_text(common / "packed-refs")
    if packed:
        for line in packed.splitlines():
            parts = line.split(" ", 1)
            if len(parts) == 2 and parts[1].strip() == ref and _SHA_RE.match(parts[0]):
                return parts[0]
    return None


def read_git_head_sha(start: Path) -> Optional[str]:
    """Return the commit HEAD points at, or None when there is no readable git checkout."""
    gitdir = _git_dir(Path(start).resolve())
    if gitdir is None:
        return None
    head = _read_text(gitdir / "HEAD")
    if not head:
        return None
    if not head.startswith("ref:"):
        return head if _SHA_RE.match(head) else None
    common = gitdir
    commondir = _read_text(gitdir / "commondir")
    if commondir:
        common = (gitdir / commondir).resolve()
    return _ref_sha(common, head[len("ref:") :].strip())


def build_identity(start: Optional[Path] = None) -> Dict[str, Optional[str]]:
    """The two provenance fields /health reports at top level."""
    root = start if start is not None else Path(__file__).resolve().parents[2]
    code_sha = (os.environ.get("BUILD_SHA") or "").strip() or "unknown"
    return {"code_sha": code_sha, "mounted_sha": read_git_head_sha(root)}
