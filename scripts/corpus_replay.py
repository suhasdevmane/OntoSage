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


def _env_or_dotenv(key: str, default: str = "") -> str:
    """Return an env var if set, else read it from the repo-root .env.

    RBAC now enforces auth on /v1/chat/completions, so the harness must present a
    valid PIPELINE_API_KEY. Reading .env here means the run works out of the box
    (``python scripts/corpus_replay.py``) with no manual ``export`` — matching how
    the orchestrator itself loads the key.
    """
    v = os.environ.get(key)
    if v:
        return v
    try:
        env_path = _SCRIPT_DIR.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s and not s.startswith("#") and s.split("=", 1)[0].strip() == key:
                    return s.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return default


BASE_URL = os.environ.get("ONTOSAGE_BASE", "http://127.0.0.1:8000")
REPLAY_USER = os.environ.get("ONTOSAGE_REPLAY_USER", "replaytest")
REPLAY_PASS = os.environ.get("ONTOSAGE_REPLAY_PASS", "replaytestpass99")
# /v1/chat/completions (Open WebUI path) authenticates with the pipeline key.
# Auto-loaded from .env (RBAC-enforced) so runs don't silently 401 without an export.
PIPELINE_API_KEY = _env_or_dotenv("PIPELINE_API_KEY", "sk-ontobot-pipeline")

REQUEST_TIMEOUT = 120  # seconds per question
REQUEST_DELAY = 0.8  # polite gap between requests

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
    # L7 grades (V4-T27/28): emitted by the deliberative grader, not the LLM judge
    "answered-with-proof",
    "clarified-appropriately",
    "fabricated",
}

PASS_GRADES = {
    "answered-with-data",
    "honest-capability-answer",
    "answered-with-proof",
    "clarified-appropriately",
}


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
            _safe_print(
                f"[cache] WARNING: flush exited {result.returncode}: {result.stderr.strip()[:120]}"
            )
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
                    json={
                        "username": REPLAY_USER,
                        "password": REPLAY_PASS,
                        "email": "replay@test.local",
                    },
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
                    "content": (f"Question: {question}\n\n" f"System answer:\n{answer[:1500]}"),
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
        and any(
            w in low
            for w in ["temperature", "co2", "humidity", "energy", "floor", "room", "sensor"]
        )
    )

    # Generic deflection
    if (
        any(s in low for s in _DECLINE_STRINGS)
        and not has_capability_phrase
        and not has_data_markers
    ):
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
        # V5: a non-answer is NOT a behavioural verdict. Grading transport
        # failures as "wrong" silently converted a mid-run stack restart into
        # a 9.2%-coverage "finding" (CAVEAT-173). These rows are excluded from
        # the denominator and reported separately.
        if r.status_code != 200:
            return "", "invalid-no-response", elapsed, f"HTTP {r.status_code}"
        payload = r.json()
        answer = payload["choices"][0]["message"]["content"]
        # HTTP 200 does not mean the system answered: when the provider refused
        # (quota 429, timeout, open circuit) every agent falls back to generic
        # text that reads like a reply. The server declares that, so quarantine
        # the row rather than scoring an outage as behaviour (BUG-177).
        degraded = payload.get("ontosage_llm_degraded")
        if degraded:
            causes = ",".join(degraded.get("causes") or ["unknown"])
            return answer, "invalid-no-response", elapsed, f"LLM-DEGRADED:{causes}"
        grade = judge_fn(question, answer)
        return answer, grade, elapsed, "OK"
    except requests.Timeout:
        return "", "invalid-no-response", round(time.time() - t0, 1), "TIMEOUT"
    except Exception as exc:
        return "", "invalid-no-response", round(time.time() - t0, 1), f"ERROR:{str(exc)[:80]}"


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
    # L7 bank columns (V4-T27): the annotated expectation rides along so the
    # deliberative grader (V4-T28) can score behavior-match without a re-join
    "expected_behavior",
    "l7_stratum",
    # V5-T01: stakeholder-bank passthroughs for per-role rollups
    "stakeholder_role",
    "register",
    # V6-T46: the supervisors' own classification, carried through so coverage can be
    # reported per readiness tier rather than as one number that hides which half is empty.
    "readiness_r",
    "complexity_l",
    "bank_source",
]


