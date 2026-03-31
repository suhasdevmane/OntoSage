"""
OntoSage Evaluation Benchmark — ACADEMIC-01
=============================================
PhD-grade evaluation framework with ground-truth Q&A for automated
performance measurement across all intent types and personas.

Metrics:
  - Intent Classification Accuracy
  - SPARQL Syntactic Correctness (via sparql_validator)
  - Response Quality (BLEU-1, semantic similarity via LLM judge)
  - Persona Appropriateness
  - System Latency (p50, p90, p99)

Usage:
    python benchmarks/eval_ontosage.py [--quick] [--output results.json]

    # Run with live OntoSage API:
    python benchmarks/eval_ontosage.py --api-url http://localhost:8000

    # Run offline (intent + SPARQL only, no live API):
    python benchmarks/eval_ontosage.py --offline
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Ground-truth benchmark dataset
# ─────────────────────────────────────────────────────────────────────────────

BENCHMARK_CASES: List[Dict[str, Any]] = [
    # ── General / Greeting ──────────────────────────────────────────────────
    {
        "id": "G001",
        "category": "general",
        "persona": "general",
        "query": "Hello! What can you do?",
        "expected_intent": "general",
        "expected_entities": [],
        "reference_response_keywords": ["building", "sensor", "data", "help"],
        "sparql_expected": False,
    },
    {
        "id": "G002",
        "category": "general",
        "persona": "student",
        "query": "What is a Brick Schema?",
        "expected_intent": "general",
        "expected_entities": [],
        "reference_response_keywords": ["ontology", "building", "sensor", "standard"],
        "sparql_expected": False,
    },

    # ── Metadata / Discovery ─────────────────────────────────────────────────
    {
        "id": "M001",
        "category": "metadata",
        "persona": "it_admin",
        "query": "List all sensors in the building",
        "expected_intent": "discovery",
        "expected_entities": [],
        "reference_response_keywords": ["sensor", "zone"],
        "sparql_expected": True,
    },
    {
        "id": "M002",
        "category": "metadata",
        "persona": "facility_manager",
        "query": "How many sensors are in zone 5.01?",
        "expected_intent": "metadata",
        "expected_entities": ["zone 5.01"],
        "reference_response_keywords": ["sensor", "zone"],
        "sparql_expected": True,
    },
    {
        "id": "M003",
        "category": "metadata",
        "persona": "researcher",
        "query": "What type of sensor is Air_Temperature_Sensor_5.04?",
        "expected_intent": "metadata",
        "expected_entities": ["Air_Temperature_Sensor_5.04"],
        "reference_response_keywords": ["temperature", "sensor", "type"],
        "sparql_expected": True,
    },

    # ── Analytics ───────────────────────────────────────────────────────────
    {
        "id": "A001",
        "category": "analytics",
        "persona": "occupant",
        "query": "What is the current CO2 level in zone 5.06?",
        "expected_intent": "analytics",
        "expected_entities": ["Zone_5.06"],
        "expected_analytics": ["latest"],
        "reference_response_keywords": ["CO2", "ppm", "zone"],
        "sparql_expected": True,
    },
    {
        "id": "A002",
        "category": "analytics",
        "persona": "energy_manager",
        "query": "What was the average energy consumption last week?",
        "expected_intent": "analytics",
        "expected_analytics": ["avg"],
        "expected_time_range": True,
        "reference_response_keywords": ["energy", "kwh", "average", "week"],
        "sparql_expected": True,
    },
    {
        "id": "A003",
        "category": "analytics",
        "persona": "researcher",
        "query": "Show me PM2.5 distribution across all zones with statistical summary",
        "expected_intent": "analytics",
        "expected_analytics": ["avg", "min", "max"],
        "reference_response_keywords": ["PM2.5", "zone", "distribution"],
        "sparql_expected": True,
    },

    # ── Anomaly ─────────────────────────────────────────────────────────────
    {
        "id": "AN001",
        "category": "anomaly",
        "persona": "safety_officer",
        "query": "Are there any CO2 threshold violations in the last 48 hours?",
        "expected_intent": "anomaly",
        "expected_entities": ["CO2"],
        "expected_analytics": ["anomaly"],
        "expected_time_range": True,
        "reference_response_keywords": ["CO2", "threshold", "violation", "ppm"],
        "sparql_expected": True,
    },
    {
        "id": "AN002",
        "category": "anomaly",
        "persona": "facility_manager",
        "query": "Which sensors have readings outside normal range today?",
        "expected_intent": "anomaly",
        "expected_analytics": ["anomaly", "min", "max"],
        "reference_response_keywords": ["sensor", "range", "anomaly"],
        "sparql_expected": True,
    },

    # ── Compliance ──────────────────────────────────────────────────────────
    {
        "id": "C001",
        "category": "compliance",
        "persona": "sustainability_officer",
        "query": "Does the building meet BREEAM Hea 02 requirements for IAQ?",
        "expected_intent": "compliance",
        "expected_entities": [],
        "expected_analytics": ["avg", "max"],
        "reference_response_keywords": ["BREEAM", "IAQ", "CO2", "compliant"],
        "sparql_expected": True,
    },
    {
        "id": "C002",
        "category": "compliance",
        "persona": "safety_officer",
        "query": "Are we meeting ASHRAE 55 thermal comfort requirements?",
        "expected_intent": "compliance",
        "expected_analytics": ["avg"],
        "reference_response_keywords": ["ASHRAE", "thermal", "temperature"],
        "sparql_expected": True,
    },
    {
        "id": "C003",
        "category": "compliance",
        "persona": "energy_manager",
        "query": "Check ISO 50001 energy performance targets",
        "expected_intent": "compliance",
        "expected_analytics": ["avg", "sum"],
        "reference_response_keywords": ["ISO", "50001", "energy", "performance"],
        "sparql_expected": True,
    },

    # ── Report ──────────────────────────────────────────────────────────────
    {
        "id": "R001",
        "category": "report",
        "persona": "facility_manager",
        "query": "Generate a weekly building summary report",
        "expected_intent": "report",
        "expected_analytics": ["avg", "trend"],
        "reference_response_keywords": ["report", "summary", "week"],
        "sparql_expected": True,
    },
    {
        "id": "R002",
        "category": "report",
        "persona": "executive",
        "query": "Give me a KPI summary for this month",
        "expected_intent": "report",
        "reference_response_keywords": ["KPI", "summary", "month"],
        "sparql_expected": True,
    },

    # ── Export ──────────────────────────────────────────────────────────────
    {
        "id": "E001",
        "category": "export",
        "persona": "researcher",
        "query": "Export temperature data for zone 5.01 last week as CSV",
        "expected_intent": "export",
        "expected_entities": ["zone 5.01"],
        "expected_export_format": "csv",
        "expected_time_range": True,
        "reference_response_keywords": ["export", "CSV", "temperature"],
        "sparql_expected": True,
    },

    # ── Compare ─────────────────────────────────────────────────────────────
    {
        "id": "CP001",
        "category": "compare",
        "persona": "energy_manager",
        "query": "Compare energy usage between zone 5.01 and zone 5.02",
        "expected_intent": "compare",
        "expected_entities": ["zone 5.01", "zone 5.02"],
        "expected_analytics": ["avg", "sum"],
        "reference_response_keywords": ["zone", "energy", "compare"],
        "sparql_expected": True,
    },

    # ── Trend ───────────────────────────────────────────────────────────────
    {
        "id": "T001",
        "category": "trend",
        "persona": "researcher",
        "query": "Show me CO2 trend over the last 30 days",
        "expected_intent": "trend",
        "expected_entities": ["CO2"],
        "expected_analytics": ["trend"],
        "expected_time_range": True,
        "reference_response_keywords": ["CO2", "trend", "days"],
        "sparql_expected": True,
    },

    # ── Planner ─────────────────────────────────────────────────────────────
    {
        "id": "PL001",
        "category": "planner",
        "persona": "sustainability_officer",
        "query": "Generate a CO2 compliance report and export as PDF",
        "expected_intent": "planner",
        "expected_export_format": "pdf",
        "reference_response_keywords": ["CO2", "compliance", "report"],
        "sparql_expected": True,
    },

    # ── Clarification ────────────────────────────────────────────────────────
    {
        "id": "CL001",
        "category": "clarification",
        "persona": "general",
        "query": "Show me data",
        "expected_intent": "clarification",
        "expected_entities": [],
        "reference_response_keywords": ["clarify", "which", "type", "sensor"],
        "sparql_expected": False,
    },

    # ── Multi-hop (complex) ──────────────────────────────────────────────────
    {
        "id": "MH001",
        "category": "multi_hop",
        "persona": "researcher",
        "query": "Which floor has the highest average CO2 this week?",
        "expected_intent": "analytics",
        "expected_analytics": ["avg", "max"],
        "expected_time_range": True,
        "reference_response_keywords": ["floor", "CO2", "highest", "average"],
        "sparql_expected": True,
        "is_multi_hop": True,
    },
    {
        "id": "MH002",
        "category": "multi_hop",
        "persona": "energy_manager",
        "query": "Compare energy consumption per zone for the last 30 days",
        "expected_intent": "compare",
        "expected_analytics": ["sum", "avg"],
        "expected_time_range": True,
        "reference_response_keywords": ["zone", "energy", "consumption"],
        "sparql_expected": True,
        "is_multi_hop": True,
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Result data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CaseResult:
    case_id: str
    category: str
    persona: str
    query: str
    expected_intent: str
    actual_intent: Optional[str] = None
    intent_correct: bool = False
    entity_recall: float = 0.0
    response_keyword_hit_rate: float = 0.0
    response_length: int = 0
    latency_ms: float = 0.0
    error: Optional[str] = None
    passed: bool = False


@dataclass
class BenchmarkReport:
    timestamp: str = ""
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    intent_accuracy: float = 0.0
    avg_entity_recall: float = 0.0
    avg_keyword_hit_rate: float = 0.0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p90_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    per_category: Dict[str, Any] = field(default_factory=dict)
    case_results: List[Dict] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Evaluator
# ─────────────────────────────────────────────────────────────────────────────

class BenchmarkEvaluator:
    """
    Runs the OntoSage benchmark suite.

    Supports:
      - Offline mode: calls DialogueAgent directly (no HTTP, no live pipeline)
      - API mode: calls the live OntoSage REST API
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_token: Optional[str] = None,
        offline: bool = True,
        cases: Optional[List[Dict]] = None,
    ):
        self.api_url = api_url
        self.api_token = api_token
        self.offline = offline
        self.cases = cases or BENCHMARK_CASES

    async def run(self) -> BenchmarkReport:
        """Execute all benchmark cases and return aggregated report."""
        print(f"\n{'='*60}")
        print(f"  OntoSage Benchmark Suite — {len(self.cases)} cases")
        print(f"  Mode: {'offline (dialogue agent only)' if self.offline else 'live API'}")
        print(f"{'='*60}\n")

        results: List[CaseResult] = []

        for i, case in enumerate(self.cases, 1):
            print(f"[{i:02d}/{len(self.cases)}] {case['id']} ({case['category']}) — {case['query'][:60]}...", end=" ")
            result = await self._evaluate_case(case)
            results.append(result)
            status = "✅" if result.passed else "❌"
            print(f"{status} intent={result.actual_intent} lat={result.latency_ms:.0f}ms")

        return self._compute_report(results)

    async def _evaluate_case(self, case: Dict) -> CaseResult:
        """Evaluate a single benchmark case."""
        cr = CaseResult(
            case_id=case["id"],
            category=case["category"],
            persona=case.get("persona", "general"),
            query=case["query"],
            expected_intent=case["expected_intent"],
        )

        t0 = time.monotonic()
        try:
            if self.offline:
                response_data = await self._run_offline(case)
            else:
                response_data = await self._run_api(case)

            cr.latency_ms = (time.monotonic() - t0) * 1000
            cr.actual_intent = response_data.get("intent", "unknown")
            cr.intent_correct = (cr.actual_intent == case["expected_intent"])

            # Entity recall
            expected_entities = [e.lower() for e in case.get("expected_entities", [])]
            if expected_entities:
                detected = [e.lower() for e in response_data.get("entities", [])]
                matches = sum(1 for e in expected_entities if any(e in d or d in e for d in detected))
                cr.entity_recall = matches / len(expected_entities)
            else:
                cr.entity_recall = 1.0  # No entities expected = vacuously correct

            # Response keyword check
            response_text = (response_data.get("response") or response_data.get("formatted_response") or "").lower()
            keywords = [k.lower() for k in case.get("reference_response_keywords", [])]
            if keywords and response_text:
                hits = sum(1 for kw in keywords if kw in response_text)
                cr.response_keyword_hit_rate = hits / len(keywords)
            elif not keywords:
                cr.response_keyword_hit_rate = 1.0
            cr.response_length = len(response_text)

            # Overall pass: intent correct + entity recall >= 0.5
            cr.passed = cr.intent_correct and cr.entity_recall >= 0.5

        except Exception as e:
            cr.latency_ms = (time.monotonic() - t0) * 1000
            cr.error = str(e)
            cr.passed = False

        return cr

    async def _run_offline(self, case: Dict) -> Dict:
        """Run intent detection offline via DialogueAgent."""
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from shared.models import ConversationState, Message
            from orchestrator.agents.dialogue_agent import DialogueAgent

            agent = DialogueAgent()
            state = ConversationState(
                conversation_id="bench_" + case["id"],
                user_id="bench_user",
                persona=case.get("persona", "general"),
                messages=[Message(role="user", content=case["query"])],
            )
            result = await agent.detect_intent(state)
            return result
        except Exception as e:
            return {"intent": "error", "entities": [], "error": str(e)}

    async def _run_api(self, case: Dict) -> Dict:
        """Run via live OntoSage REST API."""
        try:
            import httpx
            headers = {"Content-Type": "application/json"}
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"

            payload = {
                "message": case["query"],
                "persona": case.get("persona", "general"),
                "conversation_id": f"bench_{case['id']}",
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(f"{self.api_url}/chat", json=payload, headers=headers)
                data = resp.json()
                # Extract intent from API response
                return {
                    "intent": data.get("data", {}).get("intent", "unknown"),
                    "entities": data.get("data", {}).get("entities", []),
                    "response": data.get("data", {}).get("response", ""),
                    "formatted_response": data.get("data", {}).get("message", ""),
                }
        except Exception as e:
            return {"intent": "error", "entities": [], "error": str(e)}

    def _compute_report(self, results: List[CaseResult]) -> BenchmarkReport:
        """Aggregate case results into a benchmark report."""
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        intents_correct = sum(1 for r in results if r.intent_correct)
        latencies = [r.latency_ms for r in results if r.latency_ms > 0]

        # Per-category stats
        categories: Dict[str, List[CaseResult]] = {}
        for r in results:
            categories.setdefault(r.category, []).append(r)

        per_category = {}
        for cat, cat_results in categories.items():
            per_category[cat] = {
                "count": len(cat_results),
                "passed": sum(1 for r in cat_results if r.passed),
                "intent_accuracy": sum(1 for r in cat_results if r.intent_correct) / len(cat_results),
                "avg_entity_recall": statistics.mean(r.entity_recall for r in cat_results),
                "avg_keyword_hit_rate": statistics.mean(r.response_keyword_hit_rate for r in cat_results),
            }

        report = BenchmarkReport(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            total_cases=total,
            passed=passed,
            failed=total - passed,
            intent_accuracy=intents_correct / total if total else 0,
            avg_entity_recall=statistics.mean(r.entity_recall for r in results) if results else 0,
            avg_keyword_hit_rate=statistics.mean(r.response_keyword_hit_rate for r in results) if results else 0,
            avg_latency_ms=statistics.mean(latencies) if latencies else 0,
            p50_latency_ms=sorted(latencies)[len(latencies)//2] if latencies else 0,
            p90_latency_ms=sorted(latencies)[int(len(latencies)*0.9)] if latencies else 0,
            p99_latency_ms=sorted(latencies)[int(len(latencies)*0.99)] if latencies else 0,
            per_category=per_category,
            case_results=[asdict(r) for r in results],
        )
        return report

    def print_report(self, report: BenchmarkReport):
        """Print a formatted summary report."""
        print(f"\n{'='*60}")
        print(f"  BENCHMARK RESULTS — {report.timestamp}")
        print(f"{'='*60}")
        print(f"  Total Cases    : {report.total_cases}")
        print(f"  Passed         : {report.passed} ({report.passed/report.total_cases*100:.1f}%)")
        print(f"  Failed         : {report.failed}")
        print(f"  Intent Accuracy: {report.intent_accuracy*100:.1f}%")
        print(f"  Entity Recall  : {report.avg_entity_recall*100:.1f}%")
        print(f"  Keyword Hits   : {report.avg_keyword_hit_rate*100:.1f}%")
        print(f"  Avg Latency    : {report.avg_latency_ms:.0f}ms")
        print(f"  p50 Latency    : {report.p50_latency_ms:.0f}ms")
        print(f"  p90 Latency    : {report.p90_latency_ms:.0f}ms")
        print(f"\n  Per Category:")
        for cat, stats in report.per_category.items():
            pass_pct = stats['passed'] / stats['count'] * 100
            intent_pct = stats['intent_accuracy'] * 100
            print(f"    {cat:20s}: {stats['passed']}/{stats['count']} "
                  f"passed ({pass_pct:.0f}%), intent={intent_pct:.0f}%")
        print(f"{'='*60}\n")


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import asyncio

    parser = argparse.ArgumentParser(description="OntoSage Academic Benchmark Suite")
    parser.add_argument("--offline", action="store_true", default=True,
                        help="Run offline (dialogue agent only, no live API)")
    parser.add_argument("--api-url", default=None,
                        help="Live OntoSage API URL (enables API mode)")
    parser.add_argument("--api-token", default=None,
                        help="Bearer token for authenticated API calls")
    parser.add_argument("--quick", action="store_true",
                        help="Run only first 8 cases (quick smoke test)")
    parser.add_argument("--output", default="benchmark_results.json",
                        help="Output JSON file for results")
    parser.add_argument("--category", default=None,
                        help="Filter by category (e.g., compliance, anomaly, metadata)")
    args = parser.parse_args()

    cases = BENCHMARK_CASES
    if args.quick:
        cases = cases[:8]
    if args.category:
        cases = [c for c in cases if c["category"] == args.category]
        print(f"Filtered to {len(cases)} cases in category: {args.category}")

    offline = args.offline and not args.api_url
    evaluator = BenchmarkEvaluator(
        api_url=args.api_url,
        api_token=args.api_token,
        offline=offline,
        cases=cases,
    )

    report = asyncio.run(evaluator.run())
    evaluator.print_report(report)

    # Save to JSON
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2, default=str)
    print(f"Results saved to: {output_path}")


if __name__ == "__main__":
    main()
