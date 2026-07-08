# -*- coding: utf-8 -*-
"""
corpus_replay.py — Corpus replay harness for the OntoSage V3 evaluation (T28).

Replays a stratified sample from the 5,604-question master table against the
live OntoSage system and grades each answer with an LLM judge.

STRATIFICATION
--------------
Default 240 questions: 40 per latent complexity level (L1-L6), non-GK rows only
(answer_basis != "general-knowledge").  A fixed random seed (default 42) makes
the sample reproducible across runs.

GRADING RUBRIC
--------------
The LLM judge assigns one of four grades:
  answered-with-data       System returned a grounded, data-driven answer.
  honest-capability-answer System truthfully acknowledged it can't answer yet
                           and explained why (e.g. 'requires_extension' case).
  deflected                Scope redirect or refusal with no useful explanation.
  wrong                    Factually incorrect, traceback, or empty/timeout.

Both answered-with-data and honest-capability-answer count as PASS for the
paper metric.  deflected and wrong count as FAIL.

RESUMABILITY
------------
Each graded row is appended to a checkpoint CSV immediately.  Re-running
with the same --out-prefix skips already-graded qids.

OUTPUT
------
  outputs/replay/replay_<ts>.csv    — machine-readable row per question
  outputs/replay/replay_<ts>.md     — human-readable summary with per-level rates

RUN
---
  python scripts/corpus_replay.py                    # 240q default
  python scripts/corpus_replay.py --sample 60        # quick smoke test
  python scripts/corpus_replay.py --seed 99 --sample 240
  python scripts/corpus_replay.py --out-prefix replay_20260611_120000  # resume
  python scripts/corpus_replay.py --no-flush-cache   # skip cache flush
  python scripts/corpus_replay.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

# ─── Configuration ────────────────────────────────────────────────────────────

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent

_MASTER_TABLE = (
    _REPO_ROOT
    / "paper"
    / "Survey analysis and results"
    / "outputs"
    / "master table analysis"
    / "complexity_master_table.csv"
)
_OUTPUT_DIR = _SCRIPT_DIR / "outputs" / "replay"

BASE_URL = os.environ.get("ONTOSAGE_BASE", "http://127.0.0.1:8000")
REPLAY_USER = os.environ.get("ONTOSAGE_REPLAY_USER", "replaytest")
REPLAY_PASS = os.environ.get("ONTOSAGE_REPLAY_PASS", "replaytestpass99")
# /v1/chat/completions (Open WebUI path) authenticates with the pipeline key.
PIPELINE_API_KEY = os.environ.get("PIPELINE_API_KEY", "sk-ontobot-pipeline")

REQUEST_TIMEOUT = 120  # seconds per question
REQUEST_DELAY = 0.8    # polite gap between requests

# LLM judge — uses the same MODEL_PROVIDER env the system uses.
# Falls back to rule-based heuristics when no API key is set.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_JUDGE_MODEL", "gpt-4o-mini")

_HARD_FAIL_STRINGS = [
    "traceback",
    "internal server error",
    "unable to process",
    "keyerror",
    "typeerror",
    "valueerror",
    "nameerror",
    "indexerror",
    "couldn't generate a response",
    "could not generate a response",
]

_DECLINE_STRINGS = [
    "cannot",
    "can't",
    "unable",
    "not supported",
    "not yet",
    "do not have access",
    "don't have access",
    "not able to",
    "out of scope",
    "i'm an ai",
    "i am an ai",
    "i specialise in",
    "i specialize in",
    "smart building management",
    "building-related",
    "i can help with",
    "i'm here to help with",
    "i focus on",
    "only help with",
]

VALID_GRADES = {
    "answered-with-data",
    "honest-capability-answer",
    "deflected",
    "wrong",
}

PASS_GRADES = {"answered-with-data", "honest-capability-answer"}


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _safe_print(text: str = "") -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "ascii"
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"))


def _flush_resp_cache() -> None:
    """Flush resp_cache:* keys from the Redis container."""
    cmd = [
        "docker",
        "exec",
        "redis-memory-store",
        "sh",
        "-c",
        "redis-cli --scan --pattern 'resp_cache:*' | xargs -r redis-cli del",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            deleted = result.stdout.strip()
            _safe_print(f"[cache] Flushed resp_cache — deleted keys: {deleted or '0'}")
        else:
            _safe_print(f"[cache] WARNING: flush exited {result.returncode}: {result.stderr.strip()[:120]}")
    except FileNotFoundError:
        _safe_print("[cache] WARNING: docker not found — cache not flushed (run manually)")
    except subprocess.TimeoutExpired:
        _safe_print("[cache] WARNING: cache flush timed out — continuing anyway")


# ─── Authentication ────────────────────────────────────────────────────────────


def _authenticate(base_url: str) -> str:
    """Obtain a session token, registering the user if needed."""
    for attempt in range(2):
        try:
            r = requests.post(
                f"{base_url}/auth/login",
                headers={"Content-Type": "application/json"},
                json={"username": REPLAY_USER, "password": REPLAY_PASS},
                timeout=15,
            )
            if r.status_code == 200:
                tok = ((r.json() or {}).get("data") or {}).get("session_token")
                if tok:
                    _safe_print(f"[auth] token acquired for '{REPLAY_USER}'")
                    return tok
        except Exception as exc:
            _safe_print(f"[auth] login attempt error: {exc}")
        if attempt == 0:
            try:
                requests.post(
                    f"{base_url}/auth/register",
                    headers={"Content-Type": "application/json"},
                    json={"username": REPLAY_USER, "password": REPLAY_PASS, "email": "replay@test.local"},
                    timeout=15,
                )
            except Exception:
                pass
    _safe_print("[auth] WARNING: could not authenticate — requests may 401")
    return ""


# ─── Master table loading + stratification ────────────────────────────────────


def _load_master_table(path: Path) -> List[Dict[str, str]]:
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    _safe_print(f"[corpus] Loaded {len(rows)} rows from {path.name}")
    return rows


def _filter_non_gk(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Keep only rows where answer_basis != 'general-knowledge'."""
    filtered = [r for r in rows if r.get("answer_basis", "").lower() != "general-knowledge"]
    skipped = len(rows) - len(filtered)
    _safe_print(f"[corpus] Non-GK filter: {len(filtered)} kept, {skipped} GK rows dropped")
    return filtered


