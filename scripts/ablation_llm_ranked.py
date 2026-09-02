# -*- coding: utf-8 -*-
"""
ablation_llm_ranked.py — ablation (b): the LLM ranks from raw rows (V4-T29).

The headline comparison behind ARBITER's design: give the SAME sensor data to
the LLM as raw context and ask IT to pick the quietest/lowest/... rooms — no
deterministic scorer, no dossier, no guard. Graded by the same independent
GroundTruth as the system: top-1/top-3 agreement, plus a fabrication check
(does every value the LLM quotes actually match its room's data within
tolerance? invented values are exactly what the deterministic path makes
impossible).

RUN (inside the orchestrator container — needs llm_manager + DB + graph):
  docker exec ontosage-orchestrator python /app/scripts/ablation_llm_ranked.py --runs 3
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))

from orchestrator.services.deliberation.coverage_audit import (  # noqa: E402
    CoverageAuditor,
    load_modalities,
)
from orchestrator.services.deliberation.live import (  # noqa: E402
    active_identity,
    sparql_exec,
)

# the same single-cue tasks the grader can score exactly
_TASKS: List[Tuple[str, str, str, Optional[str]]] = [
    ("noise", "min", "Which 3 rooms are the quietest right now?", None),
    ("co2", "min", "Which 3 rooms have the lowest CO2 right now?", None),
    ("temperature", "max", "Which 3 rooms are the warmest right now?", None),
    ("occupancy", "min", "Which 3 rooms have the fewest people right now?", None),
    ("illuminance", "max", "Which 3 rooms are the brightest right now?", None),
]
_VALUE_TOLERANCE = 0.20  # generous: the LLM sees the same rows it quotes from


def _load_truth():
    """Reuse the grader's independent GroundTruth (own uuids + own SQL)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("l7_grader", _SCRIPT_DIR / "l7_grader.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def _run(runs: int) -> int:
    from orchestrator.llm_manager import llm_manager

    grader = _load_truth()
    identity = active_identity()
    building_id, namespace = identity["BUILDING_ID"], identity["BUILDING_NAMESPACE"]
    auditor = CoverageAuditor(sparql_exec, load_modalities(building_id))
    spaces = await auditor.discover_spaces(namespace)
    truth = grader.GroundTruth(building_id, spaces)
    rooms = dict(truth._rooms)

    results = []
    for modality, direction, question, floor in _TASKS:
        series = truth._series(modality, rooms, 24.0)
        actual = {room: truth._aggregate(s, forecast=False) for room, s in series.items() if s}
        true_rank = truth.true_ranking_multi([(modality, direction)], floor)
        true_top3 = [r for r, _ in true_rank[:3]]

        # raw rows into the prompt: newest 6 readings per room (the LLM gets
        # MORE than the scorer's aggregate — the fairest possible framing)
        lines = []
        for room, s in sorted(series.items()):
            if s:
                lines.append(f"{room}: " + ", ".join(f"{v:g}" for v in s[-6:]))
        prompt = (
            f"Sensor readings ({modality}, newest last, per room):\n"
            + "\n".join(lines)
            + f"\n\n{question} Reply with exactly three lines, each 'room_name: value'."
        )

        for run in range(runs):
            reply = await llm_manager.generate(prompt, temperature=0.0)
            picked = re.findall(r"(RM[\w.]+)\s*[:\-]?\s*(-?\d+(?:\.\d+)?)?", reply or "")
            names = [p[0] for p in picked][:3]
            top1_match = bool(names) and names[0] == true_top3[0]
            top3_hit = bool(names) and names[0] in true_top3
            invented = 0
            for name, value in picked[:3]:
                if not value:
                    continue
                real = actual.get(name)
                if real is None or abs(float(value) - real) > max(
                    abs(real) * _VALUE_TOLERANCE, 1.0
                ):
                    invented += 1
            results.append(
                {
                    "modality": modality,
                    "run": run + 1,
                    "llm_top1": names[0] if names else "",
                    "true_top1": true_top3[0],
                    "top1_match": top1_match,
                    "top3_hit": top3_hit,
                    "invented_values": invented,
                }
            )
            print(
                f"[{modality} run{run + 1}] llm_top1={names[0] if names else '?'} "
                f"true={true_top3[0]} top1={top1_match} top3={top3_hit} invented={invented}"
            )

    n = len(results)
    top1 = sum(1 for r in results if r["top1_match"])
    top3 = sum(1 for r in results if r["top3_hit"])
    invented_total = sum(r["invented_values"] for r in results)
    variance = len({(r["modality"], r["llm_top1"]) for r in results}) - len(_TASKS)
    print(
        f"\n[ablation:llm-ranked] n={n} top1={top1}/{n} top3={top3}/{n} "
        f"invented_values={invented_total} run_variance(extra distinct picks)={max(0, variance)}"
    )
    out = (
        _SCRIPT_DIR
        / "outputs"
        / "l7"
        / (f"ablation_llm_ranked_{building_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    import csv

    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(results)
    print(f"[ablation:llm-ranked] -> {out}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args.runs)))
