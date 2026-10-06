"""H1 (TRIAL_TRACKER, 2026-10-06): the Ollama watchdog must probe the MODEL, not /api/tags,
and must restart after two consecutive failures with a 120 s floor.

These are STRING checks on the PowerShell source, not execution tests. The watchdog loops
forever and restarts a host process, so it cannot run inside pytest. The parse itself was
checked separately with the PowerShell AST parser (zero errors on both scripts).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
WATCHDOG = REPO / "scripts" / "ollama_watchdog.ps1"
REGISTER = REPO / "scripts" / "register_ollama_watchdog_task.ps1"


@pytest.fixture(scope="module")
def watchdog():
    return WATCHDOG.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def register():
    return REGISTER.read_text(encoding="utf-8")


def test_the_probe_is_a_one_token_generation_not_a_tags_listing(watchdog):
    assert "/api/generate" in watchdog
    assert "num_predict = 1" in watchdog
    assert "stream  = $false" in watchdog or "stream = $false" in watchdog
    # The default URL must not be the tags endpoint, which answers while the runner is hung.
    default_url = re.search(r'\[string\]\$Url = "([^"]+)"', watchdog).group(1)
    assert "/api/tags" not in default_url


def test_the_probe_is_a_post_with_a_sixty_second_timeout(watchdog):
    assert "-Method Post" in watchdog
    assert re.search(r"\[int\]\$ProbeTimeoutSeconds = 60\b", watchdog)
    assert "-TimeoutSec $ProbeTimeoutSeconds" in watchdog


def test_the_model_comes_from_env_not_a_literal(watchdog):
    assert "OLLAMA_MODEL" in watchdog
    assert ".env1" in watchdog
    assert "gpt-oss" not in watchdog


def test_restart_happens_after_exactly_two_consecutive_failures_by_default(watchdog):
    assert re.search(r"\[int\]\$FailuresBeforeRestart = 2\b", watchdog)
    # A success resets the counter; the restart branch fires only at the threshold.
    assert "$failures = 0" in watchdog
    assert "if ($failures -ge $FailuresBeforeRestart)" in watchdog


def test_a_hung_server_is_stopped_before_it_is_restarted(watchdog):
    # The earlier version left a running-but-hung process alone. The owner's rule is restart.
    assert "Stop-Process" in watchdog
    assert "'ollama serve'" in watchdog or '"serve"' in watchdog


def test_a_120_second_floor_follows_every_restart(watchdog):
    assert re.search(r"\[int\]\$RestartFloorSeconds = 120\b", watchdog)
    assert "Start-Sleep -Seconds ([Math]::Max($RestartFloorSeconds" in watchdog


def test_the_registration_script_is_a_logon_task_that_does_not_run_the_watchdog(register):
    assert "Register-ScheduledTask" in register
    assert "-AtLogOn" in register
    assert "ollama_watchdog.ps1" in register
    # Time limit off: the default would stop the watchdog after three days mid-trial.
    assert "ExecutionTimeLimit ([TimeSpan]::Zero)" in register
    # Registration only schedules; it must not start the watchdog itself.
    assert "Start-Process" not in register
    assert "-Unregister" in register
