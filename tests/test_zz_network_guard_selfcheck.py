# -*- coding: utf-8 -*-
"""Positive control for the unit-suite network guard (CAVEAT-408).

A guard that catches nothing and a suite that reaches nothing look identical from the
outside. This test makes the difference visible: it deliberately opens a non-loopback
socket and asserts the guard stops it. If this ever passes silently, the guard is inert and
every "the unit suite is offline" claim built on it is unsupported.
"""

import socket

import pytest

pytestmark = pytest.mark.unit


def test_the_guard_blocks_a_non_loopback_connection():
    from tests.conftest import UnitTestNetworkAccess

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    with pytest.raises(UnitTestNetworkAccess):
        s.connect(("93.184.216.34", 80))  # example.com, never actually reached
    s.close()


def test_loopback_is_still_allowed():
    """Blocking loopback would conflate 'reaches the internet' with 'talks to a local
    service' — a different problem, also worth fixing, and not this guard's job."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect_ex(("127.0.0.1", 1))  # refused is fine; not blocked is the point
    finally:
        s.close()
