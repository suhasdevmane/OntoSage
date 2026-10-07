# -*- coding: utf-8 -*-
"""The MTEXT decoder's grammar, exercised directly (BUG-1407, instance #58).

This repeats and extends `tests/test_a_room_label_is_not_cad_markup.py` on purpose: that file
is the chokepoint test (the `Space` model strips on load, so no reader can reintroduce the
leak); this file is the DECODER's own contract, independent of the model that happens to call
it, and adds a shape the other file does not cover (three `\\P` breaks in one label).

**A correction to the tracker's own phrasing, checked against the code rather than assumed.**
BUG-1407's row describes instance #58's string and says "the label should be the decoded text
('Kitchen')". Read literally that would mean DISCARDING `0.16` -- but `0.16` is not an MTEXT
control code. The grammar is:

    \\pxqc;              a paragraph-property directive (alignment) -- CONTROL, dropped
    {                    a format-override group open -- CONTROL, dropped
    \\fArial|b0|i0|c0|p34;  a font directive -- CONTROL, dropped
    \\H1.6x;             a height directive (1.6x) -- CONTROL, dropped
    0.16                 LITERAL TEXT at that height
    \\P                  a paragraph break -- CONTROL, becomes a space
    \\H0.625x;           a second height directive (0.625x) -- CONTROL, dropped
    Kitchen              LITERAL TEXT at that height
    }                    group close -- CONTROL, dropped

`0.16` sits between two directives and is not itself one: it is a second line of literal text
(the room's `zone_id`, matching `Space(zone_id="0.16", ...)` in the companion test), rendered
at a different height than the name below it -- the standard room-tag convention of a number
over a name. A decoder that throws it away is not decoding MTEXT, it is guessing which of two
literal lines a human wanted and discarding the other -- exactly the kind of silent data loss
`CLAUDE.md` design contract #4 rules out ("never surface a plausible-but-wrong value" cuts both
ways: dropping a real value is not safer than inventing one). The shipped, live-verified fix
(`shared.utils.strip_drawing_markup`, applied by the `Space` model) already gets this right and
returns "0.16 Kitchen" -- this file asserts that behaviour explicitly, rather than the tracker
row's shorthand.

EVERY MARKED-UP STRING HERE IS BUILT WITH EXPLICIT BACKSLASH ESCAPES, never typed through a
shell -- a `\\f` arriving as a form feed is lesson #125, confirmed again while drafting this
file (a `bash -c` string mangled it on the first attempt).
"""

from __future__ import annotations

import pytest

from shared.utils import strip_drawing_markup

pytestmark = pytest.mark.unit

#: Tracker BUG-1407 instance #58, verbatim.
KITCHEN = "\\pxqc;{\\fArial|b0|i0|c0|p34;\\H1.6x;0.16\\P\\H0.625x;Kitchen}"

#: A second shape with THREE `\P` breaks (four literal segments), not covered by the
#: companion test file: a number line followed by a name split across two more lines
#: ("Open", "Plan", "Office" -- a compound room name AutoCAD wrapped onto separate lines).
MULTI_PARAGRAPH = "\\pxqc;{\\fArial|b0|i0|c0|p34;\\H1.4x;3.02\\P\\H0.6x;Open\\PPlan\\POffice}"


class TestTheDecodersGrammar:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (KITCHEN, "0.16 Kitchen"),
            (MULTI_PARAGRAPH, "3.02 Open Plan Office"),
        ],
    )
    def test_control_codes_are_removed_and_literal_text_survives(self, raw, expected):
        assert strip_drawing_markup(raw) == expected

    @pytest.mark.parametrize("raw", [KITCHEN, MULTI_PARAGRAPH])
    def test_no_backslash_or_brace_control_code_remains(self, raw):
        out = strip_drawing_markup(raw)
        assert "\\" not in out
        assert "{" not in out and "}" not in out
        # The directive bodies themselves must be gone too, not merely the backslash.
        assert "pxqc" not in out
        assert "Arial" not in out
        assert "b0" not in out and "i0" not in out and "c0" not in out and "p34" not in out
        assert "1.6x" not in out and "0.625x" not in out and "1.4x" not in out and "0.6x" not in out

    def test_multiple_paragraph_breaks_collapse_to_single_spaces(self):
        """Three `\\P`s must not leave double spaces or run words together."""
        out = strip_drawing_markup(MULTI_PARAGRAPH)
        assert "  " not in out
        assert out == "3.02 Open Plan Office"
