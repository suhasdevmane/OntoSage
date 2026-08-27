# -*- coding: utf-8 -*-
"""The Observability tab and the endpoints behind it (V6-T11, 2026-08-27).

The conversational lane has answered "can you measure formaldehyde in 5.01?" from
the coverage matrix since V6-T10. The portal had no way to SEE that matrix, so an
operator could not find out what their building could answer with except by asking
it one question at a time.

The design constraint that shaped this: the tab reads the SAME coverage schema and
the same `Reach` the lane answers from. Not a second computation of the same idea.
Two copies of one measurement drift -- BUG-210 in this repo was exactly that -- and
a portal disagreeing with the chat answer is worse than no portal, because it looks
authoritative while contradicting the system.
"""

import inspect
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]
_MAIN = (_REPO / "orchestrator" / "main.py").read_text(encoding="utf-8")
_TAB = _REPO / "frontend" / "src" / "components" / "admin" / "ObservabilityTab.js"
_PORTAL = _REPO / "frontend" / "src" / "pages" / "AdminPortal.js"


def _endpoint_body(path: str) -> str:
    """Everything from this route's decorator to the NEXT route's.

    Not a fixed character count. A 4,000-char slice cut this endpoint off before its
    own truncation logic and reported a missing field that was right there - the
    same brittle-slice mistake that made a neighbouring test fail on length rather
    than behaviour (see tests/test_ticket_universe.py).
    """
    idx = _MAIN.index(f'"{path}"')
    rest = _MAIN[idx:]
    boundaries = [i for i in (rest.find("\n@app."), rest.find("\n@router.")) if i > 0]
    return rest[: min(boundaries)] if boundaries else rest


# ── the endpoints exist and are admin-gated ──────────────────────────────────
@pytest.mark.parametrize(
    "path",
    ["/api/v1/admin/observability/matrix", "/api/v1/admin/observability/calibration"],
)
def test_the_endpoint_exists_and_requires_admin(path):
    body = _endpoint_body(path)
    assert 'require_permission("system:admin")' in body


def test_the_matrix_reuses_the_lane_and_does_not_recompute_coverage():
    """A second implementation of 'what can this building observe' would drift from
    the one the chat answers with."""
    body = _endpoint_body("/api/v1/admin/observability/matrix")
    assert "build_schema" in body
    assert "reach_from_coverage" in body


def test_every_cell_carries_the_step_that_would_change_it():
    """A matrix of red cells an operator cannot act on is decoration."""
    body = _endpoint_body("/api/v1/admin/observability/matrix")
    assert "reach.describe()" in body


def test_the_cell_list_is_bounded_and_says_what_it_cut():
    """bldg1 is ~344 spaces by ~35 modalities: twelve thousand cells. A list that
    silently stops reads as the whole picture."""
    body = _endpoint_body("/api/v1/admin/observability/matrix")
    assert '"truncated"' in body
    assert "min(int(limit or 300), 2000)" in body


def test_the_summary_is_complete_even_when_the_cells_are_truncated():
    """Counting must happen before the limit, or the totals describe the page
    rather than the building."""
    body = _endpoint_body("/api/v1/admin/observability/matrix")
    count_at = body.index("by_status[reach.status]")
    trunc_at = body.index("if len(cells) <")
    assert count_at < trunc_at


# ── calibration agrees with the gate ─────────────────────────────────────────
def test_calibration_state_is_read_through_the_gate_helper():
    """The gate that suppresses an answer and the panel that explains why must agree
    about what 'expired' means."""
    body = _endpoint_body("/api/v1/admin/observability/calibration")
    assert "_calibration_state" in body


def test_the_calibration_entry_uses_the_keys_the_helper_reads():
    """_calibration_state reads "due_on". Passing "calibration_due_on" would make
    every record read calibrated-or-unknown and NEVER expired -- the panel would show
    a clean building while the gate suppressed answers. Same class of defect as the
    sparql_result / sparql_results drift that blanked two lanes' evidence."""
    from orchestrator.services.evidence.assemble import _calibration_state

    src = inspect.getsource(_calibration_state)
    assert 'entry.get("due_on")' in src
    body = _endpoint_body("/api/v1/admin/observability/calibration")
    assert '"due_on": str(get("due")' in body


def test_an_absent_calibration_record_is_unknown_not_assumed_good():
    from datetime import datetime, timezone

    from orchestrator.services.evidence.assemble import _calibration_state

    assert _calibration_state({}, datetime.now(timezone.utc)) == "unknown"
    assert _calibration_state(None, datetime.now(timezone.utc)) == "unknown"


def test_the_calibration_note_says_what_is_missing_from_the_table():
    """Points with no record simply do not appear; without saying so, the table
    reads as the whole sensor population."""
    body = _endpoint_body("/api/v1/admin/observability/calibration")
    assert "never as calibrated" in body


# ── the tab ──────────────────────────────────────────────────────────────────
def test_the_tab_component_exists():
    assert _TAB.is_file()


def test_the_tab_is_registered_in_the_portal():
    """A component nobody renders is the recurring defect in this codebase."""
    portal = _PORTAL.read_text(encoding="utf-8")
    assert "import ObservabilityTab" in portal
    assert "{ id: 'observability', label: 'Observability' }" in portal
    assert "{tab === 'observability' && <ObservabilityTab {...props} />}" in portal


def test_the_portal_has_twelve_tabs():
    """V6-T11 calls it the 12th tab; if that count drifts, one of them is unreachable."""
    portal = _PORTAL.read_text(encoding="utf-8")
    assert portal.count("{ id: '") == 12


def test_the_tab_renders_the_unlock_step_not_just_the_status():
    tab = _TAB.read_text(encoding="utf-8")
    assert "What would change it" in tab
    assert "c.note" in tab


def test_the_tab_says_when_it_truncated():
    tab = _TAB.read_text(encoding="utf-8")
    assert "more not shown" in tab


def test_a_calibration_failure_does_not_blank_the_matrix():
    """They answer different questions, and one being unreadable is not the other
    being wrong."""
    tab = _TAB.read_text(encoding="utf-8")
    assert "unaffected" in tab
    assert "cj.success ?" in tab
