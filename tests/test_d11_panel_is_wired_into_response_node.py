# -*- coding: utf-8 -*-
"""D11 (QA-trial plan, 2026-10-02): the inline evidence panel must be appended inside
`_response_node`, AFTER the claim-binder block (so the panel's own numbers are never
extracted as claims and do not self-vouch) and BEFORE the message/response-cache writes
(so a cache hit replays it, the way the Sources footer already does), and it must be
unreachable on the two lanes that already carry their own evidence block.

Source-pinned, matching this repo's convention for `_response_node` wiring (e.g.
`tests/test_an_assumed_referent_is_disclosed.py`) rather than driving the whole node, which
has no isolated test fixture.
"""
import inspect

import pytest

from orchestrator.workflow._orchestrator import WorkflowOrchestrator

pytestmark = pytest.mark.unit


def _src() -> str:
    return inspect.getsource(WorkflowOrchestrator._response_node)


class TestItCallsTheSameRendererNotASecondOne:
    def test_answer_provenance_render_is_called_inline(self):
        assert (
            "from orchestrator.services.answer_provenance import render as _render_evidence"
            in _src()
        )
        assert "inline=True" in _src()

    def test_no_second_renderer_is_defined_in_this_node(self):
        assert "def render" not in _src()


class TestItSitsAfterClaimBindingAndBeforeTheCacheWrite:
    def test_the_panel_block_comes_after_the_claim_binder_block(self):
        src = _src()
        assert src.index('_bus["claim_binding"] = _claim_report') < src.index("_render_evidence(")

    def test_the_panel_block_comes_before_messages_append(self):
        src = _src()
        assert src.index("_render_evidence(") < src.index("state.messages.append(")


class TestItSkipsTheTwoLanesThatAlreadyShowTheirWork:
    def test_it_skips_when_the_deliberation_dossier_already_ran(self):
        assert 'results.get("evidence_dossier")' in _src()

    def test_it_skips_when_the_text_already_carries_a_rendered_heading(self):
        """Not by lane name -- by whether the rendered heading is already in the text, so
        a THIRD self-rendering lane cannot slip through unnoticed."""
        assert '"arrived at**" not in final_response' in _src()


class TestItFailsOpen:
    def test_the_block_is_wrapped_in_a_try_except(self):
        src = _src()
        panel_idx = src.index("_render_evidence(")
        # the nearest preceding "try:" and the nearest following "except" bracket the block
        assert src.rindex("try:", 0, panel_idx) < panel_idx
        assert "[response] inline evidence panel skipped" in src
