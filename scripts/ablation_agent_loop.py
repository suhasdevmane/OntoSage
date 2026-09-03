# -*- coding: utf-8 -*-
"""
ablation_agent_loop.py — ablation (f): a ReAct tool-loop agent as the brain (V4-T29).

The strongest generic-agent baseline: the LLM gets REAL tools (read-only SPARQL
on the building graph + read-only SQL on the time-series DB) and must find its
own answer — discover sensors, resolve UUIDs, fetch rows, rank. No CQ-IR, no
deterministic scorer, no dossier, no guard. This is the "point Claude-Code at
the building" architecture, measured with the same independent GroundTruth as
ARBITER: top-1/top-3 agreement, invented values, plus loop-specific costs
(steps, tool errors, wall time).

RUN host-side (Ollama direct) with the stack up and saturation backfilled:
  OLLAMA_BASE_URL=http://localhost:11434 MYSQL_HOST=localhost \
    python -X utf8 scripts/ablation_agent_loop.py --runs 3
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))

import pymysql  # noqa: E402

from orchestrator.services.deliberation.coverage_audit import (  # noqa: E402
    CoverageAuditor,
    load_modalities,
)
from orchestrator.services.deliberation.live import (  # noqa: E402
    active_identity,
    sparql_exec,
)
from shared.db_clock import UTC_SESSION_INIT

# identical task set to ablation (b) — comparability across arms
_TASKS: List[Tuple[str, str, str, Optional[str]]] = [
    ("noise", "min", "Which 3 rooms are the quietest right now?", None),
    ("co2", "min", "Which 3 rooms have the lowest CO2 right now?", None),
    ("temperature", "max", "Which 3 rooms are the warmest right now?", None),
    ("occupancy", "min", "Which 3 rooms have the fewest people right now?", None),
    ("illuminance", "max", "Which 3 rooms are the brightest right now?", None),
]
_VALUE_TOLERANCE = 0.20
_MAX_STEPS = 8
_MAX_OBS_ROWS = 30

_SYSTEM = """You are an agent answering questions about a smart building.
Write PLAIN TEXT only — never use function-calling or tool-call syntax.
You can issue READ-ONLY queries. To run one, reply with EXACTLY one line starting with:
  RUN sparql: <a SPARQL SELECT query>
  RUN sql: <a SQL SELECT query>
When you know the answer, reply with FINAL: followed by three lines — one per
room, each as "<actual room label>: <actual numeric value>". Example shape:
  FINAL:
  ExampleRoomA: 41.2
  ExampleRoomB: 43.7
  ExampleRoomC: 44.0
Never output placeholder words; use the real room labels from your query results.

Facts about the building's data layout:
- The graph (SPARQL) holds a Brick ontology. Sensors link to storage via
  ref:hasExternalReference -> a node with ref:hasTimeseriesId (a UUID string)
  and ref:storedAt (a database key whose local name is the SQL table name).
  PREFIX brick: <https://brickschema.org/schema/Brick#>
  PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
  PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
