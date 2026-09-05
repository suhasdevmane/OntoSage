"""
conftest.py — Shared pytest fixtures for OntoSage
==================================================
Provides reusable fixtures available to all test modules.
"""

import os
import sys

import pytest

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Tests must exercise a REAL pipeline key, never the published default — the app
# now rejects "sk-ontobot-pipeline" so a stock deployment can't authenticate
# /v1/*. Set BEFORE the project imports below pull in shared.config /
# orchestrator.main so the Settings singleton and _OAI_AUTH_KEYS pick it up.
# setdefault lets CI override with a real key.
os.environ.setdefault("PIPELINE_API_KEY", "sk-test-pipeline-key-ci")

# STRICT_SECRETS is a DEPLOYMENT guard (refuse to boot on default passwords), not a
# test concern: with no local .env — a fresh clone, CI, or the repo's canonical
# "no building active" state — it made `Settings()` raise at import time, so the
# whole suite failed to COLLECT. setdefault keeps any explicit override (a real
# deployment or a test that exercises the guard itself sets it deliberately).
os.environ.setdefault("STRICT_SECRETS", "false")

# Live-chat fixtures for the capability-semantic-routing regression battery.
# Imports `chat_client` and `fresh_session_id` fixtures.
from tests.fixtures.live_chat_client import chat_client, fresh_session_id  # noqa: F401
from tests.fixtures.ontology_fixtures import (
    brick_fixture,
    mock_anomalous_readings,
    mock_sensor_readings,
    mock_sparql_result,
    mock_sql_result,
    rec_fixture,
    s223_fixture,
)


@pytest.fixture
def brick_graph():
    """Parsed rdflib Graph with Brick v1.3 mock building."""
    return brick_fixture()


@pytest.fixture
def rec_graph():
    """Parsed rdflib Graph with REC 3.3 mock building."""
    return rec_fixture()


@pytest.fixture
def s223_graph():
    """Parsed rdflib Graph with ASHRAE 223P mock system."""
    return s223_fixture()


@pytest.fixture
def normal_readings():
    """50 normal temperature readings (21–24°C)."""
    return mock_sensor_readings("uuid-temp-101", n=50)


@pytest.fixture
def anomalous_readings():
    """20 readings with injected spike (35°C at index 5) and cold (8°C at index 10)."""
    return mock_anomalous_readings(n=20)


@pytest.fixture
def sql_result():
    """Typical SQLAgent result with 30 sensor readings."""
    return mock_sql_result("uuid-temp-101", n=30)


@pytest.fixture
def sparql_result():
    """Typical SPARQLAgent result for Air_Temperature_Sensor_1_01."""
    return mock_sparql_result("Air_Temperature_Sensor_1_01")


@pytest.fixture
def mock_state():
    """Minimal ConversationState mock."""
    from unittest.mock import MagicMock

    state = MagicMock()
    state.conversation_id = "test-conv-001"
    state.user_id = "test-user"
    state.messages = [MagicMock(content="test query", role="user")]
    state.current_intent = "analytics"
    state.analytics_required = False
    state.needs_clarification = False
    state.query_results = {}
    state.intermediate_results = {}
    state.persona = "general"
    return state


@pytest.fixture
def building_config(tmp_path):
    """Write a minimal building_config.yaml to a temp dir and return its path."""
    cfg_content = """
building:
  id: test_bldg
  name: Test Building
  namespace: "http://test.building.local/mock#"
  prefix: bldg
  timezone: Europe/London
  abox_file: data/test_abox.ttl
  tbox_file: data/Brick.ttl
ontology:
  schema: brick
  schema_uri: https://brickschema.org/schema/Brick#
  extra_prefixes: []
storage:
  backend: mysql
  database: test_db
  table: sensor_data
  columns:
    uuid: uuid
    value: value
    timestamp: time
    sensor_name: sensor_name
"""
    cfg_file = tmp_path / "test_building_config.yaml"
    cfg_file.write_text(cfg_content)
    return str(cfg_file)