def _load_strata_source(path: Path) -> List[Dict[str, str]]:
    """Load a question-bank CSV as replay rows.

    Accepts FOUR bank shapes:
      - L7 bank (V4-T27): ID/qid, Question/question, l7_stratum, expected_behavior
      - V5 synthetic bank: ID, Question, Category, Register, Stakeholder_Role —
        Category becomes the stratum.
      - supervisor catalogue (V6-T46): ID, Question, Readiness_R (R1/R2/R3),
        Complexity_L (L1-L4), Stakeholder_Role — READINESS becomes the stratum.
      - stakeholder catalogue 37 (2026-08-29): 2,480 questions from the 31 catalogues
        that had never been extracted — STAKEHOLDER ROLE becomes the stratum.

    The corpora stratify on different axes ON PURPOSE, and the choice matters more than
    it looks. R1 coverage measures OntoSage; R2 coverage measures the estate's
    integration backlog; R3 measures governance. Rolling them into one number would let a
    good R1 score mask an empty R2 — and would tempt exactly the scoring inflation that
    already cost this project three false results (CAVEAT-173, BUG-176, BUG-177).

    The third corpus needs its own axis for the same reason. Most of those 31 catalogues
    carry no Category and no Readiness tag — verified in the source PDFs, not assumed —
    so on the old rules 1,840 of them fell into "unknown", which is precisely the
    meaningless bucket the sentence above was written to prevent. What they DO carry, on
    every row, is the stakeholder whose catalogue they came from, and that is the axis
    those documents are organised on: a security officer's questions and an
    undergraduate's fail for different reasons and are fixed by different work.

    Every row is replayed — banks are curated sets, no stratified sampling.
    """
    rows: List[Dict[str, str]] = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            qid = (r.get("qid") or r.get("ID") or "").strip()
            question = (r.get("question") or r.get("Question") or "").strip()
            if not qid or not question:
                continue
            readiness = (r.get("Readiness_R") or "").strip()
            source = (r.get("Source") or "").strip()
            # Readiness first: a supervisor-catalogue row has no Category, and falling
            # through to "unknown" would silently drop 480 questions into one meaningless
            # bucket. The 37-catalogue rows mostly have NEITHER, so they stratify on the
            # stakeholder their catalogue belongs to — the axis those documents are built
            # on, and the only field populated on all 2,480.
            if source == "stakeholder_catalogue_37":
                # ONE axis for this corpus, not two. Only 38% of these rows carry a
                # readiness tag, so a fallback chain would stratify part of the corpus by
                # readiness and the rest by stakeholder — 26 role buckets beside a
                # handful of R buckets, splitting single catalogues across both. Mixing
                # axes inside one corpus is the thing the paragraph above argues against.
                # Readiness stays available in its own column for anyone who wants it.
                stratum = (
                    (r.get("Stakeholder_Role") or "").strip()
                    or readiness
                    or (r.get("Category") or "").strip()
                    or "unknown"
                )
            else:
                stratum = (
                    (r.get("l7_stratum") or "").strip()
                    or readiness
                    or (r.get("Category") or "").strip()
                    or "unknown"
                )
            rows.append(
                {
                    "qid": qid,
                    "question": question,
                    "latent_level": stratum,
                    "latent_level_name": stratum,
                    "answerability": (r.get("expected_behavior") or "").strip(),
                    "expected_behavior": (r.get("expected_behavior") or "").strip(),
                    "l7_stratum": stratum,
                    "stakeholder_role": (r.get("Stakeholder_Role") or "").strip(),
                    "register": (r.get("Register") or "").strip(),
                    "readiness_r": readiness,
                    "complexity_l": (r.get("Complexity_L") or "").strip(),
                    "bank_source": (r.get("Source") or "").strip(),
                }
            )
    return rows


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


