# -*- coding: utf-8 -*-
"""B2 + B5: the bldg1 compose file publishes ports on loopback only and bounds the logs.

The role header is trusted (main.resolve_forwarded_user) on the strength of the orchestrator
and Open WebUI being reachable from the host loopback alone. A bare "8000:8000" publishes on
every interface, which is the exposure this guards against.
"""

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.bldg1.yml"


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


def test_orchestrator_and_open_webui_publish_on_loopback_only(compose):
    services = compose["services"]
    for name in ("orchestrator", "open-webui"):
        ports = services[name].get("ports") or []
        assert ports, f"{name} publishes no port; the test would prove nothing"
        for port in ports:
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port!r} beyond loopback"


def test_no_published_port_in_the_file_lacks_the_loopback_prefix(compose):
    offenders = [
        (name, port)
        for name, svc in compose["services"].items()
        for port in (svc.get("ports") or [])
        if not str(port).startswith("127.0.0.1:")
    ]
    assert not offenders, offenders


def test_orchestrator_logs_are_bounded_json_file(compose):
    logging = compose["services"]["orchestrator"].get("logging")
    assert logging, "orchestrator has no logging block, so logs grow without a bound"
    assert logging["driver"] == "json-file"
    assert logging["options"]["max-size"] == "50m"
    assert str(logging["options"]["max-file"]) == "5"
