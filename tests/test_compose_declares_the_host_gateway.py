# -*- coding: utf-8 -*-
"""A service that reaches the host must say so, or Linux cannot find it (W3-5).

Six services in every compose file name `host.docker.internal`. Exactly one — adminer —
declared `extra_hosts: host.docker.internal:host-gateway`.

Docker Desktop resolves that name whether or not you declare it, so on the machine this
was developed on it has always worked. On LINUX it does not resolve at all. The
orchestrator uses it for **both** MySQL and Ollama, so a fresh clone on a Linux host
boots, passes every container health check, and cannot answer a single question about
sensor data — with nothing in the logs naming the cause.

That is the shape of "deployment truth" this task is about: not a missing feature, but a
prerequisite that is invisible until someone else runs it.

Declaring the mapping is a no-op on Docker Desktop, which already provides it, and the
difference between working and not everywhere else. It is cheap, so it is declared on
every service that needs it rather than on the one that happened to be noticed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

MAPPING = "host.docker.internal:host-gateway"
SERVICE_RE = re.compile(r"^  ([a-z0-9_.-]+):\s*$")

#: The parked per-building files. `docker-compose.yml` is whichever of them is ACTIVE, and
#: is absent in the committed tree by Workflow rule 8 — so it is checked when present and
#: never required.
COMPOSE_FILES = sorted(Path(".").glob("docker-compose*.yml"))


def _service_blocks(text: str):
    lines = text.splitlines(keepends=True)
    marks = [(m.group(1), i) for i, ln in enumerate(lines) if (m := SERVICE_RE.match(ln))]
    for idx, (name, start) in enumerate(marks):
        end = marks[idx + 1][1] if idx + 1 < len(marks) else len(lines)
        yield name, "".join(lines[start:end])


def test_at_least_one_compose_file_is_present():
    """Guards the guard: a glob that matches nothing would pass every test below."""
    assert COMPOSE_FILES, "no docker-compose*.yml found — this test proves nothing"


@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.name)
def test_every_service_reaching_the_host_declares_the_gateway(path):
    text = path.read_text(encoding="utf-8")
    missing = [
        name
        for name, block in _service_blocks(text)
        if "host.docker.internal" in block and MAPPING not in block
    ]
    assert not missing, (
        f"{path.name}: these services reach host.docker.internal without declaring "
        f"`extra_hosts: {MAPPING}`, so the name does not resolve on Linux and they fail "
        f"silently: " + ", ".join(missing)
    )


@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.name)
def test_the_file_is_still_valid_yaml(path):
    """A mechanical insertion across four files earns a parse check."""
    import yaml

    assert yaml.safe_load(path.read_text(encoding="utf-8")), f"{path.name} parsed as empty"


@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.name)
def test_the_mapping_is_not_declared_where_it_is_not_needed(path):
    """Noise in a compose file is how the next reader stops believing it."""
    text = path.read_text(encoding="utf-8")
    stray = [
        name
        for name, block in _service_blocks(text)
        if MAPPING in block and "host.docker.internal" not in block.replace(MAPPING, "")
    ]
    assert not stray, f"{path.name}: gateway declared but unused by " + ", ".join(stray)
