#!/usr/bin/env python3
"""
B3_irr_llm_coder.py
===================
Produce Coder-B (LLM) annotations for the 300-question IRR sample.
Coder A = deterministic lexicon classifier (machine_* columns in irr_samples.csv).

Outputs:
  taxonomy/irr_samples_coderB_llm.csv   — one row per question with LLM labels
  taxonomy/irr_coderB_run.log           — per-question trace for audit

Usage:
  python scripts/B3_irr_llm_coder.py
  python scripts/B3_irr_llm_coder.py --model gpt-4o-mini   # cheaper smoke test
  python scripts/B3_irr_llm_coder.py --turns 5              # first 5 rows only
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

# Load .env from repo root (two levels up: scripts/ → Survey analysis and results/ → paper/ → root)
try:
    from dotenv import load_dotenv
    _env = Path(__file__).resolve().parent.parent.parent.parent / ".env"
    load_dotenv(_env)
except ImportError:
    pass

from openai import OpenAI

HERE = Path(__file__).resolve().parent
SURVEY_ROOT = HERE.parent
IRR_SAMPLE = SURVEY_ROOT / "taxonomy" / "irr_samples.csv"
OUT_CSV = SURVEY_ROOT / "taxonomy" / "irr_samples_coderB_llm.csv"
RUN_LOG = SURVEY_ROOT / "taxonomy" / "irr_coderB_run.log"

VALID = {
    "domain_l1": {
        "THERMAL", "AIR_QUALITY", "ENERGY", "LIGHTING", "OCCUPANCY", "SAFETY",
        "SECURITY", "MAINTENANCE", "WATER", "WASTE", "SUSTAINABILITY", "WELLBEING",
        "WAYFINDING", "CONTROL", "INFO_REQUEST", "PRIVACY", "ACCESSIBILITY",
        "TRANSPORT", "WEATHER_OUTDOOR", "OTHER",
    },
    "query_type_l2": {
        "STATUS", "HISTORICAL", "COMPARISON", "ANOMALY",
        "RECOMMENDATION", "DIAGNOSTIC", "CAPABILITY",
    },
    "intent": {"INFORMATIONAL", "DIAGNOSTIC", "PRESCRIPTIVE", "PREDICTIVE"},
    "temporal": {"REALTIME", "HISTORICAL", "PREDICTIVE", "STATIC"},
    "spatial": {"POINT", "ROOM", "FLOOR", "BUILDING", "CAMPUS", "UNSPECIFIED"},
    "complexity": {"LOOKUP", "AGGREGATION", "MULTI_STEP"},
}

SYSTEM_PROMPT = """\
You are a building-informatics taxonomy expert. Classify each natural-language
query a building occupant might ask, using EXACTLY the codes below.

DIMENSION 1 — domain_l1 (20 codes):
THERMAL, AIR_QUALITY, ENERGY, LIGHTING, OCCUPANCY, SAFETY, SECURITY, MAINTENANCE,
WATER, WASTE, SUSTAINABILITY, WELLBEING, WAYFINDING, CONTROL, INFO_REQUEST, PRIVACY,
ACCESSIBILITY, TRANSPORT, WEATHER_OUTDOOR, OTHER

Rules:
- OTHER = off-topic, gibberish, fewer than 3 meaningful building-related words
- If two domains apply, pick the one the ANSWER would primarily report on

DIMENSION 2 — query_type_l2 (7 codes, apply priority order):
ANOMALY > RECOMMENDATION > DIAGNOSTIC > COMPARISON > HISTORICAL > STATUS > CAPABILITY

ANOMALY  = "Is X too high/low?", out-of-range check
RECOMMENDATION = "What should I do?", "How can I improve?"
DIAGNOSTIC = "Why is X?", cause-seeking
COMPARISON = "Compare A and B", "Which is better?"
HISTORICAL = "Show me last week", "What was X yesterday?"
STATUS = "What is X right now?", current-state lookup
CAPABILITY = "Can the building / system do X?", "Is there a sensor for?"

DIMENSION 3 — intent (4 codes):
INFORMATIONAL, DIAGNOSTIC, PRESCRIPTIVE, PREDICTIVE

DIMENSION 4 — temporal (4 codes):
REALTIME = current/live  |  HISTORICAL = past values  |  PREDICTIVE = future forecast
STATIC = time-invariant fact (building dimensions, policies, certifications)

DIMENSION 5 — spatial (6 codes):
POINT = single sensor/device  |  ROOM = one room/zone  |  FLOOR = one floor/wing
BUILDING = whole building  |  CAMPUS = multiple buildings or outdoor  |  UNSPECIFIED = no spatial cue

