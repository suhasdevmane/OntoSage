# -*- coding: utf-8 -*-
"""2D-09 -- replay the narration validators over every stored answer, offline.

Reads every answer file under ``docs/phase0/`` (each paired with its hand-read labels), runs
``orchestrator/services/narration_validators.py`` over each answer with the question and lane the
run recorded, and writes what each validator would change:

    docs/phase0/narration_validators_replay.md      the table a reader checks
    docs/phase0/narration_validators_replay.jsonl   one row per answer that changes

The module is loaded by file path, so nothing is imported that could reach a network, a model or
the settings loader. ``tail_C*`` is the held-out set and is never opened.

    python scripts/replay_narration_validators.py
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import types
from collections import Counter
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
PHASE0 = REPO / "docs" / "phase0"
MODULE = REPO / "orchestrator" / "services" / "narration_validators.py"

#: answer file -> its hand-read label file. ``run3`` and ``run3b`` are the two halves of
#: ``run3_combined`` and are not replayed twice.
PAIRS: Tuple[Tuple[str, str], ...] = (
    ("phase0_baseline.md", "phase0_read"),
    ("phase0_rerun.md", "phase0_rerun_read"),
    ("phase0_run3.md", "phase0_run3_read"),
    ("phase0_run4.md", "phase0_run4_read"),
    ("phase0_run5.md", "phase0_run5_read"),
    ("phase0_run6.md", "phase0_run6_read"),
    ("fresh_tail_run1", "fresh_tail_run1_read"),
    ("fresh_tail_B_run1", "fresh_tail_B_run1_read"),
    ("fresh_tail_B_run2", "fresh_tail_B_run2_read"),
    ("guardrail_run1", "guardrail_run1_read"),
    ("demo_rehearsal_2026-09-18_run1", "demo_rehearsal_2026-09-18_run1_read"),
    ("demo_rehearsal_2026-09-18_run2", "demo_rehearsal_2026-09-18_run2_read"),
    ("demo_rehearsal_2026-09-18_run3_combined", "demo_rehearsal_2026-09-18_run3_read"),
    # Wave 1: the build these validators first ran on, and the development tail beside it. The
    # SEALED held-out set (tail_C_2026-09-19) is a different file and is never opened here.
    ("demo_wave1", "demo_wave1_read"),
    ("wave1_verification", "wave1_verification_read"),
    ("dev_tail_C_baseline", "dev_tail_C_baseline_read"),
    ("dev_tail_C_wave1", "dev_tail_C_wave1_read"),
)


def _load_by_path(dotted: str, path: Path):
    """Import one module from its file, under its real dotted name, running no package __init__."""
    spec = importlib.util.spec_from_file_location(dotted, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = mod
    spec.loader.exec_module(mod)
    return mod


def load_validators():
    """The validator modules, loaded by path so the settings loader is never touched.

    ``orchestrator/__init__.py`` imports the agents, which import the settings loader, which
    refuses to build without real secrets — so this measurement script must never trigger it.
    The two modules import each other by their real dotted names, so stub parent packages are
    registered (carrying only ``__path__``) and the real ``__init__`` files never run.
    """
    for name, directory in (
        ("orchestrator", REPO / "orchestrator"),
        ("orchestrator.services", REPO / "orchestrator" / "services"),
    ):
        if name not in sys.modules:
            pkg = types.ModuleType(name)
            pkg.__path__ = [str(directory)]  # type: ignore[attr-defined]
            sys.modules[name] = pkg
    _load_by_path("orchestrator.services.narration_validators", MODULE)
    _load_by_path("orchestrator.services.narration_totals", MODULE.with_name("narration_totals.py"))
    return sys.modules["orchestrator.services.narration_validators"]


def _read(path: Path) -> List[Dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def iter_answers() -> Iterator[Dict]:
    """Every stored answer with its hand label (the label file is paired by row index)."""
    for answers, labels in PAIRS:
        a_path, l_path = PHASE0 / f"{answers}.jsonl", PHASE0 / f"{labels}.jsonl"
        if not a_path.exists():
            continue
        rows = _read(a_path)
        marks = _read(l_path) if l_path.exists() else []
        for i, r in enumerate(rows):
            lab = marks[i] if i < len(marks) else {}
            yield {
                "file": answers,
                "row": i,
                "id": lab.get("id"),
                "question": r.get("q") or "",
                "answer": r.get("answer") or "",
                "lane": r.get("lane"),
                "verdict": lab.get("verdict"),
                "evidence": lab.get("evidence") or "",
            }


def _numbers(text: str) -> List[str]:
    return re.findall(r"(?<![A-Za-z\d.,])\d[\d,]*(?:\.\d+)?", text)


def orphaned_numbers(removed: str, kept_text: str) -> List[str]:
    """Numbers in the removed text that appear nowhere in what was kept."""
    kept = set(_numbers(kept_text))
    return sorted({n for n in _numbers(removed) if n not in kept})


def replay() -> List[Dict]:
    """One row per answer whose text changes."""
    nv = load_validators()
    out: List[Dict] = []
    for a in iter_answers():
        res = nv.validate_narration(a["question"], a["answer"], a["lane"])
        if res.text == a["answer"]:
            continue
        removed = " ".join(c.removed for c in res.changes)
        out.append(
            {
                **{
                    k: a[k]
                    for k in ("file", "row", "id", "question", "lane", "verdict", "evidence")
                },
                "changes": [
                    {
                        "validator": c.validator,
                        "action": c.action,
                        "removed": c.removed,
                        "replacement": c.replacement,
                    }
                    for c in res.changes
                ],
                "orphaned_numbers": orphaned_numbers(removed, res.text),
                "chars_before": len(a["answer"]),
                "chars_after": len(res.text),
            }
        )
    return out


def _cell(text: str, limit: int = 230) -> str:
    text = re.sub(r"\s+", " ", text).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def write_report(changed: List[Dict], total: int) -> None:
    per_validator: Counter = Counter()
    per_verdict: Counter = Counter()
    for r in changed:
        per_verdict[r["verdict"] or "NOLABEL"] += 1
        for v in {c["validator"] for c in r["changes"]}:
            per_validator[v] += 1
    # Counted from PAIRS, never written by hand: this file said "13 answer files" for one wave
    # after it stopped being 13, which is how a measurement artifact stops being trusted.
    present = sum(1 for answers, _ in PAIRS if (PHASE0 / f"{answers}.jsonl").exists())
    lines: List[str] = [
        "# Narration validators, replayed over the stored answers (2D-09)",
        "",
        f"Replayed **{total}** stored answers ({present} answer files under `docs/phase0/`, each",
        f"paired with its hand-read labels). **{len(changed)}** change; the rest are byte-identical.",
        "The SEALED held-out set (`tail_C_2026-09-19`) is not among them and is never read here;",
        "`dev_tail_C_*` is the development copy the lead released for this measurement.",
        "Regenerate with `python scripts/replay_narration_validators.py`.",
        "",
        "| validator | answers changed |",
        "|---|---|",
    ]
    for name, n in sorted(per_validator.items()):
        lines.append(f"| {name} | {n} |")
    lines += ["", "| hand label | answers changed |", "|---|---|"]
    for name, n in sorted(per_verdict.items()):
        lines.append(f"| {name} | {n} |")
    lines += [
        "",
        "`orphans` = numbers that were in a removed sentence and appear nowhere else in the answer.",
        "",
        "| file#row | label | validator | action | removed (or replaced) | orphans |",
        "|---|---|---|---|---|---|",
    ]
    for r in changed:
        for c in r["changes"]:
            shown = c["removed"] + (f"  =>  {c['replacement']}" if c["replacement"] else "")
            lines.append(
                f"| {r['file']}#{r['row']} | {r['verdict'] or '-'} | {c['validator']} | "
                f"{c['action']} | {_cell(shown)} | {' '.join(r['orphaned_numbers'][:6])} |"
            )
    (PHASE0 / "narration_validators_replay.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    with (PHASE0 / "narration_validators_replay.jsonl").open("w", encoding="utf-8") as fh:
        for r in changed:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    total = sum(1 for _ in iter_answers())
    changed = replay()
    write_report(changed, total)
    print(
        f"replayed {total} answers; {len(changed)} change; wrote {PHASE0.name}/narration_validators_replay.md"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
