"""
OntoSage Survey Question Evaluator
==================================

This script evaluates hundreds or thousands of questions (from a CSV file)
by passing each one dynamically through the OntoSage /chat completions API.

Features:
- Auto-resumes: If the script is stopped, just run it again. It automatically
  detects the existing output CSV, skips processed questions, and resumes.
- Real-time save: Writes directly to disk after EVERY request so no data is lost.
- Graceful error handling: Records API timeouts/errors without dropping the loop.

Usage Examples:
---------------
1. Run all questions (default behavior):
   python scripts/evaluate_survey_questions.py

2. Run a short test batch of 50 questions:
   python scripts/evaluate_survey_questions.py --limit 50

3. Run answers from the perspective of an occupant (slower delay to prevent server overload):
   python scripts/evaluate_survey_questions.py --persona occupant --delay 1.0

Command Line Arguments:
-----------------------
  --input    : Path to input CSV (Default: paper/Survey analysis and results/inputs/questions_only.csv)
  --output   : Path to output CSV (Default: paper/Survey analysis and results/outputs/survey_evaluation_results.csv)
  --persona  : Persona to assume for the response (e.g. general, occupant, facility_manager)
  --building : Building ID to use (Default: reads from .env or 'bldg1')
  --limit    : Max number of questions to process (0 for unlimited)
  --delay    : Seconds to delay between requests to avoid overloading the local API (Default: 0.5)
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Ensure we have httpx, fallback to urllib if not (httpx is preferred for async/speed)
try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    import urllib.request
    import urllib.error

    HAS_HTTPX = False


def ensure_utf8_stdout():
    """Ensure console can print Unicode without crashing (Windows cp1252 fix)."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    elif sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        import io

        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )


def _clean_question(q: str) -> str:
    """Strip quotes, whitespace, and normalize the question text."""
    return q.strip().strip('"').strip()


def send_chat_request(
    endpoint: str,
    question: str,
    persona: str = "general",
    building_id: str = "bldg1",
    timeout: float = 60.0,
) -> tuple[Optional[str], float, Optional[str]]:
    """
    Sends a request to the OntoSage /v1/chat/completions endpoint.
    Returns: (response_text, latency_seconds, error_string)
    """
    payload = {
        "model": "ontobot-pipeline",
        "messages": [{"role": "user", "content": question}],
        "persona": persona,
        "building_id": building_id,
        "stream": False,
    }

    headers = {"Content-Type": "application/json", "Authorization": "Bearer evaluation_script"}

    start_time = time.time()
    try:
        if HAS_HTTPX:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(endpoint, json=payload, headers=headers)
                latency = time.time() - start_time
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content, latency, None
        else:
            # Fallback to urllib
            req = urllib.request.Request(
                endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
                latency = time.time() - start_time
                content = result["choices"][0]["message"]["content"]
                return content, latency, None

    except Exception as e:
        latency = time.time() - start_time
        err_msg = str(e)
        if HAS_HTTPX and isinstance(e, httpx.HTTPStatusError):
            err_msg = f"HTTP {e.response.status_code}: {e.response.text}"
        return None, latency, err_msg


def main():
    ensure_utf8_stdout()

    parser = argparse.ArgumentParser(
        description="Evaluate OntoSage system using a CSV of survey questions."
    )
    parser.add_argument(
        "--input",
        default=os.path.join(
            "paper", "Survey analysis and results", "inputs", "questions_only.csv"
        ),
        help="Path to the input CSV file containing questions (one per line).",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(
            "paper", "Survey analysis and results", "outputs", "survey_evaluation_results.csv"
        ),
        help="Path to save the output CSV. It will be appended to dynamically.",
    )
    parser.add_argument(
        "--endpoint",
        default="http://localhost:8000/v1/chat/completions",
        help="OntoSage openwebui completions API endpoint.",
    )
    parser.add_argument(
        "--persona",
        default="general",
        help="Persona to use for the evaluation (e.g. general, occupant, facility_manager).",
    )
    parser.add_argument(
        "--building",
        default=os.environ.get("BUILDING_ID", "bldg1"),
        help="Building ID to supply to the system.",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="Only process this many questions (0 for all)."
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay in seconds between requests to prevent overwhelming the server.",
    )
    args = parser.parse_args()

    # --- 1. Load questions from input CSV ---
    if not os.path.isfile(args.input):
        print(f"?? Error: Input file not found: {args.input}")
        sys.exit(1)

    questions = []
    try:
        with open(args.input, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                q = _clean_question(row[0])
                if q:
                    questions.append(q)
    except Exception as e:
        print(f"?? Error reading input file: {e}")
        sys.exit(1)

    total_questions = len(questions)
    print(f"?? Loaded {total_questions} questions from {args.input}")

    # --- 2. Handle Resumption (Check existing output) ---
    processed_questions = set()
    output_exists = os.path.isfile(args.output)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    if output_exists:
        try:
            with open(args.output, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Keep track of questions we've already successfully processed or permanently failed
                    processed_questions.add(_clean_question(row.get("question", "")))
            print(
                f"?? Found existing output file. Skipping {len(processed_questions)} already processed questions."
            )
        except Exception as e:
            print(
                f"?? Warning: Could not read existing output file ({e}). Starting fresh or appending."
            )

    # Apply limits and filter out already processed exactly
    # We use a list to preserve ordering while filtering
    remaining_tasks = []
    for q in questions:
        if q not in processed_questions:
            remaining_tasks.append(q)

    if args.limit > 0:
        remaining_tasks = remaining_tasks[: args.limit]

    if not remaining_tasks:
        print("?? All questions have been processed! Exiting.")
        sys.exit(0)

    print(f"?? Starting evaluation on {len(remaining_tasks)} questions...")
    print(f"   Endpoint: {args.endpoint}")
    print(f"   Persona : {args.persona}")
    print(f"   Building: {args.building}")
    print("=" * 80)

    # --- 3. Process Questions & Write to CSV Iteratively ---
    fieldnames = ["timestamp", "question", "persona", "latency_sec", "response", "error"]

    # Open file in append mode. Write header if it's a new file.
    with open(args.output, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not output_exists or os.path.getsize(args.output) == 0:
            writer.writeheader()

        success_count = 0
        error_count = 0

        for i, question in enumerate(remaining_tasks, 1):
            sys.stdout.write(f"[{i}/{len(remaining_tasks)}] Q: {question[:60]}... ")
            sys.stdout.flush()

            response, latency, error = send_chat_request(
                endpoint=args.endpoint,
                question=question,
                persona=args.persona,
                building_id=args.building,
            )

            timestamp = datetime.now().isoformat(timespec="seconds")

            if error:
                sys.stdout.write(f"?? ERROR ({latency:.1f}s)\n")
                error_count += 1
            else:
                sys.stdout.write(f"? OK ({latency:.1f}s)\n")
                success_count += 1

            # Append to file and flush immediately
            writer.writerow(
                {
                    "timestamp": timestamp,
                    "question": question,
                    "persona": args.persona,
                    "latency_sec": f"{latency:.2f}",
                    "response": response if response else "",
                    "error": error if error else "",
                }
            )
            f.flush()  # Crucial: Ensures data is on disk after every turn

            # Sleep to prevent overwhelming the local orchestrator
            if i < len(remaining_tasks) and args.delay > 0:
                time.sleep(args.delay)

    print("=" * 80)
    print(f"?? Evaluation Complete!")
    print(f"?? Successful: {success_count}/{len(remaining_tasks)}")
    print(f"?? Errors:     {error_count}/{len(remaining_tasks)}")
    print(f"?? Results saved to: {args.output}")


if __name__ == "__main__":
    main()
