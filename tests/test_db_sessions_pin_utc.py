# -*- coding: utf-8 -*-
"""Every MySQL session must speak the clock the rows are stamped in (BUG-403).

OntoSage stores time-series as naive UTC. Until this test, that convention was enforced in
exactly ONE place — ``mysql_adapter``'s pool — and merely assumed everywhere else, including
in that pool's own comment: *"the dummy-data generator writes UTC"*.

It did not. The publisher wrote narrow rows with SQL ``NOW()`` on a session that inherited
the server's SYSTEM zone (BST, UTC+1) into ``DATETIME`` columns, which store what they are
handed. Every narrow row landed ONE HOUR AHEAD of every reader, and two things followed:

* a window bounded by ``NOW()`` dropped the newest hour, so the anomaly sweep read a
  truncated series and an injected fault sat outside its own window — measured as
  "27 rows across 7 hours" and a dropout skipped for "no rows in the window";
* the freshness gate, ENFORCING since 2026-09-02, saw a *future* timestamp as current and
  would have called a dead point fresh for a full hour after it stopped.

The wide table hid all of it, because its column is ``TIMESTAMP`` — converted on write and
on read — so the same ``NOW()`` landed correctly there. One table type was right and
eighteen were wrong.

A convention held in one connection is not a convention. This asserts it at every call site,
because the cost of the next one forgetting is not an error: it is an hour of silence that
looks like data.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent

#: Directories whose code opens MySQL sessions against the time-series stores.
_SEARCH_ROOTS = ("orchestrator", "shared", "scripts", "mysql-dummy-publish-dev")

#: A connect call and everything up to its closing paren at the same indent.
_CONNECT = re.compile(r"(?:pymysql|aiomysql)\.(?:connect|create_pool)\(", re.M)

#: Files that legitimately open a session where no timestamp is read or written.
_EXEMPT = {
    # none today; add with a one-line reason rather than widening the regex
}


def _call_body(text: str, start: int) -> str:
    """The source of one call, from its opening paren to the matching close."""
    i = text.index("(", start)
    depth, j = 0, i
    while j < len(text):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                return text[i : j + 1]
        j += 1
    return text[i:]


def _offenders():
    bad = []
    for root in _SEARCH_ROOTS:
        base = REPO / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            rel = path.relative_to(REPO).as_posix()
            if rel in _EXEMPT or "/tests/" in rel or path.name.startswith("test_"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for m in _CONNECT.finditer(text):
                body = _call_body(text, m.start())
                if "init_command" not in body:
                    line = text[: m.start()].count("\n") + 1
                    bad.append(f"{rel}:{line}")
    return bad


def test_every_mysql_session_pins_its_time_zone():
    offenders = _offenders()
    assert not offenders, (
        "these open a MySQL session without pinning its time zone, so NOW() there may not "
        "mean what NOW() means to the readers:\n  "
        + "\n  ".join(offenders)
        + "\n\nPass init_command=UTC_SESSION_INIT (shared/db_clock.py)."
    )


def test_the_pin_is_stated_in_one_place():
    """A copied string literal is a convention that drifts; a constant is one that holds."""
    from shared.db_clock import UTC_SESSION_INIT

    assert "+00:00" in UTC_SESSION_INIT
    assert UTC_SESSION_INIT.lower().startswith("set time_zone")


def test_the_publisher_pins_the_same_clock_it_writes_with():
    """The writer is the half that was wrong; assert it directly rather than by proxy."""
    src = (REPO / "mysql-dummy-publish-dev" / "mysql_dummy_publisher.py").read_text(
        encoding="utf-8"
    )
    assert "init_command=\"SET time_zone='+00:00'\"" in src, (
        "the publisher stamps narrow rows with SQL NOW(); without this pin those rows carry "
        "the server's local zone while every reader reads UTC"
    )
