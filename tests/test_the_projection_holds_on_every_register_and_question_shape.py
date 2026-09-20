# -*- coding: utf-8 -*-
"""2D-06: the projection never crashes, and never prints a placeholder, on any register.

Every entry point of ``register_projection`` catches its own exceptions and falls back to the
narration — which is exactly why a crash would go unseen: the answer would quietly get worse. So
this drives the UNWRAPPED functions (``resolve``, ``_compose``) over every register the building
holds and a spread of question shapes, and checks what comes out:

* nothing raises;
* an answer never contains a placeholder (``None``, ``nan``, a bare ``?``, a dict or list repr),
  an internal field name, or a word that calls the data simulated;
* every record an answer names is a record of THAT register, and no record is named twice in one
  list (a partition, not a pile).
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from orchestrator.services import register_projection as rp
from tests.register_fixture_rows import document_names, lifted_rows

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 19)

QUESTIONS = [
    "Which records are overdue?",
    "How many records are open?",
    "Which are defective?",
    "Who owns them?",
    "Who owns the active records?",
    "When is the next test due?",
    "When was it last checked?",
    "When was the last one completed?",
    "Which records are completed and who owns them?",
    "Where are the active ones?",
    "How many are active?",
    "What is the location of the defective records?",
    "Which are overdue and when are they due?",
    "Who is responsible for the open records?",
    "List the open records",
    "Show me the completed records",
    "Who is the contact for the active records?",
    "Which records have no owner?",
    "Which are not active?",
    "Which are due for review?",
    "What are the due dates for the overdue records?",
    "How many are overdue?",
    "Who owns the moon?",
    "",
]

_PLACEHOLDER = re.compile(
    r"(?-i:\bNone\b)(?! of\b)|(?-i:\bnan\b)|(?<!\w)\?(?!\w)|\{|\}|\[\]|recordOwner|recordStatus|isSimulated|"
    r"derivedFromDocument|simulated|synthetic|\bfake\b",
    re.IGNORECASE,
)
_ID = re.compile(r"\*\*([A-Za-z0-9][\w./-]*)\*\*")


def _cases():
    return [(d, q) for d in document_names() for q in QUESTIONS]


@pytest.mark.parametrize("document, question", _cases())
def test_resolve_and_compose_never_raise_and_never_print_a_placeholder(document, question):
    rows, label = lifted_rows(document)
    res = rp.resolve(rows, question, label, TODAY)
    lines = rp._compose(res, label, TODAY, rp.question_shape(question) or "list")
    text = "\n".join(lines)
    # A register may itself record "None" ("hold open device: None"): that is data, not a leak.
    recorded_none = any(
        rp._value(r, c).startswith("None") for r in rows for c in rp._all_columns(rows)
    )
    found = _PLACEHOLDER.search(text)
    assert not found or (recorded_none and found.group(0) == "None"), (document, question, text)
    # every bolded id belongs to this register
    known = {rp._ident(r) for r in rows}
    for ident in _ID.findall(text):
        assert ident in known or ident[0].isdigit(), (document, question, ident)


@pytest.mark.parametrize("document", document_names())
def test_a_list_names_each_record_at_most_once(document):
    rows, label = lifted_rows(document)
    for question in (
        "Which records are open?",
        "Which records are active?",
        "List the completed records",
    ):
        res = rp.resolve(rows, question, label, TODAY)
        idents = [rp._ident(r) for r in res.chosen()]
        assert len(idents) == len(set(idents)), (document, question)
        text = "\n".join(rp._compose(res, label, TODAY, "list"))
        bullets = [m for m in re.findall(r"^- \*\*([^*]+)\*\*", text, re.MULTILINE)]
        assert len(bullets) == len(set(bullets)), (document, question)


@pytest.mark.parametrize("document", document_names())
def test_the_guard_never_raises_on_a_denial_over_any_register(document):
    rows, label = lifted_rows(document)
    narration = "The register does not contain an ownership field.\n\nNo due date is recorded."
    for question in QUESTIONS[:8]:
        out = rp.guard_narration(narration, rows, question, label, TODAY)
        assert isinstance(out, str) and out
        assert not _PLACEHOLDER.search(out), (document, question, out)


@pytest.mark.parametrize("document", document_names())
def test_the_locked_facts_never_carry_an_internal_name(document):
    rows, label = lifted_rows(document)
    for question in QUESTIONS:
        block = "\n".join(rp.facts_lines(rows, question, label, TODAY))
        assert not _PLACEHOLDER.search(block), (document, question, block)