DIMENSION 6 — complexity (3 codes):
LOOKUP = single lookup / single SPARQL row
AGGREGATION = mean / sum / count / groupby
MULTI_STEP = multi-source join, planning, forecasting, or analytics chain

Respond ONLY with a JSON object — no markdown, no explanation:
{
  "domain_l1": "<code>",
  "query_type_l2": "<code>",
  "intent": "<code>",
  "temporal": "<code>",
  "spatial": "<code>",
  "complexity": "<code>",
  "coder_notes": "<optional: one sentence if genuinely ambiguous, else empty string>"
}
"""


def classify_one(client: OpenAI, question: str, model: str, retries: int = 4) -> dict:
    """Call LLM to classify one question; retry with backoff on transient errors."""
    user_msg = f'Question: "{question}"'
    delay = 2.0
    last_err = None
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0,
                response_format={"type": "json_object"},
                timeout=30,
            )
            raw = resp.choices[0].message.content.strip()
            parsed = json.loads(raw)
            # Validate and uppercase all codes
            result = {}
            for dim, valid_set in VALID.items():
                val = str(parsed.get(dim, "")).strip().upper()
                if val not in valid_set:
                    # Attempt fuzzy fix: find closest valid code
                    matches = [v for v in valid_set if v.startswith(val[:4])]
                    val = matches[0] if matches else next(iter(valid_set))
                result[dim] = val
            result["coder_notes"] = parsed.get("coder_notes", "")[:200]
            return result
        except Exception as exc:
            last_err = exc
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
    raise RuntimeError(f"classify_one failed after {retries} attempts: {last_err}")


def load_done(out_csv: Path) -> set[str]:
    """Return set of (PID, Stage, question_text) already in output file."""
    done = set()
    if not out_csv.exists():
        return done
    with open(out_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            done.add((row["PID"], row["Stage"], row["Question"]))
    return done


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4o", help="OpenAI model name")
    parser.add_argument("--turns", type=int, default=0, help="Stop after N rows (0=all)")
    args = parser.parse_args()

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key or not api_key.startswith("sk-"):
        sys.exit("OPENAI_API_KEY not set. Export it or add to .env at the repo root.")

    client = OpenAI(api_key=api_key)

    # Load input sample
    with open(IRR_SAMPLE, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"IRR sample: {len(rows)} questions")

    done = load_done(OUT_CSV)
    print(f"Already coded: {len(done)}  Remaining: {len(rows) - len(done)}")

    out_fields = [
        "PID", "Stage", "Question",
        "domain_l1", "query_type_l2", "intent", "temporal", "spatial", "complexity",
        "coder_notes",
    ]

    # Open for append if resuming
    mode = "a" if OUT_CSV.exists() and done else "w"
    out_f = open(OUT_CSV, mode, newline="", encoding="utf-8")
    writer = csv.DictWriter(out_f, fieldnames=out_fields)
    if mode == "w":
        writer.writeheader()

    log_f = open(RUN_LOG, "a", encoding="utf-8")

    coded = 0
    skipped = 0
    for i, row in enumerate(rows):
        key = (row["PID"], row["Stage"], row["Question"])
        if key in done:
            skipped += 1
            continue

        question = row["Question"].strip()
        if not question:
            continue

        try:
            labels = classify_one(client, question, args.model)
        except RuntimeError as e:
            log_f.write(f"ERROR row {i}: {e}\n")
            print(f"  ERROR row {i}: {e}", file=sys.stderr)
            continue

        out_row = {
            "PID": row["PID"],
            "Stage": row["Stage"],
            "Question": question,
            **labels,
        }
        writer.writerow(out_row)
        out_f.flush()

        log_f.write(
            f"row {i}: [{labels['domain_l1']}|{labels['query_type_l2']}|"
            f"{labels['intent']}|{labels['temporal']}|{labels['spatial']}|"
            f"{labels['complexity']}] {question[:80]}\n"
        )
        coded += 1
        if coded % 25 == 0:
            print(f"  Coded {coded + skipped}/{len(rows)} ...")

        if args.turns and coded >= args.turns:
            print(f"  --turns {args.turns} reached, stopping.")
            break

        # Gentle rate-limit pause between calls
        time.sleep(0.3)

    out_f.close()
    log_f.close()

    total_in_file = sum(1 for _ in open(OUT_CSV, encoding="utf-8")) - 1  # minus header
    print(f"\nDone. Coded {coded} new rows ({skipped} skipped). "
          f"Total in {OUT_CSV.name}: {total_in_file}")


if __name__ == "__main__":
    main()
