"""H5 (TRIAL_TRACKER, 2026-10-06): the freshness threshold is a CLI flag, default 30 minutes.

Offline: the HTTP layer and the health helpers are replaced, so nothing touches a stack.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "daily_trial_check.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("daily_trial_check_h5", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _fake_http(monkeypatch, mod, sensors):
    """Route the two calls _sensor_freshness makes to canned responses."""

    def fake_post(url, **kwargs):
        return _Resp({"data": {"session_token": "t"}})

    def fake_get(url, **kwargs):
        return _Resp(
            {
                "data": {
                    "by_state": {"fresh": 2, "stale": 1},
                    "assessed": len(sensors),
                    "not_probed": [],
                    "sensors": sensors,
                }
            }
        )

    monkeypatch.setattr(mod.httpx, "post", fake_post)
    monkeypatch.setattr(mod.httpx, "get", fake_get)
    monkeypatch.setenv("ADMIN_USERNAME", "u")
    monkeypatch.setenv("ADMIN_PASSWORD", "p")


def test_the_default_threshold_is_thirty_minutes():
    mod = _load_module()
    assert mod.FRESHNESS_THRESHOLD_MINUTES == 30


def test_the_flag_defaults_to_thirty_and_reaches_the_freshness_check(monkeypatch, capsys):
    mod = _load_module()
    seen = []
    monkeypatch.setattr(mod, "_health", lambda: {"data": {"status": "healthy"}})
    monkeypatch.setattr(mod, "_gate_deletions_24h", lambda: 0)
    monkeypatch.setattr(mod, "_watchdog_restarts", lambda: "none")
    monkeypatch.setattr(mod, "_backup_status", lambda: "none")
    monkeypatch.setattr(mod, "_sensor_freshness", lambda t: seen.append(t) or "x")

    monkeypatch.setattr("sys.argv", ["daily_trial_check.py", "--no-log"])
    mod.main()
    monkeypatch.setattr(
        "sys.argv", ["daily_trial_check.py", "--no-log", "--freshness-minutes", "45"]
    )
    mod.main()

    assert seen == [30, 45]


def test_the_threshold_counts_only_sensors_older_than_it(monkeypatch):
    mod = _load_module()
    sensors = [
        {"uuid": "a", "state": "fresh", "age_minutes": 5},
        {"uuid": "b", "state": "stale", "age_minutes": 40},
        {"uuid": "c", "state": "stale", "age_minutes": 200},
        {"uuid": "d", "state": "unknown", "age_minutes": None},
    ]
    _fake_http(monkeypatch, mod, sensors)

    thirty = mod._sensor_freshness(30)
    assert "2 older than 30 min" in thirty

    ninety = mod._sensor_freshness(90)
    assert "1 older than 90 min" in ninety


def test_the_default_argument_is_the_module_constant(monkeypatch):
    mod = _load_module()
    _fake_http(monkeypatch, mod, [{"uuid": "a", "state": "stale", "age_minutes": 31}])
    assert "1 older than 30 min" in mod._sensor_freshness()


def test_missing_credentials_are_reported_not_hidden(monkeypatch):
    mod = _load_module()
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    assert mod._sensor_freshness(15).startswith("unavailable")
