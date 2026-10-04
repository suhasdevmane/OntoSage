# -*- coding: utf-8 -*-
"""BUG-1430 / G7 (QA-trial plan, 2026-10-04): 'How much energy did the building use
yesterday?' declined; 'and the day before?' then answered YESTERDAY's window, narrated as
'the day before', with its own caveat that it does not cover the day it names.

Root cause: the bare follow-up had no deterministic resolver and fell to the LLM's
free-form rewrite (CAVEAT-891 -- non-deterministic by nature), which could turn it into
"...the day before yesterday?" -- a phrase that CONTAINS the word "yesterday", so the old
unordered `_CALENDAR_DAYS` check matched that substring and resolved one day back instead
of two.

Fix, two parts, both covered here: (1) `resolve_relative_day_followup` rewrites the bare
follow-up deterministically from the PREVIOUS question, never reaching the LLM for this
shape at all; (2) `_CALENDAR_DAYS` is now checked longest-phrase-first so even an LLM
rewrite that does say "the day before yesterday" resolves correctly (covered separately in
tests/test_a_named_day_is_a_date_not_a_duration.py::TestG7TheDayBeforeYesterdayIsTwoDaysNotOne).
"""
import pytest

from orchestrator.services.context_switch import resolve_relative_day_followup

pytestmark = pytest.mark.unit


class TestTheBareFollowUpIsRewrittenDeterministically:
    def test_and_the_day_before_after_a_question_about_yesterday(self):
        out = resolve_relative_day_followup(
            "and the day before?", "How much energy did the building use yesterday?"
        )
        assert out == "How much energy did the building use the day before yesterday?"

    def test_the_day_before_after_a_question_about_today(self):
        out = resolve_relative_day_followup("the day before?", "What was the CO2 level today?")
        assert out == "What was the CO2 level yesterday?"

    def test_what_about_the_day_before_phrasing(self):
        out = resolve_relative_day_followup(
            "what about the day before?", "How much energy did the building use yesterday?"
        )
        assert out == "How much energy did the building use the day before yesterday?"

    def test_the_day_before_that_phrasing(self):
        out = resolve_relative_day_followup(
            "the day before that?", "How much energy did the building use yesterday?"
        )
        assert out == "How much energy did the building use the day before yesterday?"

    def test_the_previous_day_phrasing(self):
        out = resolve_relative_day_followup(
            "the previous day?", "How much energy did the building use yesterday?"
        )
        assert out == "How much energy did the building use the day before yesterday?"


class TestItDoesNotGuessBeyondWhatIsDefined:
    def test_asking_for_the_day_before_the_day_before_yesterday_declines(self):
        """BUG-540's own caution: no phrase is defined for three days back, so this must
        not silently invent one."""
        out = resolve_relative_day_followup(
            "and the day before?", "energy use the day before yesterday?"
        )
        assert out is None

    def test_a_previous_question_naming_no_calendar_day_declines(self):
        out = resolve_relative_day_followup("and the day before?", "how warm is room 5.01?")
        assert out is None

    def test_an_empty_previous_question_declines(self):
        assert resolve_relative_day_followup("and the day before?", "") is None


class TestItIsNarrowAndLeavesRicherFollowUpsToTheLlm:
    def test_extra_content_in_the_latest_message_is_not_matched(self):
        """'and the day before, for floor 3?' carries new content this resolver must not
        silently drop -- the LLM rewrite handles it instead."""
        out = resolve_relative_day_followup(
            "and the day before, for floor 3?", "How much energy did the building use yesterday?"
        )
        assert out is None

    def test_an_unrelated_follow_up_is_not_matched(self):
        assert resolve_relative_day_followup("what about floor 3?", "energy use yesterday?") is None


class TestItIsWiredIntoTheRewriteChain:
    def test_the_resolver_is_imported_and_called_in_rewrite_to_standalone(self):
        import inspect

        from orchestrator.agents.dialogue_agent import DialogueAgent

        src = inspect.getsource(DialogueAgent.rewrite_to_standalone)
        assert "resolve_relative_day_followup" in src
        assert "_previous_user_q" in src

    def test_it_runs_before_the_llm_rewrite_not_after(self):
        import inspect

        from orchestrator.agents.dialogue_agent import DialogueAgent

        src = inspect.getsource(DialogueAgent.rewrite_to_standalone)
        assert src.index("resolve_relative_day_followup") < src.index("llm_manager.generate(")