def _stratified_sample(
    rows: List[Dict[str, str]], per_level: int, seed: int
) -> List[Dict[str, str]]:
    """Return up to per_level rows per latent_level (1-6), with fixed seed."""
    rng = random.Random(seed)
    levels: Dict[str, List[Dict[str, str]]] = {}
    for row in rows:
        lv = row.get("latent_level", "").strip()
        if not lv:
            continue
        levels.setdefault(lv, []).append(row)

    sample: List[Dict[str, str]] = []
    for lv in sorted(levels.keys(), key=lambda x: int(x) if x.isdigit() else 99):
        pool = levels[lv]
        rng.shuffle(pool)
        chosen = pool[:per_level]
        sample.extend(chosen)
        _safe_print(f"[corpus]   L{lv}: {len(chosen)}/{len(pool)} rows sampled")

    _safe_print(f"[corpus] Total sample: {len(sample)} questions")
    return sample


# ─── LLM judge ────────────────────────────────────────────────────────────────

_JUDGE_SYSTEM_PROMPT = """\
You are a strict evaluator for an intelligent building management assistant called OntoSage.
Grade the system's answer to the user's question using exactly one of these four labels:

answered-with-data
  The system returned a grounded, data-driven answer using real sensor readings,
  analytics, metadata, or ontology facts.  Numbers, specific values, or structured
  information are present.  This is the best outcome.

honest-capability-answer
  The system truthfully acknowledged it cannot answer this question yet (e.g. sensor
  not available, capability not implemented) and gave a clear reason.  A capability
  explanation, offer to set up an alert, or reference to what extension is needed
  counts here.  This is a good outcome.

deflected
  The system gave a generic scope redirect, refused without useful explanation, or
  said something like "I specialise in building management" without addressing the
  question at all.  No useful information was provided.

wrong
  The response contains a traceback, internal server error, empty text, or clearly
  incorrect information that contradicts observable facts.

Respond with EXACTLY one word from the four labels above.  No explanation, no punctuation.
"""


def _judge_with_llm(question: str, answer: str) -> str:
    """Call the OpenAI API to grade the answer. Falls back to heuristic."""
    if not OPENAI_API_KEY:
        return _heuristic_grade(question, answer)
    try:
        import openai  # type: ignore

        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Question: {question}\n\n"
                        f"System answer:\n{answer[:1500]}"
                    ),
                },
            ],
            temperature=0,
            max_tokens=10,
        )
        raw = response.choices[0].message.content.strip().lower()
        # Normalise partial matches
        for grade in sorted(VALID_GRADES, key=len, reverse=True):
            if grade in raw:
                return grade
        _safe_print(f"[judge] unexpected response '{raw}' — falling back to heuristic")
    except Exception as exc:
        _safe_print(f"[judge] LLM judge error: {exc} — using heuristic")
    return _heuristic_grade(question, answer)