# ── Network guard for the unit suite (CAVEAT-408) ──────────────────────────────────────
#
# `pytest -m unit` is documented as the fast, OFFLINE suite. It was not one. Confirmed from
# a run log: `httpx POST https://ollama.com/v1/chat/completions` during collection of the
# unit selection. So a green unit run was a function of `.env` — evidence about one machine
# and none about another — and a provider switch read as a code regression
# (test_capability_bare_building failed the moment the provider moved to the hosted model,
# because a BETTER answer took a different path).
#
# The guard blocks OUTBOUND, NON-LOOPBACK connections while a unit test runs, and names the
# test in the failure. Loopback is allowed: a test that talks to 127.0.0.1 is exercising a
# local service and is a different (also worth fixing) problem, and blocking it here would
# conflate the two.
#
# ONE ESCAPE HATCH, deliberately explicit: `@pytest.mark.allow_network`. A test that needs
# the network is an integration test and should say so in its marks rather than in its
# behaviour.
#
# Enabled by default. Set ONTOSAGE_ALLOW_UNIT_NETWORK=1 to measure what the guard would
# catch without failing the run.

_ALLOW_UNIT_NETWORK = os.environ.get("ONTOSAGE_ALLOW_UNIT_NETWORK", "").lower() in (
    "1",
    "true",
    "yes",
)

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}


class UnitTestNetworkAccess(AssertionError):
    """A test marked `unit` tried to reach the network."""


@pytest.fixture(autouse=True)
def _no_network_in_unit_tests(request, monkeypatch):
    """Fail a unit test that opens a non-loopback socket."""
    if _ALLOW_UNIT_NETWORK:
        return
    if "unit" not in request.node.keywords:
        return
    if "allow_network" in request.node.keywords:
        return

    import socket

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _host_of(address):
        if isinstance(address, tuple) and address:
            return str(address[0])
        return ""

    def _guarded(self, address, *args, **kwargs):
        host = _host_of(address)
        if host not in _LOOPBACK_HOSTS:
            raise UnitTestNetworkAccess(
                f"{request.node.nodeid} is marked `unit` but opened a connection to "
                f"{host}. The unit suite is documented as offline; a test that needs the "
                f"network belongs in `integration`, or must stub its client. If it "
                f"genuinely needs it, mark it @pytest.mark.allow_network and say why."
            )
        return real_connect(self, address, *args, **kwargs)

    def _guarded_ex(self, address, *args, **kwargs):
        host = _host_of(address)
        if host not in _LOOPBACK_HOSTS:
            raise UnitTestNetworkAccess(
                f"{request.node.nodeid} is marked `unit` but opened a connection to {host}."
            )
        return real_connect_ex(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", _guarded)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_ex)


def pytest_collection(session):
    """Report any outbound connection made while COLLECTING tests (CAVEAT-408).

    The original observation was a `POST https://ollama.com/v1/chat/completions` **during
    collection of the unit selection** — i.e. at import time, before any test ran. A
    per-test fixture cannot see that: by the time it installs, the call has happened.

    This reports rather than fails. Collection covers every selected test, including
    integration ones, so failing here would block a legitimate integration run for a
    problem that belongs to a specific module. The point is to make an import-time call
    visible, since inspection is exactly what let this sit unmeasured.
    """
    if _ALLOW_UNIT_NETWORK:
        return
    import socket

    real_connect = socket.socket.connect
    offenders = []

    def _watch(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) and address else ""
        if str(host) not in _LOOPBACK_HOSTS:
            offenders.append(str(host))
        return real_connect(self, address, *args, **kwargs)

    socket.socket.connect = _watch
    session.config._ontosage_collect_offenders = offenders

    def _restore():
        socket.socket.connect = real_connect

    session.config.add_cleanup(_restore)


def pytest_collection_finish(session):
    offenders = getattr(session.config, "_ontosage_collect_offenders", None)
    if offenders:
        unique = sorted(set(offenders))
        session.config.stash  # noqa: B018 - touch to keep the attribute lookup honest
        print(
            f"\n[network] {len(offenders)} outbound connection(s) during COLLECTION "
            f"to {unique}. Test collection must not reach the network: it makes the "
            f"suite's result a function of the environment (CAVEAT-408)."
        )
