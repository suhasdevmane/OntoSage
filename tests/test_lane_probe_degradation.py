# -*- coding: utf-8 -*-
"""A run with a dead model is INVALID, not low-scoring (2026-08-28).

Ollama died part-way through bldg1's evidence-lane probe. The probe reported 9/10 with
the deliberate lane marked FAIL-CLOSED, and I began diagnosing that lane — querying its
sensor coverage, checking a class hierarchy — before a third phrasing happened to return
the real answer: "LLM circuit breaker is OPEN — the ollama provider has been
unresponsive."

The provider had died AFTER the preflight passed, which is precisely BUG-177: `/health`
is green, the container is up, and the fallback text reads enough like an answer to be
graded as one. `capture_golden_baseline`, `corpus_replay` and `leak_benchmark` all
quarantine on the `llm_degraded` field the API sets per turn. This probe did not.

Two properties are pinned:

* a degraded turn never counts as a pass, and
* the run says INVALID in its own output and exits distinctly, because "9/10" and
  "9/10, and the model was dead for one of them" are not the same claim.
"""

import importlib.util
import inspect
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]


def _src() -> str:
    path = _REPO / "scripts" / "probe_evidence_lanes.py"
    spec = importlib.util.spec_from_file_location("_probe", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return inspect.getsource(mod.main)


def test_a_degraded_turn_cannot_pass():
    src = _src()
    assert 'degraded = bool(data.get("llm_degraded"))' in src, "the field is not read"
    assert "not degraded" in src, "a degraded turn can still be scored ok"


def test_a_degraded_turn_is_labelled_as_such():
    """Not as FAIL-CLOSED. Mislabelling it is what sent me diagnosing the wrong thing."""
    assert '"DEGRADED"' in _src()


def test_the_run_declares_itself_invalid_in_its_own_output():
    """In the artifact, not in a log nobody re-reads — the rule this project already
    wrote down and had never enforced here."""
    src = _src()
    assert "INVALID RUN" in src
    assert "do not publish this number" in src


def test_invalid_and_failed_exit_differently():
    """They call for different actions: re-run once the provider is healthy, versus
    diagnose the lane. Collapsing them is how a dead model gets investigated as a
    defect."""
    src = _src()
    assert "return 3" in src
    assert "if quarantined:" in src


def test_the_other_harnesses_already_did_this():
    """If one of these stops quarantining, this test says so — the point is that the
    behaviour is uniform, not that three scripts happen to share a habit."""
    for name in ("capture_golden_baseline.py", "corpus_replay.py", "leak_benchmark.py"):
        text = (_REPO / "scripts" / name).read_text(encoding="utf-8")
        assert "llm_degraded" in text, f"{name} no longer checks for a degraded provider"
