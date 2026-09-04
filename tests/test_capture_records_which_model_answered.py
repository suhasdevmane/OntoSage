# -*- coding: utf-8 -*-
"""A capture must record which model answered each question (CAVEAT-411).

The stakeholder-catalogue run of 2026-09-03 was deliberately split: the hosted
`gpt-oss:120b` until its rolling call budget ran out, then local `gpt-oss:20b` on the
freed GPU. Nothing in the artifact would have said so. Its columns were qid, question,
intent, answer, gates, elapsed — and no provider and no model. A later reader, or a
regression comparison against it, would have treated two systems' answers as one
homogeneous baseline.

This project has been here repeatedly: BUG-359 graded bldg1 against faults injected into
bldg2; CAVEAT-393 computed recall over whichever detectors survived a rotation offset. Every
time, the harness reported a completeness it had not achieved, in the direction that looks
like success.

The provider is read from the RUNNING system's admin endpoint, not from `.env`. `.env` is
what someone intended; the container holds what is loaded. BUG-406 was exactly that gap, and
CAVEAT-178 is the same shape — a `restart` silently keeps the old environment.
"""

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent


def _load():
    """Import the script by path; it is not a package module."""
    path = REPO / "scripts" / "capture_golden_baseline.py"
    spec = importlib.util.spec_from_file_location("_cap", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_cap"] = mod
    spec.loader.exec_module(mod)
    return mod


cap = _load()


# ── the columns exist at all ────────────────────────────────────────────────────────────


def test_the_capture_schema_records_the_model():
    assert "provider" in cap.FIELDS
    assert "model" in cap.FIELDS


def test_the_new_columns_are_last_so_an_older_file_still_parses():
    """A resume reads the file written before these existed."""
    assert cap.FIELDS[-2:] == ["provider", "model"]


# ── reading the live system, and never dying because of it ─────────────────────────────


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.mark.parametrize(
    "cfg, expected",
    [
        ({"model_provider": "local", "ollama_model": "gpt-oss:20b"}, ("local", "gpt-oss:20b")),
        (
            {"model_provider": "cloud", "ollama_cloud_model": "gpt-oss:120b-cloud"},
            ("cloud", "gpt-oss:120b-cloud"),
        ),
        ({"model_provider": "openai", "openai_model": "gpt-4o"}, ("openai", "gpt-4o")),
    ],
)
def test_the_model_is_read_per_provider(monkeypatch, cfg, expected):
    monkeypatch.setattr(cap.requests, "get", lambda *a, **k: _Resp({"data": cfg}))
    assert cap._active_model("http://x", "tok") == expected


def test_an_unreachable_endpoint_labels_the_run_rather_than_killing_it():
    """A capture that dies because it could not label itself is worse than one labelled
    'unrecorded'. This runs for hours; it must not fall over on an admin 403."""

    def _boom(*_a, **_k):
        raise RuntimeError("403")

    original = cap.requests.get
    cap.requests.get = _boom
    try:
        assert cap._active_model("http://x", "tok") == (cap._UNRECORDED, cap._UNRECORDED)
    finally:
        cap.requests.get = original


def test_an_unknown_provider_is_named_not_guessed(monkeypatch):
    monkeypatch.setattr(
        cap.requests, "get", lambda *a, **k: _Resp({"data": {"model_provider": "something-new"}})
    )
    provider, model = cap._active_model("http://x", "tok")
    assert provider == "something-new"
    assert model == cap._UNRECORDED


# ── an older row is labelled honestly, not blankly ─────────────────────────────────────


def test_a_row_written_before_the_columns_existed_says_unrecorded():
    row = {"qid": "Q1", "status": "OK"}
    out = cap._labelled(row)
    assert out["provider"] == cap._UNRECORDED
    assert out["model"] == cap._UNRECORDED, (
        "blank would read as 'answered by no model', which is a claim; the truth is that it "
        "was not captured"
    )


def test_a_row_that_has_a_model_keeps_it():
    row = {"qid": "Q1", "provider": "local", "model": "gpt-oss:20b"}
    assert cap._labelled(row)["model"] == "gpt-oss:20b"


def test_a_rewrite_does_not_drop_the_unknown_columns(tmp_path):
    """_drop_rows rewrites the file; an old file's rows must survive with labels."""
    path = tmp_path / "baseline_x.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["qid", "question", "answer", "status"])
        w.writeheader()
        w.writerow({"qid": "Q1", "question": "a", "answer": "x", "status": "OK"})
        w.writerow({"qid": "Q2", "question": "b", "answer": "", "status": "FAILED"})
    dropped = cap._drop_rows(path, {"Q2"})
    assert dropped == 1
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["qid"] for r in rows] == ["Q1"]
    assert rows[0]["provider"] == cap._UNRECORDED


# ── a switch mid-run is located, not assumed ───────────────────────────────────────────


def test_the_poll_interval_is_short_enough_to_locate_a_switch():
    assert 1 <= cap._MODEL_POLL_EVERY <= 50, (
        "a switch is located to within this many rows; too large and the boundary between "
        "two models becomes a guess"
    )


def test_the_run_announces_a_model_change_rather_than_absorbing_it():
    """Pinned against the source: the loop must compare and say so."""
    import inspect

    src = inspect.getsource(cap.main)
    assert "MODEL CHANGED" in src
    assert "_active_model" in src
