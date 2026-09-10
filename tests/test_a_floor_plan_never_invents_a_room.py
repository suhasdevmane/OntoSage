# -*- coding: utf-8 -*-
"""A room number the building may not have is the worst thing to invent (BUG-444).

WHAT WENT WRONG
---------------
`FloorPlanService.get_zones_for_floor` mined the floor plan's PDF text for room numbers,
and when extraction returned nothing it GENERATED them:

    zones = [f"{floor}.{n:02d}" for n in range(1, 15)]

Fourteen identifiers, offered to the user under the heading *"Known zones on Floor N"*.

Two design contracts, broken in one line.

**Contract 4 -- never fabricate.** Most fabrications produce a wrong number. This one
produces a wrong PLACE, and a reader acts on a place: they walk to it, they book it, they
send an engineer to it. The fabrication is also unfalsifiable from the answer itself, since
"3.07" looks exactly like every real room in this particular building.

**Contract 3 -- no building literals.** It invents in ONE BUILDING'S GRAMMAR. A building
numbering rooms `RM-204`, or naming them `Atrium` and `Long Gallery`, would have been told
about rooms called "3.01" through "3.14".

An empty list is a true statement, and the caller already handles it: it asks which room
the user means rather than listing invented ones.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services import floor_plan_service as fps  # noqa: E402


class _NoText(fps.FloorPlanService):
    """A service whose plan text cannot be read -- the case that used to fabricate."""

    def __init__(self):  # no super().__init__: this test needs no Qdrant, no PDFs
        pass

    def get_pdf_text(self, floor):  # noqa: D401
        return ""


class _WithText(_NoText):
    def __init__(self, text: str):
        self._text = text

    def get_pdf_text(self, floor):
        return self._text


def test_an_unreadable_plan_yields_no_zones_rather_than_invented_ones():
    """The load-bearing case."""
    assert _NoText().get_zones_for_floor(3) == []


def test_zones_come_from_the_plan_when_the_plan_can_be_read():
    svc = _WithText("Room 3.01 Lab · 3.02 Office · 3.14 Store · Floor 4.01 is elsewhere")
    got = svc.get_zones_for_floor(3)
    assert got == ["3.01", "3.02", "3.14"]
    assert "4.01" not in got, "a zone from another floor was swept in"


def _code_without_docstrings(module) -> str:
    """The module's source with every docstring blanked out.

    Needed because the fix's own docstring QUOTES the fabricating line in order to explain
    it, and the first version of the test below duly failed on that explanation. A checker
    that reads its own documentation is a checker that gets deleted rather than fixed --
    the same mistake, on the same day, as the status checker that reported its own header
    comment as a defect.
    """
    import ast

    src = inspect.getsource(module)
    tree = ast.parse(src)
    lines = src.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = node.body[0] if node.body else None
        if (
            isinstance(doc, ast.Expr)
            and isinstance(doc.value, ast.Constant)
            and isinstance(doc.value.value, str)
        ):
            for i in range(doc.lineno - 1, doc.end_lineno):
                lines[i] = ""
    return chr(10).join(lines)


def test_no_room_identifier_is_constructed_anywhere_in_the_module():
    """The specific line, pinned by shape rather than by behaviour.

    A future edit could reintroduce the fallback under a different guard and every
    behavioural test above would still pass, because they only exercise one path.
    """
    code = _code_without_docstrings(fps)
    assert 'f"{floor}.{n:02d}"' not in code, (
        "a room identifier is being CONSTRUCTED from a floor number again; whatever it is "
        "for, the result is a place the building may not have, spelled in one building's "
        "grammar"
    )
    assert "range(1, 15)" not in code, "the invented-room range is back"


def test_the_docstring_filter_actually_removes_something():
    """A filter that silently matched nothing would make the test above vacuous."""
    assert 'f"{floor}.{n:02d}"' in inspect.getsource(fps), (
        "the explanation of the defect has gone from the module; without it the next "
        "reader has no idea why the fallback must not come back"
    )


def test_the_caller_handles_an_empty_zone_list():
    """Deleting the fabrication is only safe because the empty branch already existed."""
    svc = _NoText()
    svc.get_pdf_url = lambda floor, absolute=False: "http://example/plan.pdf"
    out = svc.build_disambiguation_prompt(3, zones=[])
    assert "Known zones" not in out, "an empty list must not render as a zone list"
    assert "Which room or zone" in out
