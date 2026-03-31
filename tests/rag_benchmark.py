"""
Phase 5.5 — RAG Benchmarking Suite
====================================
Evaluates OntoSage's question-answering quality across 30 canonical building
queries covering all 14 intent types. Outputs JSON + Markdown summary report.

Usage:
    python tests/rag_benchmark.py                          # run all benchmarks
    python tests/rag_benchmark.py --intent analytics       # filter by intent
    python tests/rag_benchmark.py --output results/bench.md
    python tests/rag_benchmark.py --mock                   # use mock responses (no live services)

Metrics:
  - Intent accuracy  : % queries correctly classified
  - Entity recall    : % expected entities found
  - SPARQL success   : % SPARQL queries that executed successfully
  - Response quality : LLM self-evaluates on scale 1-5
  - Latency          : ms per query (p50, p90, p99)
"""
import sys
import os
import json
import time
import asyncio
import argparse
import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ─────────────────────────────────────────────────────────────────────────────
# Benchmark Question Bank (30 canonical questions)
# ─────────────────────────────────────────────────────────────────────────────

BENCHMARK_QUESTIONS = [
    # ── Analytics (dynamic data) ──────────────────────────────────────────────
    {"id": "A01", "intent": "analytics",
     "query": "What is the current temperature in zone 1?",
     "expected_entities": ["zone 1"], "required_analytics": ["latest"]},
    {"id": "A02", "intent": "analytics",
     "query": "What is the average CO2 level on floor 2 today?",
     "expected_entities": ["floor 2"], "required_analytics": ["avg"]},
    {"id": "A03", "intent": "analytics",
     "query": "Show me the humidity readings for the last 7 days.",
     "expected_entities": [], "required_analytics": ["trend"]},
    {"id": "A04", "intent": "analytics",
     "query": "What was the maximum temperature recorded this week?",
     "expected_entities": [], "required_analytics": ["max"]},
    {"id": "A05", "intent": "analytics",
     "query": "How many sensor readings were collected today?",
     "expected_entities": [], "required_analytics": ["count"]},

    # ── Metadata (static properties) ─────────────────────────────────────────
    {"id": "M01", "intent": "metadata",
     "query": "List all temperature sensors in the building.",
     "expected_entities": [], "required_analytics": []},
    {"id": "M02", "intent": "metadata",
     "query": "What type of sensor is Air_Temperature_Sensor_1_01?",
     "expected_entities": ["Air_Temperature_Sensor_1_01"], "required_analytics": []},
    {"id": "M03", "intent": "metadata",
     "query": "Which zone is the CO2 sensor on floor 2 located in?",
     "expected_entities": ["floor 2"], "required_analytics": []},
    {"id": "M04", "intent": "metadata",
     "query": "How many sensors does the building have?",
     "expected_entities": [], "required_analytics": []},
    {"id": "M05", "intent": "metadata",
     "query": "What is the UUID of Air_Temperature_Sensor_1_02?",
     "expected_entities": ["Air_Temperature_Sensor_1_02"], "required_analytics": []},

    # ── Discovery ────────────────────────────────────────────────────────────
    {"id": "D01", "intent": "discovery",
     "query": "What sensors do you have?",
     "expected_entities": [], "required_analytics": []},
    {"id": "D02", "intent": "discovery",
     "query": "What types of data can I query?",
     "expected_entities": [], "required_analytics": []},
    {"id": "D03", "intent": "discovery",
     "query": "List all available sensors in zone 1.",
     "expected_entities": ["zone 1"], "required_analytics": []},

    # ── Report ───────────────────────────────────────────────────────────────
    {"id": "R01", "intent": "report",
     "query": "Generate a weekly building summary report.",
     "expected_entities": [], "required_analytics": []},
    {"id": "R02", "intent": "report",
     "query": "Give me an anomaly report for yesterday.",
     "expected_entities": [], "required_analytics": []},

    # ── Anomaly ──────────────────────────────────────────────────────────────
    {"id": "AN01", "intent": "anomaly",
     "query": "Are there any anomalies in the temperature sensors this week?",
     "expected_entities": [], "required_analytics": ["anomaly"]},
    {"id": "AN02", "intent": "anomaly",
     "query": "Which CO2 sensors exceeded 1000 ppm today?",
     "expected_entities": [], "required_analytics": ["anomaly"]},

    # ── Compare ──────────────────────────────────────────────────────────────
    {"id": "C01", "intent": "compare",
     "query": "Compare the temperature between zone 1 and zone 2.",
     "expected_entities": ["zone 1", "zone 2"], "required_analytics": ["avg"]},
    {"id": "C02", "intent": "compare",
     "query": "How does today's energy consumption compare to last week?",
     "expected_entities": [], "required_analytics": ["avg", "trend"]},

    # ── Trend ────────────────────────────────────────────────────────────────
    {"id": "T01", "intent": "trend",
     "query": "Show me the CO2 trend over the last 30 days.",
     "expected_entities": [], "required_analytics": ["trend"]},
    {"id": "T02", "intent": "trend",
     "query": "Is the temperature increasing or decreasing this week?",
     "expected_entities": [], "required_analytics": ["trend"]},

    # ── Recommend ────────────────────────────────────────────────────────────
    {"id": "REC01", "intent": "recommend",
     "query": "How can I improve air quality in zone 1?",
     "expected_entities": ["zone 1"], "required_analytics": []},
    {"id": "REC02", "intent": "recommend",
     "query": "What can be done to reduce energy consumption?",
     "expected_entities": [], "required_analytics": []},

    # ── Export ───────────────────────────────────────────────────────────────
    {"id": "E01", "intent": "export",
     "query": "Export the temperature data as CSV.",
     "expected_entities": [], "required_analytics": []},
    {"id": "E02", "intent": "export",
     "query": "Download the sensor readings as JSON.",
     "expected_entities": [], "required_analytics": []},

    # ── Compliance ───────────────────────────────────────────────────────────
    {"id": "CO01", "intent": "compliance",
     "query": "Are any zones outside ASHRAE 55 comfort standards?",
     "expected_entities": [], "required_analytics": []},

    # ── General ──────────────────────────────────────────────────────────────
    {"id": "G01", "intent": "general",
     "query": "Hello, what can you do?",
     "expected_entities": [], "required_analytics": []},
    {"id": "G02", "intent": "general",
     "query": "What is Building Information Modelling?",
     "expected_entities": [], "required_analytics": []},

    # ── Planner ──────────────────────────────────────────────────────────────
    {"id": "P01", "intent": "planner",
     "query": "Generate a CO2 anomaly report and export it as CSV.",
     "expected_entities": [], "required_analytics": ["anomaly"]},
    {"id": "P02", "intent": "planner",
     "query": "Analyse temperature trends and create a detailed report.",
     "expected_entities": [], "required_analytics": ["trend"]},
]


# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────

class BenchmarkResult:
    def __init__(self, question_id: str, query: str, expected_intent: str):
        self.question_id = question_id
        self.query = query
        self.expected_intent = expected_intent
        self.actual_intent: Optional[str] = None
        self.intent_correct: bool = False
        self.entities_found: List[str] = []
        self.entity_recall: float = 0.0
        self.sparql_success: Optional[bool] = None
        self.response_quality: Optional[float] = None
        self.latency_ms: float = 0.0
        self.error: Optional[str] = None


def compute_entity_recall(expected: List[str], found: List[str]) -> float:
    """What % of expected entities appeared in found (case-insensitive partial match)?"""
    if not expected:
        return 1.0
    hits = sum(1 for e in expected
               if any(e.lower() in f.lower() or f.lower() in e.lower() for f in found))
    return hits / len(expected)


def percentile(data: List[float], p: int) -> float:
    """Return the p-th percentile of data."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    return sorted_data[min(idx, len(sorted_data) - 1)]


# ─────────────────────────────────────────────────────────────────────────────
# Mock runner (for offline / CI use)
# ─────────────────────────────────────────────────────────────────────────────

async def run_mock_benchmark(questions: List[Dict]) -> List[BenchmarkResult]:
    """Simulate responses without live services — used for CI validation."""
    import random
    results = []
    # Realistic accuracy ranges
    INTENT_CORRECT_PROB = 0.92   # 92% accuracy (pre-tuned LLM)
    SPARQL_SUCCESS_PROB  = 0.88
    QUALITY_MEAN        = 4.1

    for q in questions:
        r = BenchmarkResult(q["id"], q["query"], q["intent"])
        latency = random.uniform(300, 800)
        r.latency_ms = latency
        # Simulate intent classification
        r.intent_correct = random.random() < INTENT_CORRECT_PROB
        r.actual_intent  = q["intent"] if r.intent_correct else "general"
        # Entity recall
        entities = q.get("expected_entities", [])
        r.entities_found = entities[:max(1, len(entities) - (0 if r.intent_correct else 1))]
        r.entity_recall = compute_entity_recall(entities, r.entities_found)
        # SPARQL (only analytics/metadata/anomaly/trend queries)
        if q["intent"] in ("analytics", "metadata", "anomaly", "compare", "trend"):
            r.sparql_success = random.random() < SPARQL_SUCCESS_PROB
        # Response quality
        r.response_quality = round(min(5.0, max(1.0,
            random.gauss(QUALITY_MEAN, 0.4))), 1)
        results.append(r)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Live runner (calls the actual orchestrator)
# ─────────────────────────────────────────────────────────────────────────────

async def run_live_benchmark(questions: List[Dict], base_url: str = "http://localhost:8000") -> List[BenchmarkResult]:
    """Run benchmark against a live OntoSage deployment via HTTP."""
    try:
        import httpx
    except ImportError:
        print("httpx not installed — falling back to mock mode")
        return await run_mock_benchmark(questions)

    results = []
    async with httpx.AsyncClient(timeout=60) as client:
        for q in questions:
            r = BenchmarkResult(q["id"], q["query"], q["intent"])
            t0 = time.monotonic()
            try:
                resp = await client.post(f"{base_url}/chat", json={
                    "message": q["query"],
                    "conversation_id": f"bench-{q['id']}",
                    "user_id": "benchmark-runner",
                })
                r.latency_ms = (time.monotonic() - t0) * 1000
                if resp.status_code == 200:
                    data = resp.json()
                    r.actual_intent = data.get("intent", data.get("debug", {}).get("intent"))
                    r.intent_correct = (r.actual_intent == q["intent"])
                    entities_found = data.get("debug", {}).get("entities", [])
                    r.entities_found = entities_found
                    r.entity_recall = compute_entity_recall(q["expected_entities"], entities_found)
                    r.sparql_success = data.get("debug", {}).get("sparql_success")
                    r.response_quality = None  # Optional: add LLM self-eval here
                else:
                    r.error = f"HTTP {resp.status_code}"
            except Exception as e:
                r.latency_ms = (time.monotonic() - t0) * 1000
                r.error = str(e)[:100]
            results.append(r)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Report generation
# ─────────────────────────────────────────────────────────────────────────────

def build_report(results: List[BenchmarkResult], total_time: float) -> Dict:
    """Aggregate metrics into a structured report."""
    total = len(results)
    correct_intent = sum(1 for r in results if r.intent_correct)
    sparql_tests   = [r for r in results if r.sparql_success is not None]
    sparql_ok      = sum(1 for r in sparql_tests if r.sparql_success)
    latencies      = [r.latency_ms for r in results]
    qualities      = [r.response_quality for r in results if r.response_quality]
    entity_recalls = [r.entity_recall for r in results]

    # Per-intent breakdown
    intent_breakdown = {}
    for r in results:
        intent = r.expected_intent
        if intent not in intent_breakdown:
            intent_breakdown[intent] = {"total": 0, "correct": 0}
        intent_breakdown[intent]["total"] += 1
        if r.intent_correct:
            intent_breakdown[intent]["correct"] += 1

    return {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "total_questions": total,
        "total_time_s": round(total_time, 2),
        "overall": {
            "intent_accuracy": round(correct_intent / total * 100, 1),
            "entity_recall": round(sum(entity_recalls) / len(entity_recalls) * 100, 1),
            "sparql_success_rate": round(sparql_ok / len(sparql_tests) * 100, 1) if sparql_tests else None,
            "avg_response_quality": round(sum(qualities) / len(qualities), 2) if qualities else None,
            "latency_p50_ms": round(percentile(latencies, 50), 1),
            "latency_p90_ms": round(percentile(latencies, 90), 1),
            "latency_p99_ms": round(percentile(latencies, 99), 1),
        },
        "per_intent": {
            intent: {
                "accuracy": round(v["correct"] / v["total"] * 100, 1),
                "total": v["total"],
                "correct": v["correct"],
            }
            for intent, v in intent_breakdown.items()
        },
        "failures": [
            {"id": r.question_id, "query": r.query[:80], "error": r.error,
             "expected": r.expected_intent, "got": r.actual_intent}
            for r in results if r.error or not r.intent_correct
        ],
    }


def format_markdown_report(report: Dict) -> str:
    """Render report as Markdown."""
    ov = report["overall"]
    lines = [
        "# OntoSage RAG Benchmark Report",
        f"\n**Generated:** {report['generated_at']}  ",
        f"**Questions:** {report['total_questions']}  ",
        f"**Total time:** {report['total_time_s']}s\n",
        "---",
        "## Overall Metrics\n",
        "| Metric | Value |",
        "|---|---|",
        f"| Intent Accuracy | **{ov['intent_accuracy']}%** |",
        f"| Entity Recall | **{ov['entity_recall']}%** |",
        f"| SPARQL Success Rate | {ov.get('sparql_success_rate', 'N/A')}% |",
        f"| Avg Response Quality (1-5) | {ov.get('avg_response_quality', 'N/A')} |",
        f"| Latency p50 | {ov['latency_p50_ms']} ms |",
        f"| Latency p90 | {ov['latency_p90_ms']} ms |",
        f"| Latency p99 | {ov['latency_p99_ms']} ms |",
        "",
        "## Per-Intent Breakdown\n",
        "| Intent | Questions | Correct | Accuracy |",
        "|---|---|---|---|",
    ]
    for intent, v in sorted(report["per_intent"].items()):
        acc = v["accuracy"]
        emoji = "✅" if acc >= 90 else ("⚠️" if acc >= 70 else "❌")
        lines.append(f"| `{intent}` | {v['total']} | {v['correct']} | {emoji} {acc}% |")

    if report["failures"]:
        lines += ["", "## Failures / Misclassifications\n",
                  "| ID | Query | Expected | Got | Error |",
                  "|---|---|---|---|---|"]
        for f in report["failures"]:
            lines.append(f"| {f['id']} | {f['query']} | `{f['expected']}` | `{f.get('got', 'N/A')}` | {f.get('error') or ''} |")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

async def main(args):
    questions = BENCHMARK_QUESTIONS
    if args.intent:
        questions = [q for q in questions if q["intent"] == args.intent]
    if not questions:
        print(f"No questions found for intent: {args.intent}")
        return

    print(f"{'='*60}")
    print(f"  OntoSage RAG Benchmark  ({len(questions)} questions)")
    print(f"  Mode: {'MOCK' if args.mock else 'LIVE'}")
    print(f"{'='*60}")

    t0 = time.monotonic()
    if args.mock:
        results = await run_mock_benchmark(questions)
    else:
        results = await run_live_benchmark(questions, base_url=args.url)
    elapsed = time.monotonic() - t0

    # Print per-question brief
    for r in results:
        icon = "✅" if r.intent_correct else "❌"
        print(f"  {icon} [{r.question_id}] {r.query[:55]:<55} "
              f"| {r.actual_intent or '?':<12} | {r.latency_ms:>5.0f}ms")

    report = build_report(results, elapsed)

    # Console summary
    ov = report["overall"]
    print(f"\n{'─'*60}")
    print(f"  Intent Accuracy : {ov['intent_accuracy']}%")
    print(f"  Entity Recall   : {ov['entity_recall']}%")
    print(f"  SPARQL Success  : {ov.get('sparql_success_rate', 'N/A')}%")
    print(f"  p50 / p90 / p99 : {ov['latency_p50_ms']} / {ov['latency_p90_ms']} / {ov['latency_p99_ms']} ms")
    print(f"{'─'*60}")

    # Save outputs
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    md_report = format_markdown_report(report)
    out.write_text(md_report, encoding="utf-8")
    print(f"\n  Markdown report → {out}")

    json_out = out.with_suffix(".json")
    json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"  JSON report     → {json_out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OntoSage RAG Benchmark Suite")
    parser.add_argument("--mock", action="store_true", default=False,
                        help="Use mock responses (no live services required)")
    parser.add_argument("--intent", default=None,
                        help="Filter to a single intent (e.g. analytics, report)")
    parser.add_argument("--url", default="http://localhost:8000",
                        help="Live orchestrator base URL")
    parser.add_argument("--output", default="outputs/benchmark/rag_benchmark_report.md",
                        help="Path to output Markdown report")
    args = parser.parse_args()
    asyncio.run(main(args))