def _heuristic_grade(question: str, answer: str) -> str:
    """Rule-based grading fallback when no LLM API is available.

    Signature matches the judge_fn contract (question, answer); the question
    is currently unused by the heuristic but kept for parity with the LLM judge.
    """
    low = answer.lower()

    # Hard failures first
    if not answer.strip() or len(answer.strip()) < 20:
        return "wrong"
    if any(h in low for h in _HARD_FAIL_STRINGS):
        return "wrong"

    # Honest capability answer: contains capability language + no data
    capability_phrases = [
        "not currently available",
        "not yet implemented",
        "requires",
        "not equipped",
        "not instrumented",
        "phase h",
        "hardware integration",
        "sensor not available",
        "i don't have access to",
        "i currently do not have",
        "extension needed",
        "alert me when",
        "set up an alert",
        "cannot directly measure",
        "capability",
    ]
    has_capability_phrase = any(p in low for p in capability_phrases)
    has_numbers = bool(re.search(r"\b\d+\.?\d*\s*(%|°|ppm|kwh|kw|lux|db|m2|m3|°c|l/|kg)", low))
    has_data_markers = bool(
        re.search(r"\b\d{2,}\b", low)
        and any(w in low for w in ["temperature", "co2", "humidity", "energy", "floor", "room", "sensor"])
    )

    # Generic deflection
    if any(s in low for s in _DECLINE_STRINGS) and not has_capability_phrase and not has_data_markers:
        return "deflected"

    if has_capability_phrase and not has_numbers:
        return "honest-capability-answer"

    if has_numbers or has_data_markers:
        return "answered-with-data"

    # Long structured answers without numbers are plausibly honest explanations
    if len(answer) > 200 and not any(s in low for s in _DECLINE_STRINGS):
        return "honest-capability-answer"

    return "deflected"


# ─── Question asking ──────────────────────────────────────────────────────────


def _ask_question(
    question: str,
    base_url: str,
    building_id: str,
    judge_fn,
) -> Tuple[str, str, float, str]:
    """POST to /v1/chat/completions; return (answer, grade, elapsed, status)."""
    chat_id = f"replay-{uuid.uuid4().hex[:8]}"
    body = {
        "model": "ontosage",
        "stream": False,
        "messages": [{"role": "user", "content": question}],
    }
    headers = {
        "Content-Type": "application/json",
        "X-Chat-Id": chat_id,
        "Authorization": f"Bearer {PIPELINE_API_KEY}",
    }
    if building_id:
        headers["X-Building-Id"] = building_id

    time.sleep(REQUEST_DELAY)
    t0 = time.time()
    try:
        r = requests.post(
            f"{base_url}/v1/chat/completions",
            headers=headers,
            json=body,
            timeout=REQUEST_TIMEOUT,
        )
        elapsed = round(time.time() - t0, 1)
        if r.status_code != 200:
            return "", "wrong", elapsed, f"HTTP {r.status_code}"
        answer = r.json()["choices"][0]["message"]["content"]
        grade = judge_fn(question, answer)
        return answer, grade, elapsed, "OK"
    except requests.Timeout:
        return "", "wrong", round(time.time() - t0, 1), "TIMEOUT"
    except Exception as exc:
        return "", "wrong", round(time.time() - t0, 1), f"ERROR:{str(exc)[:80]}"


# ─── Checkpoint CSV ───────────────────────────────────────────────────────────

_CSV_FIELDNAMES = [
    "qid",
    "latent_level",
    "latent_level_name",
    "answerability",
    "question",
    "grade",
    "pass",
    "elapsed_s",
    "status",
    "answer_preview",
]


def _load_checkpoint(path: Path) -> Dict[str, Dict[str, str]]:
    """Return dict of already-graded {qid: row}."""
    done: Dict[str, Dict[str, str]] = {}
    if not path.exists():
        return done
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            done[row["qid"]] = row
    _safe_print(f"[resume] Loaded {len(done)} already-graded rows from {path.name}")
    return done


