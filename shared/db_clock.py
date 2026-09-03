# -*- coding: utf-8 -*-
"""One clock for every process that reads or writes time-series (BUG-403).

OntoSage stores time-series as naive UTC. That convention was written down in exactly one
place — ``mysql_adapter``'s connection pool, which pins each session to ``+00:00`` and states
in a comment that "the dummy-data generator writes UTC".

It did not. The publisher wrote narrow rows with SQL ``NOW()`` on a session that inherited
the server's SYSTEM zone (BST, UTC+1), into ``DATETIME`` columns, which store what they are
handed without converting it. Every narrow row was therefore stamped ONE HOUR AHEAD of the
clock every consumer reads with, and:

* any window bounded by ``NOW()`` silently dropped the newest hour of data, so the anomaly
  sweep saw a truncated series and a freshly injected fault sat outside its own window;
* the freshness gate — ENFORCING since 2026-09-02 — read a future timestamp as current, and
  would have gone on calling a dead point fresh for a full hour after it stopped.

The wide table concealed it: its timestamp column is ``TIMESTAMP``, which MySQL converts on
write and again on read, so the identical ``NOW()`` landed correctly there. One table type
was right and eighteen were wrong.

A convention enforced in one connection and merely *assumed* everywhere else is not a
convention. Import ``UTC_SESSION_INIT`` wherever a MySQL session is opened, and
``tests/test_db_sessions_pin_utc.py`` fails the build when a new call site forgets.
"""

from __future__ import annotations

#: Pass as ``init_command=`` to pymysql/aiomysql so the session's ``NOW()``,
#: ``CURDATE()`` and ``DATE_SUB(NOW(), ...)`` speak the same UTC the rows are stamped in.
UTC_SESSION_INIT = "SET time_zone='+00:00'"
