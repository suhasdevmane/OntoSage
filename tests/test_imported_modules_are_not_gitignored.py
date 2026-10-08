"""A module that tracked code imports must not be swallowed by an ignore rule.

``orchestrator/services/auto_backup.py`` matched the generic ``*_backup.*`` rule in .gitignore and
was never committed (found 2026-10-08). ``main.py`` imports it lazily and its own test imports it
at module level, so on the developer's machine everything passed, while every fresh clone and CI
failed to collect ``tests/test_auto_backup.py`` and silently lost the automatic-backup feature.
The same rule had already swallowed ``tests/test_consequence_and_backup.py`` once (A2). An IGNORED
file does not appear in ``git status``, so nothing short of a check like this one sees it.

Only ignored-and-untracked files fail. A new module that is merely not yet added shows in
``git status`` and is the developer's normal working state, so it is not reported here.
"""

import ast
import shutil
import subprocess
from pathlib import Path
from typing import Callable, List, Sequence, Set

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
#: Top-level packages whose modules live in this repository.
PACKAGES = ("orchestrator", "shared")
#: Where importers are looked for.
SCAN = ("orchestrator", "shared", "tests", "scripts")


def _dotted_to_files(dotted: str) -> List[str]:
    """The two files a dotted module name can live in, repository-relative and POSIX."""
    base = dotted.replace(".", "/")
    return [f"{base}.py", f"{base}/__init__.py"]


def imported_module_files(source: str, rel_path: str, exists: Callable[[str], bool]) -> Set[str]:
    """Repository files the imports in ``source`` resolve to, wherever in the file they sit.

    Walks the whole tree, so an import inside a function (the lazy kind main.py uses) counts.
    ``from pkg import name`` yields the package and, when it exists, ``pkg/name.py`` too: the
    name may be a submodule, and that is exactly how tests/test_auto_backup.py imported it.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    package_parts = rel_path.replace("\\", "/").split("/")[:-1]
    dotted: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                dotted.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = len(package_parts) - (node.level - 1)
                if keep < 0:
                    continue
                prefix = package_parts[:keep]
                module = ".".join(prefix + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            if not module:
                continue
            dotted.add(module)
            for alias in node.names:
                if alias.name != "*":
                    dotted.add(f"{module}.{alias.name}")
    found: Set[str] = set()
    for name in dotted:
        if name.split(".")[0] not in PACKAGES:
            continue
        for candidate in _dotted_to_files(name):
            if exists(candidate):
                found.add(candidate)
    return found


def _git(args: List[str], paths: Sequence[str] = ()) -> List[str]:
    """Run git with NUL-separated paths on stdin and return its NUL-separated output fields.

    Bytes, not text: in text mode Windows writes every "\\n" as "\\r\\n", so git was asked about
    "auto_backup.py\\r" -- which the exact-name negation does not match -- and the check failed
    on the fixed tree. NUL separation leaves nothing to translate.
    """
    stdin = b"".join(p.encode("utf-8") + b"\0" for p in paths)
    done = subprocess.run(["git", *args], cwd=REPO, input=stdin, capture_output=True)
    if done.returncode not in (0, 1):  # check-ignore exits 1 when nothing is ignored
        pytest.skip(f"git {args[0]} failed: {done.stderr.decode('utf-8', 'replace').strip()}")
    return [f for f in done.stdout.decode("utf-8").split("\0") if f]


def test_the_resolver_sees_a_lazy_import_a_submodule_and_a_relative_import():
    """Pinned on synthetic source, so the check cannot pass by resolving nothing."""
    source = (
        "import json\n"
        "from orchestrator.services import auto_backup as auto\n"
        "from . import sibling\n"
        "def later():\n"
        "    from shared.utils import get_logger\n"
        "    return get_logger\n"
    )
    on_disk = {
        "orchestrator/services/__init__.py",
        "orchestrator/services/auto_backup.py",
        "orchestrator/agents/sibling.py",
        "shared/utils.py",
    }
    found = imported_module_files(source, "orchestrator/agents/x.py", on_disk.__contains__)
    assert found == on_disk


def test_no_module_imported_by_tracked_code_is_gitignored():
    if shutil.which("git") is None or not (REPO / ".git").exists():
        pytest.skip("not a git checkout")
    tracked = _git(["ls-files", "-z", "--", *[f"{d}/*.py" for d in SCAN]])
    assert tracked, "git ls-files found no tracked Python files, so this check saw nothing"

    def exists(rel: str) -> bool:
        return (REPO / rel).is_file()

    imported: Set[str] = set()
    for rel in tracked:
        try:
            source = (REPO / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "orchestrator" not in source and "shared" not in source and "from ." not in source:
            continue
        imported |= imported_module_files(source, rel, exists)
    assert imported, "no repository module resolved from any import, so this check saw nothing"

    # Without -v, check-ignore prints only paths that are excluded (a path matching a negation
    # rule is not), and tracked files are never reported.
    swallowed = _git(["check-ignore", "-z", "--stdin"], sorted(imported))
    if swallowed:
        # -v -z prints four fields per path: source, line number, pattern, path.
        fields = _git(["check-ignore", "-v", "-z", "--stdin"], swallowed)
        rules = [
            f"{fields[i + 3]}  <- {fields[i]}:{fields[i + 1]}: {fields[i + 2]}"
            for i in range(0, len(fields) - 3, 4)
        ]
        pytest.fail(
            "modules imported by tracked code are gitignored and will be missing from every "
            "clone (add a specific negation in .gitignore):\n" + "\n".join(rules)
        )
