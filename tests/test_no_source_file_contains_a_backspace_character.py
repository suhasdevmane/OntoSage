# -*- coding: utf-8 -*-
"""No production source file may contain a literal backspace character (2026-09-20).

A regex word-boundary escape written through a shell heredoc arrives as a BACKSPACE (0x08) instead
of a backslash and a letter. The file still compiles, the pattern still loads, and it silently
matches nothing — the lay-quantity check in the aggregate lane did exactly that and was found only
because five unit tests failed. lessons.md #101 names the cause; this test names the symptom, so
the next occurrence fails at the source instead of in a live answer.

Scope is production code. One existing test file contains two such characters deliberately-or-not
and passes; it is left alone rather than rewritten under a guard about something else.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
ROOTS = ("orchestrator", "shared", "scripts")


def test_no_production_source_file_contains_a_backspace():
    offenders = []
    for root in ROOTS:
        for path in (REPO / root).rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "\x08" in text:
                offenders.append(f"{path.relative_to(REPO)} ({text.count(chr(8))})")
    assert not offenders, "backspace character(s) in source, a mangled regex escape: " + str(offenders)