def _append_row(path: Path, row: Dict[str, Any], first: bool) -> None:
    """Append one row to the checkpoint CSV; write header on first call."""
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDNAMES, extrasaction="ignore")
        if first:
            writer.writeheader()
        writer.writerow(row)


# ─── Report generation ────────────────────────────────────────────────────────

_LEVEL_NAMES = {
    "1": "Factual Recall",
    "2": "Comparative Analysis",
    "3": "Inferential Reasoning",
    "4": "Causal Diagnosis",
    "5": "Systemic Synthesis",
    "6": "Meta / Contextual",
}


def _generate_report(rows: List[Dict[str, Any]], md_path: Path, csv_path: Path) -> None:
    """Write final per-level report to .md and .csv."""
    total = len(rows)
    passed = sum(1 for r in rows if r["pass"] == "True")
    pass_rate = 100 * passed / total if total else 0

    # Per-level breakdown
    by_level: Dict[str, Dict[str, int]] = {}
    for r in rows:
        lv = str(r.get("latent_level", "?"))
        entry = by_level.setdefault(lv, {"total": 0, "pass": 0})
        entry["total"] += 1
        if r["pass"] == "True":
            entry["pass"] += 1

    # Per-grade breakdown
    grade_counts: Dict[str, int] = {}
    for r in rows:
        g = r.get("grade", "unknown")
        grade_counts[g] = grade_counts.get(g, 0) + 1

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    md_lines = [
        "# OntoSage Corpus Replay Report",
        "",
        f"*Generated: {now}*",
        f"*Sample: {total} questions | Grading: LLM judge + heuristic fallback*",
        "",
        "## Overall",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total questions | {total} |",
        f"| PASS (answered-with-data + honest-capability) | {passed} ({pass_rate:.1f}%) |",
        f"| FAIL (deflected + wrong) | {total - passed} ({100 - pass_rate:.1f}%) |",
        "",
        "## Per-level pass rates",
        "",
        "| Level | Name | Total | Pass | Rate |",
        "|-------|------|-------|------|------|",
    ]
    for lv in sorted(by_level.keys(), key=lambda x: int(x) if x.isdigit() else 99):
        entry = by_level[lv]
        rate = 100 * entry["pass"] / entry["total"] if entry["total"] else 0
        name = _LEVEL_NAMES.get(lv, lv)
        md_lines.append(
            f"| L{lv} | {name} | {entry['total']} | {entry['pass']} | {rate:.1f}% |"
        )

    md_lines += [
        "",
        "## Grade breakdown",
        "",
        "| Grade | Count |",
        "|-------|-------|",
    ]
    for grade in ["answered-with-data", "honest-capability-answer", "deflected", "wrong"]:
        md_lines.append(f"| {grade} | {grade_counts.get(grade, 0)} |")

    md_lines += [
        "",
        "## Results file",
        "",
        f"Full row-by-row results: `{csv_path.name}`",
        "",
        "---",
        "*Baseline (pre-V3): 16.2% answerable.  Target: >=60% answered-with-data-or-honest-capability.*",
    ]

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    _safe_print(f"\n[report] Written {md_path.name}")
    _safe_print(
        f"[report] OVERALL: {passed}/{total} PASS = {pass_rate:.1f}%"
        f"  (baseline 16.2%, target >=60%)"
    )
    for lv in sorted(by_level.keys(), key=lambda x: int(x) if x.isdigit() else 99):
        entry = by_level[lv]
        rate = 100 * entry["pass"] / entry["total"] if entry["total"] else 0
        _safe_print(f"  L{lv}: {entry['pass']}/{entry['total']} = {rate:.1f}%")


# ─── Main ─────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Corpus replay harness — T28 V3 evaluation"
    )
    p.add_argument(
        "--sample", type=int, default=240,
        help="Total questions to replay (must be divisible by 6; default 240)"
    )
    p.add_argument("--seed", type=int, default=42, help="Random seed for stratified sample")
    p.add_argument("--base-url", default=BASE_URL, help=f"OntoSage base URL (default {BASE_URL})")
    p.add_argument("--building", default="bldg1", help="Building ID (default bldg1)")
    p.add_argument(
        "--out-prefix",
        default=None,
        help="Resume an existing run by prefix (e.g. replay_20260611_120000); "
             "skips already-graded qids",
    )
    p.add_argument(
        "--no-flush-cache",
        action="store_true",
        help="Skip Redis resp_cache flush before the run",
    )
    p.add_argument(
        "--no-llm-judge",
        action="store_true",
        help="Force heuristic grading even when OPENAI_API_KEY is set",
    )
    p.add_argument(
        "--master-table",
        default=str(_MASTER_TABLE),
        help="Path to complexity_master_table.csv",
    )
    return p


