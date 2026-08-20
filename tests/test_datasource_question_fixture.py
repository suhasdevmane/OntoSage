"""
test_datasource_question_fixture.py -- fixture-driven datasource question set tests.

Loads tests/fixtures/datasource_question_set.yaml and validates structural completeness
of each entry (offline, no live stack required).

Live end-to-end execution of this fixture (requires running stack) is covered by
scripts/test_datasource_capability_qa.py -- that script sends real HTTP requests and
asserts on live responses.  This test module validates the fixture itself so it remains
correct and complete as datasources.yaml evolves.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

pytestmark = pytest.mark.unit

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "datasource_question_set.yaml"


def _bldg1_datasources_path() -> Path:
    """The bldg1 toggle manifest, wherever bldg1 currently lives.

    The question fixture below is written against BLDG1's source ids, so this
    test must never read another building's datasources.yaml just because that
    building happens to be active (buildings swap by folder rename)."""
    repo = Path(__file__).resolve().parents[1]
    parked = repo / "bldg1" / "datasources.yaml"
    if parked.exists():
        return parked
    env = repo / "input" / "env.building"
    if env.exists() and "BUILDING_ID=bldg1" in env.read_text(encoding="utf-8"):
        return repo / "input" / "datasources.yaml"
    return parked  # missing -> _require_datasources() skips


DATASOURCES_PATH = _bldg1_datasources_path()

VALID_PERSONAS = {"facility_manager", "occupant", "researcher", "admin"}
VALID_BEHAVIORS = {"locked_decline", "substantive_answer", "pass_through"}

# Sources that intentionally have no match_keywords (never locked).
UNLOCKABLE_SOURCES = {"iaq", "light"}


def _load_fixture() -> List[Dict[str, Any]]:
    data = yaml.safe_load(FIXTURE_PATH.read_text(encoding="utf-8"))
    return data.get("questions", [])


def _require_datasources() -> Dict[str, Any]:
    # datasources.yaml is an OPTIONAL per-building config (the datasource-toggles
    # feature). A building without it (e.g. bldg2 under the flat layout) is valid —
    # skip the datasources-coupled checks rather than hard-fail on a missing file.
    if not DATASOURCES_PATH.exists():
        pytest.skip(f"no datasources.yaml for the active building ({DATASOURCES_PATH})")
    return yaml.safe_load(DATASOURCES_PATH.read_text(encoding="utf-8")) or {}


def _load_datasource_ids() -> List[str]:
    data = _require_datasources()
    return [s["id"] for s in data.get("datasources", [])]


def _load_match_keywords() -> Dict[str, List[str]]:
    data = _require_datasources()
    return {s["id"]: s.get("match_keywords", []) for s in data.get("datasources", [])}


# ── Fixture self-validation ──────────────────────────────────────────────────


class TestFixtureCompleteness:
    """Offline structural checks on the question fixture."""

    def test_fixture_exists(self) -> None:
        assert FIXTURE_PATH.exists(), f"Missing fixture: {FIXTURE_PATH}"

    def test_fixture_has_questions(self) -> None:
        qs = _load_fixture()
        assert len(qs) >= 10, f"Expected >= 10 questions, got {len(qs)}"

    def test_all_ids_unique(self) -> None:
        qs = _load_fixture()
        ids = [q["id"] for q in qs]
        assert len(ids) == len(set(ids)), f"Duplicate question IDs: {ids}"

    def test_required_fields_present(self) -> None:
        qs = _load_fixture()
        required = {"id", "source_id", "question", "persona", "when_off", "when_on"}
        for q in qs:
            missing = required - set(q.keys())
            assert not missing, f"Question {q.get('id')!r} missing fields: {missing}"

    def test_all_source_ids_known(self) -> None:
        qs = _load_fixture()
        known = set(_load_datasource_ids())
        for q in qs:
            assert (
                q["source_id"] in known
            ), f"Question {q['id']!r} references unknown source {q['source_id']!r}"

    def test_all_personas_valid(self) -> None:
        qs = _load_fixture()
        for q in qs:
            assert q["persona"] in VALID_PERSONAS, (
                f"Question {q['id']!r} has unknown persona {q['persona']!r}. "
                f"Valid: {VALID_PERSONAS}"
            )

    def test_when_off_behavior_valid(self) -> None:
        qs = _load_fixture()
        for q in qs:
            b = q["when_off"].get("behavior")
            assert (
                b in VALID_BEHAVIORS
            ), f"Question {q['id']!r} when_off.behavior={b!r} not in {VALID_BEHAVIORS}"

    def test_when_on_behavior_valid(self) -> None:
        qs = _load_fixture()
        for q in qs:
            b = q["when_on"].get("behavior")
            assert (
                b in VALID_BEHAVIORS
            ), f"Question {q['id']!r} when_on.behavior={b!r} not in {VALID_BEHAVIORS}"

    def test_locked_decline_entries_have_must_contain(self) -> None:
        """Every OFF=locked_decline entry must name what to check for in the response."""
        qs = _load_fixture()
        for q in qs:
            if q["when_off"].get("behavior") == "locked_decline":
                mc = q["when_off"].get("must_contain", [])
                assert (
                    mc
                ), f"Question {q['id']!r}: when_off=locked_decline but must_contain is empty"

    def test_substantive_answer_entries_have_must_contain(self) -> None:
        qs = _load_fixture()
        for q in qs:
            if q["when_on"].get("behavior") == "substantive_answer":
                mc = q["when_on"].get("must_contain", [])
                assert (
                    mc
                ), f"Question {q['id']!r}: when_on=substantive_answer but must_contain is empty"

    def test_substantive_answer_entries_have_provenance_label(self) -> None:
        qs = _load_fixture()
        for q in qs:
            if q["when_on"].get("behavior") == "substantive_answer":
                pl = q["when_on"].get("provenance_label")
                assert (
                    pl
                ), f"Question {q['id']!r}: when_on=substantive_answer but provenance_label missing"

    def test_unlockable_sources_use_pass_through_behavior(self) -> None:
        """iaq and light have no match_keywords: their when_off must be pass_through."""
        qs = _load_fixture()
        for q in qs:
            if q["source_id"] in UNLOCKABLE_SOURCES:
                b = q["when_off"].get("behavior")
                assert b == "pass_through", (
                    f"Question {q['id']!r}: source {q['source_id']!r} has no match_keywords "
                    f"so when_off.behavior must be 'pass_through', not {b!r}"
                )

    def test_lockable_sources_use_locked_decline_behavior(self) -> None:
        """Sources WITH match_keywords must declare when_off=locked_decline."""
        qs = _load_fixture()
        kw_map = _load_match_keywords()
        for q in qs:
            sid = q["source_id"]
            if sid not in UNLOCKABLE_SOURCES and kw_map.get(sid):
                b = q["when_off"].get("behavior")
                assert b == "locked_decline", (
                    f"Question {q['id']!r}: source {sid!r} has match_keywords "
                    f"so when_off.behavior should be 'locked_decline', not {b!r}"
                )


class TestFixtureCoverage:
    """Checks that the fixture covers all lockable sources at least once."""

    def test_all_lockable_sources_have_at_least_one_entry(self) -> None:
        qs = _load_fixture()
        kw_map = _load_match_keywords()
        lockable = {sid for sid, kws in kw_map.items() if kws}
        covered = {q["source_id"] for q in qs if q["when_off"].get("behavior") == "locked_decline"}
        uncovered = lockable - covered
        assert not uncovered, f"Lockable sources not covered by any fixture question: {uncovered}"

    def test_at_least_one_no_lock_question_per_unlockable_source(self) -> None:
        qs = _load_fixture()
        covered = {q["source_id"] for q in qs if q["when_off"].get("behavior") == "pass_through"}
        missing = UNLOCKABLE_SOURCES - covered
        assert (
            not missing
        ), f"Unlockable sources missing a pass_through regression question: {missing}"

    def test_multiple_personas_represented(self) -> None:
        qs = _load_fixture()
        personas = {q["persona"] for q in qs}
        assert len(personas) >= 3, f"Fixture should represent >= 3 personas, only has: {personas}"
