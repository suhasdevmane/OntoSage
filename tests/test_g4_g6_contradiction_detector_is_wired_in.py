# -*- coding: utf-8 -*-
"""G4/G6 (2026-10-04): `narration_contradiction.log_contradictions` must be called inside
`_response_node`, AFTER the inline evidence panel is appended (so it inspects the text the
reader actually sees) and BEFORE the message/response-cache writes, wrapped so a failure
inside it can never affect `final_response`.

Source-pinned, matching this repo's convention for `_response_node` wiring (e.g.
`tests/test_d11_panel_is_wired_into_response_node.py`), because the node has no isolated
test fixture to drive directly.
"""
import inspect

import pytest

from orchestrator.workflow._orchestrator import WorkflowOrchestrator

pytestmark = pytest.mark.unit


def _src() -> str:
    return inspect.getsource(WorkflowOrchestrator._response_node)


class TestItCallsTheRealDetectorNotAReimplementation:
    def test_log_contradictions_is_imported_and_called(self):
        src = _src()
        assert "from orchestrator.services.narration_contradiction import log_contradictions" in src
        assert "log_contradictions(logger, final_response)" in src

    def test_no_contradiction_logic_is_reimplemented_in_this_node(self):
        assert "def log_contradictions" not in _src()
        assert "def compliance_contradiction" not in _src()
        assert "def range_contradiction" not in _src()


class TestItSitsAfterThePanelAndBeforeTheCacheWrite:
    def test_the_call_comes_after_the_inline_panel_block(self):
        src = _src()
        assert src.index("_render_evidence(") < src.index("log_contradictions(logger")

    def test_the_call_comes_before_messages_append(self):
        src = _src()
        assert src.index("log_contradictions(logger") < src.index("state.messages.append(")


class TestItFailsOpenAndNeverTouchesTheAnswer:
    def test_the_call_is_wrapped_in_a_bare_try_except(self):
        src = _src()
        call_idx = src.index("log_contradictions(logger")
        try_idx = src.rindex("try:", 0, call_idx)
        except_idx = src.index("except", call_idx)
        assert try_idx < call_idx < except_idx

    def test_final_response_is_never_reassigned_between_the_call_and_the_except(self):
        src = _src()
        call_idx = src.index("log_contradictions(logger")
        except_idx = src.index("except", call_idx)
        between = src[call_idx:except_idx]
        assert "final_response =" not in between
        assert "final_response +=" not in between
