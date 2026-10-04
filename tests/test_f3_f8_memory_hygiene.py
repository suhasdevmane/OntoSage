# -*- coding: utf-8 -*-
"""Memory-hygiene fixes from the QA-trial readiness plan (2026-10-02 / 2026-10-04).

F3: the session summary's older-notes slice must never go negative -- a conversation
shorter than the raw-recent window has no "older" turns at all, not a wrapped-around
slice of the newest ones.

F8: no orchestrator call site may name a method its target does not have. The specific
instance (`AgentMemoryService.detect_and_store_preferences`, called on every turn for
months, always failing, always swallowed at DEBUG) is removed; this also guards the class
of defect for every other `self.agent_memory.<method>` call site.

F1 (P1 PRIVACY, 2026-10-04): "openwebui_user" is main.py's resolve_forwarded_user()
least-privilege FALLBACK identity -- every request Open WebUI cannot attribute to a real
account shares this one id. Neither the cross-session memory WRITE nor the READ may use it:
writing lets a later unrelated tester retrieve it back, reading injects whatever a prior
unrelated tester asked (and the figures in its answer) into the current prompt.

F2 (2026-10-04): answer_summary is a cross-session memory, and session_summary's own
figure-free guarantee (publication_gate.redact_quantities) did not apply to it -- a measured
value from one session could resurface in a later one's prompt as if it were current. Fixed
at BOTH the store site (future writes) and the retrieve render (existing points already in
Qdrant), so the second half needs no backfill migration.
"""
import ast
import inspect
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]


def _older_slice(n_notes: int, skip: int):
    """Mirrors turn_memory.get_session_context's fixed slice logic, without a DB."""
    notes = list(range(n_notes))  # stand-ins; only the length/order matters here
    older = notes[: len(notes) - skip] if len(notes) > skip else []
    return older


class TestF3SessionSummarySlice:
    @pytest.mark.parametrize(
        "n_notes,skip,expected_len",
        [
            (0, 3, 0),
            (1, 3, 0),
            (2, 3, 0),
            (3, 3, 0),
            (4, 3, 1),
            (5, 3, 2),
            (6, 3, 3),
            (10, 3, 7),
        ],
    )
    def test_the_kept_count_is_monotonic_and_never_negative(self, n_notes, skip, expected_len):
        older = _older_slice(n_notes, skip)
        assert len(older) == expected_len
        assert len(older) >= 0

    def test_a_short_conversation_keeps_nothing_older(self):
        """The shape that was wrong live: a 2-turn conversation must not render any
        'older' turn at all -- not the first turn, not a wrapped slice of the last."""
        assert _older_slice(2, 3) == []
        assert _older_slice(1, 3) == []

    def test_the_fix_is_in_the_source(self):
        src = inspect.getsource(
            __import__(
                "orchestrator.services.turn_memory", fromlist=["TurnMemoryService"]
            ).TurnMemoryService.get_session_context
        )
        assert "notes[: len(notes) - skip] if len(notes) > skip else []" in src


class TestF8NoPhantomMemoryCalls:
    def test_detect_and_store_preferences_is_not_called(self):
        src = inspect.getsource(__import__("orchestrator.workflow._orchestrator", fromlist=["x"]))
        assert "detect_and_store_preferences" not in src

    def test_every_self_agent_memory_call_site_names_a_real_method(self):
        """The general guard: a call `self.agent_memory.<name>(...)` must name a method
        AgentMemoryService actually has, anywhere in the orchestrator workflow source."""
        from orchestrator.services.agent_memory import AgentMemoryService

        real_methods = {
            name
            for name, obj in inspect.getmembers(AgentMemoryService)
            if inspect.iscoroutinefunction(obj) or inspect.isfunction(obj)
        }

        src_path = REPO / "orchestrator" / "workflow" / "_orchestrator.py"
        tree = ast.parse(src_path.read_text(encoding="utf-8"))
        named = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "agent_memory"
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"
            ):
                named.add(node.attr)

        assert named, "expected at least one self.agent_memory.<method> call site"
        missing = named - real_methods
        assert not missing, f"orchestrator calls agent_memory methods that do not exist: {missing}"


class TestF1NoSharedFallbackMemory:
    def test_the_retrieve_site_excludes_the_fallback_identity(self):
        src = inspect.getsource(__import__("orchestrator.workflow._orchestrator", fromlist=["x"]))
        retrieve_idx = src.index("self.agent_memory.retrieve_context(")
        guard_idx = src.rindex("if (", 0, retrieve_idx)
        guard_block = src[guard_idx:retrieve_idx]
        assert 'state.user_id != "openwebui_user"' in guard_block

    def test_the_store_site_excludes_the_fallback_identity(self):
        src = inspect.getsource(__import__("orchestrator.workflow._orchestrator", fromlist=["x"]))
        store_idx = src.index("await self.agent_memory.store_success(")
        guard_idx = src.rindex("if self.agent_memory", 0, store_idx)
        guard_line = src[guard_idx : src.index("\n", guard_idx)]
        assert 'state.user_id != "openwebui_user"' in guard_line


class TestF2AnswerSummaryIsRedacted:
    def test_the_store_site_redacts_before_writing(self):
        src = inspect.getsource(__import__("orchestrator.workflow._orchestrator", fromlist=["x"]))
        store_idx = src.index("await self.agent_memory.store_success(")
        call_block = src[store_idx : store_idx + 400]
        assert "redact_quantities(final_response[:200])" in call_block

    def test_the_retrieve_render_redacts_on_read(self):
        from orchestrator.services import agent_memory as am_module

        src = inspect.getsource(am_module.AgentMemoryService.retrieve_context)
        assert "redact_quantities" in src

    def test_a_figure_does_not_survive_the_round_trip(self):
        """Functional, not just source-pinned: a stale reading must not be retrievable."""
        from orchestrator.services.publication_gate import has_quantitative_claim, redact_quantities

        raw = "CO2 was 816 ppm, within ASHRAE 62.1's 1100 ppm limit."
        rendered = f"Answer: {redact_quantities(raw[:120])}..."
        assert not has_quantitative_claim(rendered)
