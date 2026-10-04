# -*- coding: utf-8 -*-
"""D7-LIVE (QA-trial plan, 2026-10-03). Found verifying D7's own fix against the running
stack: "how do you know that?" -- the canonical provenance phrasing, which
answer_provenance.PROVENANCE_RE matches -- was being REWRITTEN by the co-reference step
into "How do you know the temperature in room 2.01?" before the routing contract ever saw
it, because "that" was treated as an entity needing resolution rather than as a reference
to the previous answer's reasoning. The rewritten text no longer matches the provenance
detector, so the question was misrouted to sensor_data and declined.

The same shape as lesson #188: a detector correct in isolation, never reached because an
earlier pipeline stage already transformed its input.
"""
import inspect

import pytest

from orchestrator.agents.dialogue_agent import DialogueAgent

pytestmark = pytest.mark.unit


def _src() -> str:
    return inspect.getsource(DialogueAgent.rewrite_to_standalone)


class TestAProvenanceQuestionSkipsTheRewriteEntirely:
    def test_the_guard_is_present_before_the_deterministic_resolvers(self):
        src = _src()
        assert "is_provenance_question(latest)" in src
        assert src.index("is_provenance_question(latest)") < src.index("resolve_report_reference,")

    def test_the_guard_fails_open_on_an_import_error(self):
        src = _src()
        idx = src.index("is_provenance_question(latest)")
        # the nearest preceding try: and a bare except that does not re-raise
        assert src.rindex("try:", 0, idx) < idx
        assert "except Exception:" in src[idx : idx + 400]
