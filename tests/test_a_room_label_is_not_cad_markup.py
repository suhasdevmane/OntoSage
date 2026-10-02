# -*- coding: utf-8 -*-
"""A CAD formatting directive is not a room name (BUG-1407).

THE DEFECT, live, tail O #58, occupant01 on /v1. "in this kitchen area, how much vampire power
do appliances draw after hours?" returned a spatial table whose Label column read:

    | 4 | `0.16` | \\pxqc;{\\fArial|b0|i0|c0|p34;\\H1.6x;0.16\\P\\H0.625x;Kitchen} | kitchen | — |

That is AutoCAD MTEXT markup — paragraph alignment, font, height multipliers — shown to a reader
as the name of a room.

MEASURED across this repository's floor-plan manifests: **26 of 354 spaces** carry such codes in
their stored label. The DWG pipeline has always stripped them at INGEST; the manifests on disk
predate that (or were written by another path) and nothing stripped them on the way OUT.

So the strip now lives in `shared.utils.strip_drawing_markup` and is applied by the `Space`
model itself. `dwg_pipeline._strip_mtext_codes` delegates to the same function, so the ingest
and the read cannot disagree about what a label is — the mistake BUG-947 and BUG-1396 both came
down to.

EVERY MARKED-UP STRING IN THIS FILE IS BUILT WITH EXPLICIT BACKSLASH ESCAPES, never typed
through a shell. Four separate times this session a `\\f` arrived as a form feed and a test
measured a string the data does not contain (lesson #125).
"""

import json
from pathlib import Path

import pytest

from shared.models import Space
from shared.utils import strip_drawing_markup

pytestmark = pytest.mark.unit

#: Built from parts so no escape can be mangled in transit. This is the tail O #58 label.
KITCHEN = "\\pxqc;{\\fArial|b0|i0|c0|p34;\\H1.6x;0.16\\P\\H0.625x;Kitchen}"
BOARDROOM = "\\pxqc;{\\fArial|b0|i0|c0|p34;\\H1.6x;0.18\\P\\H0.625x;Boardroom}"
AREA = "\\A1;1233.56 m{\\H0.7x;\\S2^ ;}"


class TestTheMarkupIsStripped:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (KITCHEN, "0.16 Kitchen"),
            (BOARDROOM, "0.18 Boardroom"),
            ("\\pxqc;{\\fArial|b0|i0|c0|p34;0.17\\PStore}", "0.17 Store"),
            (AREA, "1233.56 m"),
        ],
    )
    def test_the_words_survive_and_the_codes_do_not(self, raw, expected):
        assert strip_drawing_markup(raw) == expected

    @pytest.mark.parametrize("plain", ["Room 1.06", "Kitchen", "Meeting Room 2", "0.16", ""])
    def test_a_plain_label_is_untouched(self, plain):
        assert strip_drawing_markup(plain) == plain

    def test_none_is_tolerated(self):
        assert strip_drawing_markup(None) == ""

    def test_no_backslash_or_brace_survives(self):
        for raw in (KITCHEN, BOARDROOM, AREA):
            out = strip_drawing_markup(raw)
            assert "\\" not in out and "{" not in out and "}" not in out, out
            assert "pxqc" not in out and "Arial" not in out, out


class TestTheModelAppliesIt:
    """The chokepoint: every consumer validates through `Space`, so no reader can leak it."""

    def test_a_space_label_is_cleaned_on_construction(self):
        sp = Space(id="b.0.16", zone_id="0.16", label=KITCHEN)
        assert sp.label == "0.16 Kitchen"

    def test_aliases_are_cleaned_too(self):
        sp = Space(id="b.0.16", zone_id="0.16", label="Kitchen", aliases=[KITCHEN, "Galley"])
        assert sp.aliases == ["0.16 Kitchen", "Galley"]

    def test_a_clean_label_is_preserved_exactly(self):
        sp = Space(id="b.1.06", zone_id="1.06", label="Room 1.06 — Computer Laboratory")
        assert sp.label == "Room 1.06 — Computer Laboratory"


class TestTheIngestAndTheReadAgree:
    def test_the_pipeline_delegates_to_the_shared_function(self):
        """Two definitions of one judgement is how BUG-947 happened; there is one here."""
        import inspect

        from orchestrator.services.dwg_pipeline import _strip_mtext_codes

        assert _strip_mtext_codes(KITCHEN) == strip_drawing_markup(KITCHEN)
        src = inspect.getsource(_strip_mtext_codes)
        assert "strip_drawing_markup" in src, (
            "the DWG pipeline has its own copy of the strip again; the ingest and the read can "
            "now disagree about what a label is"
        )


class TestAgainstTheRealManifests:
    """The measurement that justified the fix, as a test rather than a claim."""

    def test_no_stored_label_survives_the_strip_with_markup_intact(self):
        root = Path(__file__).resolve().parents[1] / "volumes"
        manifests = sorted(root.glob("*/floor-plans/*/*.manifest.json"))
        if not manifests:
            pytest.skip("no floor-plan manifests in this checkout")
        total = marked = 0
        for path in manifests:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            for sp in data.get("spaces") or []:
                total += 1
                raw = str(sp.get("label") or "")
                if "\\" in raw or "{" in raw:
                    marked += 1
                    out = strip_drawing_markup(raw)
                    assert "\\" not in out and "{" not in out, (path.name, raw[:60], out)
        assert total, "manifests found but no spaces in them"
