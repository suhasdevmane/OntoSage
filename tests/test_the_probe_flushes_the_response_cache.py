# -*- coding: utf-8 -*-
"""BUG-662: the regression probe flushes the response cache, and says so when it cannot.

Observed 2026-09-17: "Is the lift working?" reported PASS in 0.0 s, having been asked by hand
minutes earlier. The answer came from Redis `resp_cache`, the lane never ran, and a cached
answer produced BEFORE a change will pass a case that the change has broken — the one
condition the probe exists to catch.

Pinned here, all with `subprocess.run` / the network replaced by fakes:

* the flush SCANs then DELs, and the count it prints is the sum of DEL's replies;
* a flush that cannot reach Redis is a FAILURE — never "0 removed" (the `--scan | xargs`
  pipeline in CLAUDE.md exits 0 when the scan fails, which is why this is two steps);
* a failed flush is stated at the TOP of the written report; `--no-flush` is stated too;
* the flush happens before the first question is asked;
* a case answered in under a second is flagged as a possible cache hit.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent


def _probe():
    spec = importlib.util.spec_from_file_location(
        "_probe_flush", REPO / "scripts" / "regression_probe.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_probe_flush"] = mod
    spec.loader.exec_module(mod)
    return mod


P = _probe()


class _Docker:
    """A fake `subprocess.run` for `docker exec <c> redis-cli ...`, backed by a key set."""

    def __init__(self, keys: List[str], scan_rc: int = 0, scan_out: str = "", del_out=None):
        self.keys = set(keys)
        self.scan_rc = scan_rc
        self.scan_out = scan_out
        self.del_out = del_out
        self.calls: List[List[str]] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        assert cmd[:2] == ["docker", "exec"] and cmd[3] == "redis-cli", cmd
        assert kwargs.get("timeout"), "a flush without a timeout can hang the probe forever"
        args = cmd[4:]
        if args[0] == "--scan":
            assert args[1:] == ["--pattern", "resp_cache:*"]
            if self.scan_rc:
                return SimpleNamespace(returncode=self.scan_rc, stdout="", stderr="no container")
            out = self.scan_out or "\n".join(sorted(k for k in self.keys))
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        if args[0] == "DEL":
            if self.del_out is not None:
                return SimpleNamespace(returncode=0, stdout=self.del_out, stderr="")
            gone = [k for k in args[1:] if k in self.keys]
            self.keys -= set(gone)
            return SimpleNamespace(returncode=0, stdout=f"{len(gone)}\n", stderr="")
        raise AssertionError(f"unexpected redis-cli call {args}")


# ── the flush itself ────────────────────────────────────────────────────────────


def test_it_deletes_every_cached_answer_and_counts_them():
    keys = [f"resp_cache:exact:b:{i}" for i in range(450)]  # more than one DEL batch
    docker = _Docker(keys)
    res = P.flush_response_cache("redis-memory-store", run=docker)
    assert res == {"ok": True, "removed": 450, "remaining": 0, "error": ""}
    assert docker.keys == set()
    dels = [c for c in docker.calls if c[4] == "DEL"]
    assert len(dels) == 3 and all(len(c) - 5 <= P._DEL_BATCH for c in dels)
    assert all(c[2] == "redis-memory-store" for c in docker.calls)


def test_an_empty_cache_is_a_successful_flush_of_zero():
    docker = _Docker([])
    res = P.flush_response_cache(run=docker)
    assert res["ok"] is True and res["removed"] == 0
    assert not [c for c in docker.calls if c[4] == "DEL"], "DEL with no keys is an error reply"


def test_the_default_container_is_the_one_claude_md_names():
    assert P.REDIS_CONTAINER == "redis-memory-store"


def test_a_scan_that_cannot_reach_redis_is_a_failure_not_zero_removed():
    res = P.flush_response_cache(run=_Docker(["resp_cache:x"], scan_rc=1))
    assert res["ok"] is False
    assert "scan failed" in res["error"]


def test_a_connection_error_printed_with_exit_zero_is_still_a_failure():
    docker = _Docker([], scan_out="Could not connect to Redis at 127.0.0.1:6379")
    res = P.flush_response_cache(run=docker)
    assert res["ok"] is False


def test_a_del_that_does_not_return_a_count_is_a_failure():
    res = P.flush_response_cache(run=_Docker(["resp_cache:x"], del_out="(error) NOAUTH"))
    assert res["ok"] is False and "DEL" in res["error"]


@pytest.mark.parametrize(
    "exc", [FileNotFoundError("docker"), subprocess.TimeoutExpired("docker", 60), OSError("x")]
)
def test_docker_missing_or_hung_is_reported_never_raised(exc):
    def boom(cmd, **kwargs):
        raise exc

    res = P.flush_response_cache(run=boom)
    assert res["ok"] is False and res["error"]


def test_keys_are_passed_as_arguments_not_through_a_shell():
    docker = _Docker(["resp_cache:exact:b:$(rm -rf /)"])
    P.flush_response_cache(run=docker)
    assert any("resp_cache:exact:b:$(rm -rf /)" in c for c in docker.calls if c[4] == "DEL")
    assert not any("sh" in c[:5] for c in docker.calls)


# ── what the report says ────────────────────────────────────────────────────────


def test_a_failed_flush_is_a_loud_warning():
    text = "\n".join(P.cache_status_lines({"ok": False, "removed": 0, "error": "scan failed"}))
    assert "WARNING" in text and "NOT FLUSHED" in text and "scan failed" in text


def test_no_flush_is_stated_rather_than_implied():
    text = "\n".join(P.cache_status_lines(None))
    assert "NOT FLUSHED" in text and "--no-flush" in text


def test_a_successful_flush_states_the_count_and_no_warning():
    text = "\n".join(P.cache_status_lines({"ok": True, "removed": 7, "remaining": 0}))
    assert "7 key(s) removed" in text and "WARNING" not in text


@pytest.mark.parametrize(
    "seconds,status,flagged",
    [
        (0.0, "OK", True),
        (0.9, "OK", True),
        (1.0, "OK", False),
        (12.4, "OK", False),
        (0.1, "HTTP 401", False),
        (0.2, "TIMEOUT", False),
    ],
)
def test_a_sub_second_success_is_a_possible_cache_hit(seconds, status, flagged):
    """A transport failure is fast for a different reason and is not called a cache hit."""
    assert P.possible_cache_hit({"seconds": seconds, "status": status}) is flagged


# ── the run: flush first, report top ────────────────────────────────────────────


def _run_main(tmp_path, monkeypatch, flush_result, extra_args=(), ask_seconds=(0.0, 14.0)):
    events: List[str] = []
    cases = json.loads(P.CASES_PATH.read_text(encoding="utf-8"))
    group = next(c["group"] for c in cases if c.get("group") and not c.get("building"))

    def fake_flush(container):
        events.append(f"flush:{container}")
        return flush_result

    timings = iter(list(ask_seconds) * 100)

    def fake_ask(question, base_url, building, token):
        events.append("ask")
        return {"answer": "", "intent": "", "status": "OK", "elapsed_s": next(timings)}

    cap = SimpleNamespace(
        REQUEST_TIMEOUT=30,
        _login=lambda base_url: "tok",
        _active_model=lambda base_url, token: ("local", "fake"),
        _ask=fake_ask,
    )
    monkeypatch.setattr(P, "flush_response_cache", fake_flush)
    monkeypatch.setattr(P, "_load", lambda name, rel: cap)
    monkeypatch.setattr(P, "_active_building", lambda base_url: "")
    monkeypatch.setattr(P, "_scalar_from_graph", lambda q, u, r: "0")
    out = tmp_path / "probe.md"
    P.main(["--only", group, "--out", str(out), *extra_args])
    return events, out.read_text(encoding="utf-8")


def test_the_run_flushes_before_the_first_question(tmp_path, monkeypatch):
    events, _ = _run_main(tmp_path, monkeypatch, {"ok": True, "removed": 3, "remaining": 0})
    assert events[0] == "flush:redis-memory-store"
    assert events.count("flush:redis-memory-store") == 1 and "ask" in events


def test_a_failed_flush_heads_the_written_report(tmp_path, monkeypatch):
    _, report = _run_main(tmp_path, monkeypatch, {"ok": False, "removed": 0, "error": "boom"})
    head = report.split("| result |")[0]
    assert "WARNING — THE RESPONSE CACHE WAS NOT FLUSHED" in head
    assert head.index("NOT FLUSHED") < head.index("Model:")


def test_no_flush_skips_the_flush_and_says_so(tmp_path, monkeypatch):
    events, report = _run_main(tmp_path, monkeypatch, {"ok": True}, extra_args=["--no-flush"])
    assert not any(e.startswith("flush:") for e in events)
    assert "--no-flush" in report.split("| result |")[0]


def test_the_report_marks_sub_second_cases(tmp_path, monkeypatch):
    _, report = _run_main(tmp_path, monkeypatch, {"ok": True, "removed": 0, "remaining": 0})
    assert "**possible cache hit**" in report
    assert "marked possible cache hits" in report