def _append_transcript(
    path: Path, qid: str, question: str, answer: str, row: Dict[str, Any]
) -> None:
    """Persist the FULL response beside the graded row, one JSON object per line.

    The CSV keeps a 300-character ``answer_preview`` with the newlines stripped, which
    is the right thing for a spreadsheet and the wrong thing for everything else. This
    project's recurring lesson is that a number only means something once somebody reads
    the rows behind it -- CAVEAT-039 was found that way, so were BUG-176, BUG-177 and
    BUG-191 -- and a truncated preview cannot support that. A table dump, a fabricated
    figure or a policy leak can all sit past character 300.

    JSONL rather than more CSV columns: answers are long and multi-line, and a
    transcript that has to survive a spreadsheet round-trip is a transcript that will be
    mangled. Written per row, so a run killed half way keeps what it had.
    """
    import json as _json

    record = {
        "qid": qid,
        "question": question,
        "answer": answer,
        "grade": row.get("grade"),
        "pass": row.get("pass"),
        "status": row.get("status"),
        "elapsed_s": row.get("elapsed_s"),
        "expected_behavior": row.get("expected_behavior"),
        "l7_stratum": row.get("l7_stratum"),
        "stakeholder_role": row.get("stakeholder_role"),
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:  # never lose a graded run over a transcript write
        _safe_print(f"[warn] could not write transcript row: {exc}")


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
    invalid_rows = [r for r in rows if r.get("grade") == "invalid-no-response"]
    if invalid_rows:
        rows = [r for r in rows if r.get("grade") != "invalid-no-response"]
    total = len(rows)
    passed = sum(1 for r in rows if r["pass"] == "True")
    pass_rate = 100 * passed / total if total else 0

    # NOTE-142 split: data-backed answers and honest declines are both acceptable
    # behaviour but not the same achievement — report them separately, always.
    data_backed = sum(1 for r in rows if r.get("grade") == "answered-with-data")
    honest_decline = sum(1 for r in rows if r.get("grade") == "honest-capability-answer")
    db_rate = 100 * data_backed / total if total else 0
    hd_rate = 100 * honest_decline / total if total else 0

    # Per-level breakdown (with per-grade split)
    by_level: Dict[str, Dict[str, int]] = {}
    for r in rows:
        lv = str(r.get("latent_level", "?"))
        entry = by_level.setdefault(lv, {"total": 0, "pass": 0, "data": 0, "honest": 0})
        entry["total"] += 1
        if r["pass"] == "True":
            entry["pass"] += 1
        if r.get("grade") == "answered-with-data":
            entry["data"] += 1
        elif r.get("grade") == "honest-capability-answer":
            entry["honest"] += 1

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
        f"| **Data-backed answers** | **{data_backed} ({db_rate:.1f}%)** |",
        f"| **Honest declines** | **{honest_decline} ({hd_rate:.1f}%)** |",
        f"| PASS (combined, legacy) | {passed} ({pass_rate:.1f}%) |",
        f"| FAIL (deflected + wrong) | {total - passed} ({100 - pass_rate:.1f}%) |",
        "",
        "> **NOTE-142:** quote the two split rates as the headline, never the combined",
        "> PASS — a system that declines everything would score 100% combined.",
        "",
        "## Per-level rates",
        "",
        "| Level | Name | Total | Data-backed | Honest-decline | Fail | Combined |",
        "|-------|------|-------|-------------|----------------|------|----------|",
    ]
    for lv in sorted(by_level.keys(), key=lambda x: int(x) if x.isdigit() else 99):
        entry = by_level[lv]
        rate = 100 * entry["pass"] / entry["total"] if entry["total"] else 0
        name = _LEVEL_NAMES.get(lv, lv)
        fails = entry["total"] - entry["pass"]
        lv_label = f"L{lv}" if str(lv).isdigit() else str(lv)
        md_lines.append(
            f"| {lv_label} | {name} | {entry['total']} | {entry['data']} | {entry['honest']} "
            f"| {fails} | {rate:.1f}% |"
        )

    # V5-T01: per-stakeholder rollup (present only when the bank carries roles)
    by_role: Dict[str, Dict[str, int]] = {}
    for r in rows:
        role = (r.get("stakeholder_role") or "").strip()
        if not role:
            continue
        entry = by_role.setdefault(role, {"total": 0, "pass": 0, "data": 0, "honest": 0})
        entry["total"] += 1
        if r["pass"] == "True":
            entry["pass"] += 1
        if r.get("grade") == "answered-with-data":
            entry["data"] += 1
        elif r.get("grade") == "honest-capability-answer":
            entry["honest"] += 1
    if by_role:
        md_lines += [
            "",
            "## Per-stakeholder rates",
            "",
            "| Stakeholder role | Total | Data-backed | Honest-decline | Fail | Combined |",
            "|---|---|---|---|---|---|",
        ]
        for role in sorted(by_role, key=lambda k: -by_role[k]["total"]):
            e = by_role[role]
            rate = 100 * e["pass"] / e["total"] if e["total"] else 0
            md_lines.append(
                f"| {role} | {e['total']} | {e['data']} | {e['honest']} "
                f"| {e['total'] - e['pass']} | {rate:.1f}% |"
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

    # Machine-readable per-level summary (for figures / cross-run comparison)
    summary_path = md_path.with_name(md_path.stem + "_summary.csv")
    with open(summary_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(
            ["level", "name", "total", "data_backed", "honest_decline", "fail", "combined_pass"]
        )
        for lv in sorted(by_level.keys(), key=lambda x: int(x) if x.isdigit() else 99):
            e = by_level[lv]
            w.writerow(
                [
                    lv,
                    _LEVEL_NAMES.get(lv, lv),
                    e["total"],
                    e["data"],
                    e["honest"],
                    e["total"] - e["pass"],
                    e["pass"],
                ]
            )
        w.writerow(["ALL", "", total, data_backed, honest_decline, total - passed, passed])
        # V5-T01: role rollup rows (level column prefixed 'role:' to stay one file)
        for role in sorted(by_role, key=lambda k: -by_role[k]["total"]):
            e = by_role[role]
            w.writerow(
                [
                    f"role:{role}",
                    role,
                    e["total"],
                    e["data"],
                    e["honest"],
                    e["total"] - e["pass"],
                    e["pass"],
                ]
            )

    _safe_print(f"\n[report] Written {md_path.name} + {summary_path.name}")
    if invalid_rows:
        _safe_print(
            f"[report] WARNING: {len(invalid_rows)} question(s) got NO response "
            "(stack down/restarting mid-run) — excluded from the rates below; this run "
            "is NOT certification grade unless that count is 0."
        )
    _safe_print(
        f"[report] OVERALL: data-backed {data_backed}/{total} = {db_rate:.1f}%"
        f" | honest-decline {honest_decline}/{total} = {hd_rate:.1f}%"
        f" | combined {passed}/{total} = {pass_rate:.1f}% (legacy; see NOTE-142)"
    )
    for lv in sorted(by_level.keys(), key=lambda x: int(x) if x.isdigit() else 99):
        entry = by_level[lv]
        rate = 100 * entry["pass"] / entry["total"] if entry["total"] else 0
        lv_label = f"L{lv}" if str(lv).isdigit() else str(lv)
        _safe_print(
            f"  {lv_label}: data {entry['data']} | honest {entry['honest']}"
            f" | fail {entry['total'] - entry['pass']} of {entry['total']}"
            f" (combined {rate:.1f}%)"
        )


# ─── Main ─────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Corpus replay harness — T28 V3 evaluation")
    p.add_argument(
        "--sample",
        type=int,
        default=240,
        help="Total questions to replay (must be divisible by 6; default 240)",
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
    p.add_argument(
        "--strata-source",
        default=None,
        help=(
            "L7 bank CSV (V4-T27): replay THIS curated question set instead of the "
            "master-table stratified sample (columns: ID/qid, Question/question, "
            "l7_stratum, expected_behavior). All rows run; --sample is ignored."
        ),
    )
    return p


def main() -> int:
    args = _build_parser().parse_args()

    per_level = args.sample // 6
    if not getattr(args, "strata_source", None) and per_level * 6 != args.sample:
        _safe_print(
            f"[error] --sample must be divisible by 6 (6 latent levels); " f"got {args.sample}"
        )
        return 1

    # ── Output paths ──────────────────────────────────────────────────────────
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = args.out_prefix or datetime.utcnow().strftime("replay_%Y%m%d_%H%M%S")
    checkpoint_path = _OUTPUT_DIR / f"{ts}.csv"
    final_csv_path = _OUTPUT_DIR / f"{ts}_final.csv"
    md_path = _OUTPUT_DIR / f"{ts}.md"
    #: Full responses, one JSON object per line. The CSV keeps a 300-char preview;
    #: this keeps what was actually said, which is what re-grading and any claim
    #: about a wrong answer depends on.
    transcript_path = _OUTPUT_DIR / f"{ts}_transcript.jsonl"

    # ── Load + sample ─────────────────────────────────────────────────────────
    master_path = Path(args.master_table)
    if not getattr(args, "strata_source", None) and not master_path.is_file():
        _safe_print(f"[error] Master table not found: {master_path}")
        # paper/ holds survey responses and an unpublished writeup, so it is no
        # longer tracked in git — a fresh clone will not have it. Point the flag
        # at your own copy rather than expecting it to be checked out.
        _safe_print(
            "[error] The paper/ corpus is not part of the repository. "
            "Pass --master-table /path/to/complexity_master_table.csv to use your own copy."
        )
        return 1

    if getattr(args, "strata_source", None):
        # L7 bank mode (V4-T27): curated question set replaces the master-table
        # stratified sample — every bank row runs
        sample = _load_strata_source(Path(args.strata_source))
        _safe_print(f"[run] L7 bank: {len(sample)} questions from {args.strata_source}")
    else:
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

    _safe_print(f"\n[run] Replaying {len(pending)} questions against {args.base_url} ...")

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
            "expected_behavior": q_row.get("expected_behavior", ""),
            "l7_stratum": q_row.get("l7_stratum", ""),
            "stakeholder_role": q_row.get("stakeholder_role", ""),
            "register": q_row.get("register", ""),
        }

        _append_row(checkpoint_path, row, first=first_write)
        _append_transcript(transcript_path, qid, question, answer, row)
        first_write = False
        completed_rows.append(row)

        icon = "[PASS]" if is_pass else "[FAIL]"
        _safe_print(f"         {icon} grade={grade} elapsed={elapsed}s")

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