- Rooms/zones relate to sensors via brick:hasLocation / brick:isPointOf / brick:hasPart.
- SQL tables are narrow: (uuid CHAR(36), datetime DATETIME, value DOUBLE).
- Always LIMIT your queries. Time is UTC; 'right now' means the newest readings.
Think briefly, then emit exactly one RUN line or a FINAL block."""


def _mysql():
    env = {}
    for line in open(_REPO_ROOT / ".env", encoding="utf-8"):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=env.get("MYSQL_USER", "root"),
        password=env.get("MYSQL_PASSWORD", "mysql"),
        database=env.get("MYSQL_DATABASE", "sensordb"),
        # Same clock the rows are stamped in (BUG-403).
        init_command=UTC_SESSION_INIT,
    )


def _load_truth():
    import importlib.util

    spec = importlib.util.spec_from_file_location("l7_grader", _SCRIPT_DIR / "l7_grader.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def _tool_sparql(query: str) -> str:
    try:
        res = await sparql_exec(query)
    except Exception as exc:
        return f"SPARQL error: {exc}"
    bindings = res.get("results", {}).get("bindings", [])
    if not bindings:
        return "SPARQL: 0 results"
    cols = res.get("head", {}).get("vars", [])
    lines = ["\t".join(cols)]
    for b in bindings[:_MAX_OBS_ROWS]:
        lines.append("\t".join(str(b.get(c, {}).get("value", "")) for c in cols))
    if len(bindings) > _MAX_OBS_ROWS:
        lines.append(f"... ({len(bindings) - _MAX_OBS_ROWS} more rows truncated)")
    return "\n".join(lines)


def _tool_sql(conn, query: str) -> str:
    q = query.strip().rstrip(";")
    if not re.match(r"(?is)^\s*select\b", q):
        return "SQL error: only SELECT is allowed"
    try:
        with conn.cursor() as cur:
            cur.execute(q)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description or []]
    except Exception as exc:
        return f"SQL error: {exc}"
    if not rows:
        return "SQL: 0 rows"
    lines = ["\t".join(cols)]
    for r in rows[:_MAX_OBS_ROWS]:
        lines.append("\t".join(str(v) for v in r))
    if len(rows) > _MAX_OBS_ROWS:
        lines.append(f"... ({len(rows) - _MAX_OBS_ROWS} more rows truncated)")
    return "\n".join(lines)


async def _ollama_generate(prompt: str) -> str:
    """Direct Ollama call — deliberately NO llm_manager: its circuit breaker
    (a production resilience feature) would short-circuit a benchmark after a
    burst of empty completions and turn the remaining runs into non-attempts."""
    import httpx

    base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "gpt-oss:20b")
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            f"{base}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0},
            },
        )
        resp.raise_for_status()
        return str(resp.json().get("response") or "")


async def _agent_answer(conn, question: str) -> Tuple[str, Dict]:
    """Run the ReAct loop; returns (final_text, loop_stats)."""
    transcript = f"{_SYSTEM}\n\nQuestion: {question}\n"
    stats = {"steps": 0, "sparql_calls": 0, "sql_calls": 0, "tool_errors": 0, "malformed": 0}
    for _ in range(_MAX_STEPS):
        stats["steps"] += 1
        try:
            reply = (await _ollama_generate(transcript)) or ""
            if not reply.strip():
                raise RuntimeError("empty completion (model drifted off the text channel)")
        except Exception as exc:
            # provider-side parse errors (e.g. the model drifting onto a native
            # tool-call channel) count as malformed agent turns, not crashes
            stats["malformed"] += 1
            stats["tool_errors"] += 1
            note = str(exc)[:120].replace("\n", " ")
            transcript += (
                f"\n(Your last reply failed to transmit: {note}. "
                "Reply in PLAIN TEXT with one RUN line or a FINAL block.)\n"
            )
            continue
        final = re.search(r"(?is)FINAL:\s*(.+)$", reply)
        if final:
            return final.group(1).strip(), stats
        m = re.search(r"(?im)^(?:RUN|TOOL)\s+(sparql|sql):\s*(.+?)\s*$", reply, re.DOTALL)
        if not m:
            stats["malformed"] += 1
            transcript += (
                "\n(Your last reply was not a valid RUN line or FINAL block. "
                "Reply with exactly one RUN line or a FINAL block.)\n"
            )
            continue
        kind, q = m.group(1).lower(), m.group(2).strip()
        obs = await _tool_sparql(q) if kind == "sparql" else _tool_sql(conn, q)
        stats["sparql_calls" if kind == "sparql" else "sql_calls"] += 1
        if obs.startswith(("SPARQL error", "SQL error")):
            stats["tool_errors"] += 1
        transcript += f"\nRUN {kind}: {q}\nOBSERVATION:\n{obs}\n"
    return "", stats  # step budget exhausted with no FINAL


async def _run(runs: int) -> int:
    grader = _load_truth()
    identity = active_identity()
    building_id, namespace = identity["BUILDING_ID"], identity["BUILDING_NAMESPACE"]
    auditor = CoverageAuditor(sparql_exec, load_modalities(building_id))
    spaces = await auditor.discover_spaces(namespace)
    truth = grader.GroundTruth(building_id, spaces)
    rooms = dict(truth._rooms)
    conn = _mysql()

    results = []
    for modality, direction, question, floor in _TASKS:
        series = truth._series(modality, rooms, 24.0)
        actual = {room: truth._aggregate(s, forecast=False) for room, s in series.items() if s}
        true_rank = truth.true_ranking_multi([(modality, direction)], floor)
        true_top3 = [r for r, _ in true_rank[:3]]

        for run in range(runs):
            t0 = time.monotonic()
            final, stats = await _agent_answer(conn, question)
            wall = round(time.monotonic() - t0, 1)
            picked = re.findall(r"([A-Za-z][\w.]*\w)\s*[:\-]\s*(-?\d+(?:\.\d+)?)?", final)
            _placeholders = {
                "room_name",
                "room",
                "name",
                "value",
                "examplerooma",
                "exampleroomb",
                "exampleroomc",
                "actual",
            }
            picked = [p for p in picked if p[0].lower() not in _placeholders]
            names = [p[0] for p in picked][:3]
            same = grader._same_space  # canonical: 'Room4.05' == 'Room 4.05 — Lab'
            top1_match = bool(names) and same(names[0], true_top3[0])
            top3_hit = bool(names) and any(same(names[0], t) for t in true_top3)
            invented = 0
            for name, value in picked[:3]:
                if not value:
                    continue
                real = next((v for r, v in actual.items() if same(r, name)), None)
                if real is None or abs(float(value) - real) > max(
                    abs(real) * _VALUE_TOLERANCE, 1.0
                ):
                    invented += 1
            results.append(
                {
                    "modality": modality,
                    "run": run + 1,
                    "agent_top1": names[0] if names else "",
                    "true_top1": true_top3[0],
                    "top1_match": top1_match,
                    "top3_hit": top3_hit,
                    "invented_values": invented,
                    "answered": bool(names),
                    "steps": stats["steps"],
                    "sparql_calls": stats["sparql_calls"],
                    "sql_calls": stats["sql_calls"],
                    "tool_errors": stats["tool_errors"],
                    "malformed": stats["malformed"],
                    "wall_secs": wall,
                }
            )
            print(
                f"[{modality} run{run + 1}] agent_top1={names[0] if names else '?'} "
                f"true={true_top3[0]} top1={top1_match} top3={top3_hit} "
                f"invented={invented} steps={stats['steps']} errors={stats['tool_errors']} "
                f"wall={wall}s"
            )

    n = len(results)
    top1 = sum(1 for r in results if r["top1_match"])
    top3 = sum(1 for r in results if r["top3_hit"])
    answered = sum(1 for r in results if r["answered"])
    invented_total = sum(r["invented_values"] for r in results)
    err_total = sum(r["tool_errors"] for r in results)
    wall_total = round(sum(r["wall_secs"] for r in results), 1)
    print(
        f"\n[ablation:agent-loop] n={n} answered={answered}/{n} top1={top1}/{n} "
        f"top3={top3}/{n} invented_values={invented_total} tool_errors={err_total} "
        f"total_wall={wall_total}s"
    )
    out = (
        _SCRIPT_DIR
        / "outputs"
        / "l7"
        / (f"ablation_agent_loop_{building_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(results)
    print(f"[ablation:agent-loop] -> {out}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args.runs)))