def main() -> int:
    args = _build_parser().parse_args()

    per_level = args.sample // 6
    if per_level * 6 != args.sample:
        _safe_print(
            f"[error] --sample must be divisible by 6 (6 latent levels); "
            f"got {args.sample}"
        )
        return 1

    # ── Output paths ──────────────────────────────────────────────────────────
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = args.out_prefix or datetime.utcnow().strftime("replay_%Y%m%d_%H%M%S")
    checkpoint_path = _OUTPUT_DIR / f"{ts}.csv"
    final_csv_path = _OUTPUT_DIR / f"{ts}_final.csv"
    md_path = _OUTPUT_DIR / f"{ts}.md"

    # ── Load + sample ─────────────────────────────────────────────────────────
    master_path = Path(args.master_table)
    if not master_path.is_file():
        _safe_print(f"[error] Master table not found: {master_path}")
        return 1

    all_rows = _load_master_table(master_path)
    non_gk = _filter_non_gk(all_rows)
    sample = _stratified_sample(non_gk, per_level, args.seed)

    if not sample:
        _safe_print("[error] No rows in sample after stratification")
        return 1

    # ── Resume checkpoint ─────────────────────────────────────────────────────
    done = _load_checkpoint(checkpoint_path)
    pending = [r for r in sample if r["qid"] not in done]
    _safe_print(f"[run] {len(done)} already done, {len(pending)} to replay")

    # ── Cache flush ───────────────────────────────────────────────────────────
    if not args.no_flush_cache and pending:
        _flush_resp_cache()

    # ── Judge function ────────────────────────────────────────────────────────
    if args.no_llm_judge or not OPENAI_API_KEY:
        if not OPENAI_API_KEY and not args.no_llm_judge:
            _safe_print("[judge] OPENAI_API_KEY not set — using heuristic grader")
        judge_fn = _heuristic_grade
    else:
        _safe_print(f"[judge] Using LLM judge: {OPENAI_MODEL}")
        judge_fn = _judge_with_llm

    # ── Run ───────────────────────────────────────────────────────────────────
    first_write = not checkpoint_path.exists()
    completed_rows: List[Dict[str, Any]] = list(done.values())

    _safe_print(
        f"\n[run] Replaying {len(pending)} questions against {args.base_url} ..."
    )

    for i, q_row in enumerate(pending, 1):
        qid = q_row["qid"]
        question = q_row.get("question", "").strip()
        latent_level = q_row.get("latent_level", "?")
        latent_level_name = q_row.get("latent_level_name", "")
        answerability = q_row.get("answerability", "")

        if not question:
            _safe_print(f"  [{i}/{len(pending)}] SKIP {qid} — empty question")
            continue

        _safe_print(
            f"  [{i}/{len(pending)}] L{latent_level} {qid[:16]} "
            f"| {question[:70]}{'...' if len(question) > 70 else ''}"
        )

        answer, grade, elapsed, status = _ask_question(
            question, args.base_url, args.building, judge_fn
        )
        is_pass = grade in PASS_GRADES

        row: Dict[str, Any] = {
            "qid": qid,
            "latent_level": latent_level,
            "latent_level_name": latent_level_name,
            "answerability": answerability,
            "question": question,
            "grade": grade,
            "pass": str(is_pass),
            "elapsed_s": elapsed,
            "status": status,
            "answer_preview": answer[:300].replace("\n", " "),
        }

        _append_row(checkpoint_path, row, first=first_write)
        first_write = False
        completed_rows.append(row)

        icon = "[PASS]" if is_pass else "[FAIL]"
        _safe_print(
            f"         {icon} grade={grade} elapsed={elapsed}s"
        )

    # ── Final report ──────────────────────────────────────────────────────────
    if completed_rows:
        # Write consolidated final CSV (all rows, including resumed)
        with open(final_csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_FIELDNAMES, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(completed_rows)

        _generate_report(completed_rows, md_path, final_csv_path)
        _safe_print(f"\n[done] Results: {final_csv_path}")
        _safe_print(f"[done] Report:  {md_path}")
    else:
        _safe_print("[done] No rows to report")

    return 0


if __name__ == "__main__":
    sys.exit(main())
