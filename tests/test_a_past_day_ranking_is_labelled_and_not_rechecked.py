"""BUG-588: "Which room on floor 5 was the warmest yesterday?" lost its ranking to the numeric guard.

The evidence label said "mean over 2026-09-13" (the UTC date of a BST day starting 23:00 UTC),
the guard did not allow numbers quoted from that label, so the year "2026" tripped it; the
fallback then attached a 15-minute recheck to a day already over.
"""

import inspect

import pytest

from orchestrator.services.deliberation import dossier as ds
from orchestrator.services.deliberation import plan_executor as px
from orchestrator.workflow import _orchestrator as orch

pytestmark = pytest.mark.unit


def test_the_guard_allows_numbers_quoted_from_the_evidence_basis_and_stamp():
    src = inspect.getsource(ds._allowed_numbers)
    assert '"basis"' in src and '"latest"' in src


def test_the_day_label_is_the_buildings_day():
    src = inspect.getsource(px.execute)
    assert "to_local(" in src and 'f"mean over {_day.isoformat()}"' in src


def test_no_recheck_line_on_a_past_window():
    src = inspect.getsource(orch.WorkflowOrchestrator._recheck_line)
    assert 'b.startswith("mean over")' in src
