# -*- coding: utf-8 -*-
"""The detector for "stored but never read back" (2026-08-27).

Five capabilities in this codebase shipped correct, tested, and with no invoker,
each externally indistinguishable from the feature being absent. None was found
by noticing; the one that found all five was a mechanical question — for every
kind of data stored, where is the code that reads it back? — applied to the
graph. scripts/audit_unread_stores.py asks it of the relational stores, and
immediately found the sixth: actuation_log, written on every approved setpoint
change since T23 and read by nothing.

A detector is only worth having if it fires, so these tests plant the defect
rather than asserting the current tree happens to be clean.
"""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def audit():
    path = _REPO / "scripts" / "audit_unread_stores.py"
    spec = importlib.util.spec_from_file_location("_audit_unread", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(root: Path, name: str, text: str) -> None:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ── it fires on the defect it exists to find ─────────────────────────────────
def test_a_table_written_and_never_read_is_reported(audit, tmp_path):
    _write(tmp_path, "writer.py", 'SQL = "INSERT INTO orphan_log (a) VALUES ($1)"\n')
    _write(tmp_path, "reader.py", 'SQL = "SELECT a FROM other_table"\n')
    out = audit.scan(root_dir=tmp_path)
    assert "orphan_log" in out["unread_tables"]
    assert "orphan_log" in out["unread_no_other_mention"]


def test_a_table_that_is_read_is_not_reported(audit, tmp_path):
    _write(tmp_path, "w.py", 'A = "INSERT INTO kept (a) VALUES ($1)"\n')
    _write(tmp_path, "r.py", 'B = "SELECT a FROM kept WHERE a > 1"\n')
    assert "kept" not in audit.scan(root_dir=tmp_path)["unread_tables"]


def test_a_join_counts_as_a_read(audit, tmp_path):
    _write(tmp_path, "w.py", 'A = "INSERT INTO joined (a) VALUES ($1)"\n')
    _write(tmp_path, "r.py", 'B = "SELECT * FROM x JOIN joined ON x.a = joined.a"\n')
    assert "joined" not in audit.scan(root_dir=tmp_path)["unread_tables"]


# ── and separates what it knows from what it is guessing ─────────────────────
def test_a_table_named_elsewhere_is_graded_as_the_weaker_signal(audit, tmp_path):
    """The seven narrow modality tables are read through f"{modality}_data", so a
    literal FROM does not exist for them. Reporting them as unread would be a lie
    about the tables that serve every sensor question in the system."""
    _write(tmp_path, "w.py", 'A = "INSERT INTO energy_data (a) VALUES ($1)"\n')
    _write(tmp_path, "registry.yaml", "tables:\n  - energy_data\n")
    out = audit.scan(root_dir=tmp_path)
    assert out["unread_no_other_mention"] == []
    assert "energy_data" in out["unread_but_named_elsewhere"]
    assert "registry.yaml" in out["mentions"]["energy_data"]


def test_files_building_table_names_at_runtime_are_named(audit, tmp_path):
    """What the scan cannot see has to be said, not omitted."""
    _write(tmp_path, "dyn.py", 'q = f"SELECT * FROM {modality}_data WHERE uuid=%s"\n')
    assert "dyn.py" in audit.scan(root_dir=tmp_path)["dynamic_files"]


def test_a_python_import_is_not_a_table_read(audit, tmp_path):
    _write(tmp_path, "w.py", 'A = "INSERT INTO pathlib_ish (a) VALUES (1)"\n')
    _write(tmp_path, "i.py", "from pathlib_ish import thing\n")
    assert "pathlib_ish" in audit.scan(root_dir=tmp_path)["unread_tables"]


# ── the finding that prompted all this is now closed ─────────────────────────
def test_the_actuation_trail_has_a_reader(audit):
    """actuation_log was the sixth instance. If this regresses, the accountability
    record for a system that changes setpoints is write-only again."""
    out = audit.scan()
    assert "actuation_log" not in out["unread_tables"], (
        "nothing reads actuation_log any more — "
        "orchestrator/services/actuation/audit_log.py was the reader"
    )
