# -*- coding: utf-8 -*-
"""D11/D16/D18 of the QA-trial readiness plan (2026-10-02): `answer_provenance.render()`
grows an `inline` mode so the SAME renderer -- not a second one (that is the BUG-947 shape)
-- can also produce the evidence panel appended to every figure-bearing answer, rather than
only the follow-up read-back of a past turn.

D16: a cache-replayed answer must say so, not show a true timestamp with a false
implication that this turn re-read the store.
D18: an inline panel with nothing to say is omitted, like `render_dossier_details`'s own
"an empty working-out is not working-out" rule -- a FOLLOW-UP question still gets the full
(possibly sparse) read-back, because that is a direct answer to a direct question.
"""
import pytest

from orchestrator.services.answer_provenance import render

pytestmark = pytest.mark.unit

RECORD = {
    "status": "observed",
    "operation": "observation",
    "sources": [{"source_id": "u1", "label": "Temperature Sensor", "kind": "sensor"}],
    "latest_evidence_at": "2026-10-02T12:00:00",
    "retrieved_at": "2026-10-02T12:00:05",
    "source_tier": "measurement",
}


class TestInlineModeDiffersFromTheFollowUpReadBack:
    def test_the_heading_speaks_of_this_answer_not_that_one(self):
        inline_text = render(RECORD, inline=True)
        follow_up_text = render(RECORD, inline=False)
        assert "this answer" in inline_text
        assert "that answer" in follow_up_text

    def test_only_the_inline_panel_is_wrapped_in_a_details_block(self):
        inline_text = render(RECORD, inline=True)
        follow_up_text = render(RECORD, inline=False)
        assert '<details type="evidence">' in inline_text
        assert "<summary>How I know this</summary>" in inline_text
        assert "</details>" in inline_text
        assert "<details" not in follow_up_text

    def test_the_backward_looking_closing_sentence_is_only_on_the_follow_up(self):
        inline_text = render(RECORD, inline=True)
        follow_up_text = render(RECORD, inline=False)
        assert "not a reconstruction after the fact" in follow_up_text
        assert "not a reconstruction after the fact" not in inline_text

    def test_default_is_the_follow_up_shape(self):
        """No caller is forced to pass inline= explicitly; the old behaviour is unchanged."""
        assert render(RECORD) == render(RECORD, inline=False)


class TestD6SourceTierIsPrinted:
    def test_the_leading_tier_is_named(self):
        text = render(RECORD, inline=True)
        assert "measurement" in text
        assert "Kind of source that led" in text

    def test_no_tier_means_no_line(self):
        rec = dict(RECORD)
        rec.pop("source_tier")
        text = render(rec, inline=True)
        assert "Kind of source that led" not in text


class TestD16CacheReplayIsDisclosed:
    def test_a_cache_hit_says_nothing_was_re_read(self):
        rec = dict(RECORD, served_from_cache=True)
        text = render(rec, inline=True)
        assert "replayed from a cached result" in text
        assert "nothing was re-read" in text

    def test_a_fresh_turn_says_nothing_of_the_kind(self):
        text = render(RECORD, inline=True)
        assert "replayed from a cached result" not in text


class TestD18EmptyPanelsAreOmitted:
    def test_a_record_with_nothing_to_say_renders_no_inline_panel(self):
        assert render({}, inline=True) is None  # no record at all: None, not ""
        assert render({"status": "", "operation": ""}, inline=True) == ""

    def test_the_same_empty_record_still_gets_a_follow_up_answer(self):
        """A direct question about an empty record is still answered directly -- the
        suppression is only for the UNPROMPTED inline panel."""
        text = render({"status": "", "operation": ""}, inline=False)
        assert text  # not empty -- the heading and closing sentence are still a real answer

    def test_a_record_with_only_a_source_is_not_suppressed(self):
        text = render(RECORD, inline=True)
        assert text  # has sources, a status, a tier -- real content, must render
