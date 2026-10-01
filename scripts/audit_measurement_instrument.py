"""Measure the measurement instrument over EVERY stored answer we have, not one run of 147.

Why this exists, and why it is not another grader
-------------------------------------------------
Ten P1 rows (CAVEAT-733/784/788/790/791/986/991/993, BUG-785/787) say one thing between
them: this project cannot currently produce a quality number it trusts. Every one of those
rows computes its figure through a *decline classifier* or through
``grade_answers_rubric``'s three buckets, and both were calibrated on 294 answers from a
single 147-question bank.

This module does not tune anything. It measures, over the whole stored corpus:

1. **Four decline classifiers, one corpus.** ``publication_gate.is_decline`` (product),
   ``grade_answers_rubric.is_decline`` (grader), ``regression_answerability.classify``
   (gate) and the inline ``decline_phrases`` list in ``ttl_gap_audit`` are run over every
   stored answer. The report gives pairwise agreement, Cohen's kappa, and — the part a
   count cannot show — whether two classifiers that agree on the TOTAL agree ROW FOR ROW.
   CAVEAT-991 was opened on three different totals; a matching total is not a reconciliation.

2. **Per-bucket precision against every hand label we hold.** 27 recorded runs carry a
   paired ``*_read.jsonl`` hand read: 1,997 labels, against the 882 (six runs of one bank)
   the existing calibration audit uses. Precision is reported per bucket, with a Wilson
   interval, split by era so staleness is visible rather than averaged away.

3. **What may be claimed.** ``--section claims`` prints, for each bucket, one sentence a
   reader may quote and one they may not, derived from the numbers in this run.

Nothing here calls the live system or a model. Every figure is recomputed from files on
disk each time it is printed, because a hand-maintained number in a docstring goes stale
(the whole point of CAVEAT-993).

Usage
-----
    python scripts/audit_measurement_instrument.py                    # all sections
    python scripts/audit_measurement_instrument.py --section classifiers
    python scripts/audit_measurement_instrument.py --section buckets --out report.md
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PHASE0 = REPO / "docs" / "phase0"
PACK = REPO / "Datasets" / "System evaluation" / "Evidence pack - 73 probes"

#: Answer files whose hand read lives under a name the suffix rule cannot derive.
_EXPLICIT_READ: Dict[str, str] = {
    "phase0_baseline.md.jsonl": "phase0_read.jsonl",
    "phase0_rerun.md.jsonl": "phase0_rerun_read.jsonl",
    "phase0_run3.md.jsonl": "phase0_run3_read.jsonl",
    "phase0_run4.md.jsonl": "phase0_run4_read.jsonl",
    "phase0_run5.md.jsonl": "phase0_run5_read.jsonl",
    "phase0_run6.md.jsonl": "phase0_run6_read.jsonl",
    # run3 was captured in two halves; the hand read covers the combined file.
    "demo_rehearsal_2026-09-18_run3_combined.jsonl": "demo_rehearsal_2026-09-18_run3_read.jsonl",
}

#: Answer files that duplicate rows already counted through another file. Counting a
#: half-run and its combined form both would double-weight 22 answers.
_SUPERSEDED = {
    "demo_rehearsal_2026-09-18_run3.jsonl",
    "demo_rehearsal_2026-09-18_run3b.jsonl",
}

#: TWO FILES CARRY A ``verdict`` FIELD AND ARE NOT HAND READS. Recorded here because the
#: alternative is a future reader concluding that 372 labels were overlooked:
#:
#: * ``answer_judge_experiment.jsonl`` (372 rows) — its ``verdict`` is the DETERMINISTIC
#:   GRADER's own output (``GOOD_DECLINE`` at confidence ``low`` is that judge's signature)
#:   and its ``judge`` field holds an LLM judge's label. Counting either as ground truth
#:   would score the grader against itself.
#: * ``narration_validators_replay.jsonl`` (52 rows) — a replay record of validator changes
#:   (``chars_before``/``chars_after``), not a read of answers.
#:
#: Both are loaded as answers (they are stored answers) and contribute no labels, which is
#: what the loader already does by looking only for a paired ``*_read.jsonl``.

#: Which recorded runs belong to which era. An era is a period over which the SYSTEM's
#: answer wording was broadly stable; a shape-scoring grader's precision is only
#: comparable within one (CAVEAT-784/986).
_ERAS: Sequence[Tuple[str, str]] = (
    ("phase0 bank, runs 1-6 (2026-09-17/18)", r"^phase0_"),
    ("demo path + guardrails (2026-09-18/19)", r"^(demo_|guardrail_|fresh_tail_|wave1_)"),
    ("held-out dev tails C-L (2026-09-19/20)", r"^dev_tail_"),
)


# ─────────────────────────────────────────────────────────────────────────────────────────
# Corpus
# ─────────────────────────────────────────────────────────────────────────────────────────


def read_jsonl(path: Path) -> List[dict]:
    rows: List[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _norm_q(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


@dataclass
class Answer:
    """One stored answer, with its hand verdict when a paired read file holds one."""

    source: str
    row: int
    question: str
    answer: str
    verdict: Optional[str] = None
    confidence: Optional[str] = None

    @property
    def era(self) -> str:
        for name, pattern in _ERAS:
            if re.match(pattern, self.source):
                return name
        return "other"


@dataclass
class Corpus:
    answers: List[Answer] = field(default_factory=list)
    alignment_failures: List[str] = field(default_factory=list)

    @property
    def labelled(self) -> List[Answer]:
        return [a for a in self.answers if a.verdict]


def load_corpus(phase0: Path = PHASE0, pack: Path = PACK) -> Corpus:
    """Every stored answer on disk, each carrying its hand verdict when one exists.

    Alignment between an answer file and its hand read is VERIFIED by comparing the
    question text row by row, not assumed from the row index. A file whose questions do
    not line up is recorded in ``alignment_failures`` and its labels are dropped rather
    than silently mis-attached — that mistake would move every number below.
    """
    corpus = Corpus()
    for path in sorted(phase0.glob("*.jsonl")):
        if path.name.endswith("_read.jsonl") or path.name in _SUPERSEDED:
            continue
        rows = read_jsonl(path)
        if not rows or "answer" not in rows[0]:
            continue  # a bank, a grading output or an evidence dump, not a recorded run

        read_name = _EXPLICIT_READ.get(path.name, path.name[: -len(".jsonl")] + "_read.jsonl")
        labels: Dict[int, dict] = {}
        read_path = phase0 / read_name
        if read_path.is_file():
            read_rows = read_jsonl(read_path)
            mismatched = 0
            for i, rec in enumerate(read_rows):
                if i >= len(rows):
                    break
                stored = _norm_q(rows[i].get("q") or rows[i].get("question") or "")
                hand = _norm_q(rec.get("question") or "")
                if stored and hand and stored[:80] != hand[:80]:
                    mismatched += 1
                    continue
                labels[i] = rec
            if mismatched:
                corpus.alignment_failures.append(
                    f"{path.name} vs {read_name}: {mismatched} rows whose questions differ"
                )

        for i, rec in enumerate(rows):
            lab = labels.get(i) or {}
            corpus.answers.append(
                Answer(
                    source=path.name,
                    row=i,
                    question=rec.get("q") or rec.get("question") or "",
                    answer=rec.get("answer") or "",
                    verdict=lab.get("verdict"),
                    confidence=lab.get("confidence"),
                )
            )

    answers_file = pack / "answers.jsonl"
    if answers_file.is_file():
        for rec in read_jsonl(answers_file):
            corpus.answers.append(
                Answer(
                    source="evidence_pack_73",
                    row=int(rec.get("n", 0)),
                    question=rec.get("question") or "",
                    answer=rec.get("answer") or "",
                )
            )
    return corpus


# ─────────────────────────────────────────────────────────────────────────────────────────
# The four classifiers, called through their REAL entry points
# ─────────────────────────────────────────────────────────────────────────────────────────


def _ttl_gap_decline(text: str) -> bool:
    """The fourth classifier: an inline list inside ``ttl_gap_audit.assess_answer``.

    It is not importable as a function, so the list is read OUT of the source at call time
    rather than restated here. A copy in this file would go stale the moment that list is
    edited, which is the defect this whole module is about (lessons #20-22).
    """
    return any(p in (text or "").lower() for p in _ttl_gap_phrases())


_TTL_GAP_CACHE: List[str] = []


def _ttl_gap_phrases() -> List[str]:
    if _TTL_GAP_CACHE:
        return _TTL_GAP_CACHE
    src = (REPO / "scripts" / "ttl_gap_audit.py").read_text(encoding="utf-8")
    block = re.search(r"decline_phrases\s*=\s*\[(.*?)\]", src, re.S)
    if not block:
        raise RuntimeError("ttl_gap_audit.decline_phrases not found — the audit cannot be trusted")
    _TTL_GAP_CACHE.extend(re.findall(r'"([^"]+)"', block.group(1)))
    return _TTL_GAP_CACHE


def classifiers() -> Dict[str, Callable[[str], bool]]:
    """The four live definitions of 'this answer declines', each called as it really is."""
    from orchestrator.services import publication_gate
    from scripts import grade_answers_rubric, regression_answerability

    return {
        "publication_gate.is_decline": publication_gate.is_decline,
        "grade_answers_rubric.is_decline": grade_answers_rubric.is_decline,
        "regression_answerability.classify": (
            lambda t: regression_answerability.classify(t) in ("declined", "refused")
        ),
        "ttl_gap_audit.decline_phrases": _ttl_gap_decline,
    }


# ─────────────────────────────────────────────────────────────────────────────────────────
# Statistics
# ─────────────────────────────────────────────────────────────────────────────────────────


def wilson(successes: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score interval. A normal-approximation interval is wrong near 0 and 1."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (centre - spread) / d), min(1.0, (centre + spread) / d))


def cohen_kappa(a: Sequence[bool], b: Sequence[bool]) -> float:
    """Chance-corrected agreement between two binary raters over the same items."""
    n = len(a)
    if n == 0:
        return 0.0
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    pa, pb = sum(a) / n, sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    if expected >= 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)


# ─────────────────────────────────────────────────────────────────────────────────────────
# Section 1 — the four classifiers
# ─────────────────────────────────────────────────────────────────────────────────────────


def section_classifiers(corpus: Corpus, out: List[str]) -> Dict[str, object]:
    w = out.append
    funcs = classifiers()
    names = list(funcs)
    texts = [a.answer for a in corpus.answers]
    verdicts = {name: [bool(fn(t)) for t in texts] for name, fn in funcs.items()}

    w("## 1. Four decline classifiers, one corpus")
    w("")
    w(
        f"Corpus: **{len(texts)} stored answers** over "
        f"{len({a.source for a in corpus.answers})} recorded runs. Every classifier is "
        "called through its real entry point."
    )
    w("")
    w("| classifier | declines | share |")
    w("|---|---:|---:|")
    for name in names:
        d = sum(verdicts[name])
        w(f"| `{name}` | {d} | {d / len(texts):.1%} |")
    w("")

    w("### Pairwise agreement over the whole corpus")
    w("")
    w("| A | B | agree | A-only | B-only | kappa |")
    w("|---|---|---:|---:|---:|---:|")
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            va, vb = verdicts[a], verdicts[b]
            agree = sum(1 for x, y in zip(va, vb) if x == y)
            a_only = sum(1 for x, y in zip(va, vb) if x and not y)
            b_only = sum(1 for x, y in zip(va, vb) if y and not x)
            k = cohen_kappa(va, vb)
            w(
                f"| `{a.split('.')[0]}` | `{b.split('.')[0]}` | {agree}/{len(texts)} "
                f"({agree / len(texts):.1%}) | {a_only} | {b_only} | {k:.3f} |"
            )
    w("")

    unanimous_decline = sum(1 for i in range(len(texts)) if all(verdicts[n][i] for n in names))
    unanimous_answer = sum(1 for i in range(len(texts)) if not any(verdicts[n][i] for n in names))
    contested = len(texts) - unanimous_decline - unanimous_answer
    w(
        f"**Unanimous decline {unanimous_decline} · unanimous answer {unanimous_answer} · "
        f"CONTESTED {contested} ({contested / len(texts):.1%}).** An answer in the contested "
        "band is a decline or not depending only on which script you ran."
    )
    w("")

    w("### How many classifiers call each answer a decline")
    w("")
    votes = Counter(sum(1 for nm in names if verdicts[nm][i]) for i in range(len(texts)))
    w("| classifiers voting 'decline' | answers |")
    w("|---:|---:|")
    for k in range(len(names) + 1):
        w(f"| {k} of {len(names)} | {votes.get(k, 0)} |")
    w("")
    if votes.get(len(names), 0) == 0:
        w(
            f"**No answer in {len(texts)} is called a decline by all four.** The four are not "
            "four readings of one concept with noise around it; they do not share a core."
        )
        w("")

    # The 73-answer pack, which is where CAVEAT-991 was written.
    pack_idx = [i for i, a in enumerate(corpus.answers) if a.source == "evidence_pack_73"]
    if pack_idx:
        w("### The 73-answer pack — CAVEAT-991's own set, re-measured")
        w("")
        w("| classifier | declines (CAVEAT-991 recorded) |")
        w("|---|---|")
        recorded = {
            "publication_gate.is_decline": "6",
            "grade_answers_rubric.is_decline": "11",
            "regression_answerability.classify": "16",
            "ttl_gap_audit.decline_phrases": "not counted",
        }
        counts = {}
        for name in names:
            c = sum(1 for i in pack_idx if verdicts[name][i])
            counts[name] = c
            w(f"| `{name}` | **{c}** (was {recorded[name]}) |")
        w("")
        pg = [verdicts["publication_gate.is_decline"][i] for i in pack_idx]
        gr = [verdicts["grade_answers_rubric.is_decline"][i] for i in pack_idx]
        same_total = (
            counts["publication_gate.is_decline"] == counts["grade_answers_rubric.is_decline"]
        )
        row_agree = sum(1 for x, y in zip(pg, gr) if x == y)
        disagree_rows = [
            corpus.answers[i].row for i, (x, y) in zip(pack_idx, zip(pg, gr)) if x != y
        ]
        w(
            f"**A matching total is not a reconciliation.** publication_gate and the grader "
            f"{'now report the SAME total' if same_total else 'report different totals'} on this "
            f"pack, and agree on {row_agree}/{len(pack_idx)} rows"
            + (f"; they disagree on pack #{disagree_rows}." if disagree_rows else " — row for row.")
        )
        w("")

    _classifiers_against_hand(corpus, verdicts, names, w)

    return {
        "n": len(texts),
        "counts": {n: sum(verdicts[n]) for n in names},
        "contested": contested,
        "verdicts": verdicts,
    }


def _classifiers_against_hand(
    corpus: Corpus,
    verdicts: Dict[str, List[bool]],
    names: Sequence[str],
    w: Callable[[str], None],
) -> None:
    """Anchor the four to the hand labels WITHOUT inventing decline ground truth.

    The hand read labels QUALITY (GOOD_ANSWER / GOOD_DECLINE / WEIRD), not KIND, so it
    cannot say of every row whether the system declined. Two subsets are unambiguous and
    they are the only ones used here:

    * a row the reader labelled **GOOD_DECLINE** is a decline, so the share of those a
      classifier catches is a **floor on its recall**;
    * a row the reader labelled **GOOD_ANSWER** answered the question, so calling it a
      decline is **unambiguously wrong**.

    WEIRD rows are excluded on purpose: a false decline is WEIRD and so is a fabricated
    answer, and the label does not distinguish them. Reading a rate off that bucket would
    be exactly the over-claim these ten rows are about.
    """
    idx = [i for i, a in enumerate(corpus.answers) if a.verdict in ("GOOD_ANSWER", "GOOD_DECLINE")]
    if not idx:
        return
    n_dec = sum(1 for i in idx if corpus.answers[i].verdict == "GOOD_DECLINE")
    n_ans = len(idx) - n_dec

    w("### Anchored to the hand labels, on the two subsets where the label is unambiguous")
    w("")
    w(
        f"{n_dec} rows a reader confirmed as an honest decline, and {n_ans} a reader "
        "confirmed as answering the question. WEIRD rows are excluded because a false "
        "decline and a fabricated answer carry the same label."
    )
    w("")
    w("| classifier | recall floor (of GOOD_DECLINE) | wrong on GOOD_ANSWER |")
    w("|---|---:|---:|")
    scores: Dict[str, Tuple[int, int]] = {}
    for name in names:
        hit = sum(
            1 for i in idx if corpus.answers[i].verdict == "GOOD_DECLINE" and verdicts[name][i]
        )
        bad = sum(
            1 for i in idx if corpus.answers[i].verdict == "GOOD_ANSWER" and verdicts[name][i]
        )
        scores[name] = (hit, bad)
        w(
            f"| `{name}` | {hit}/{n_dec} ({hit / n_dec:.1%}) | "
            f"{bad}/{n_ans} ({bad / n_ans:.1%}) |"
        )
    w("")

    w("### The reconciliation")
    w("")
    w(
        "CAVEAT-991 reads these four as one concept implemented four times. Anchored to the "
        "hand labels they are not: they sit at four separate points on a recall / "
        "false-decline trade-off, and for three of them the point they occupy is the right "
        "one for what they are FOR. Unifying them would move at least two off it."
    )
    w("")
    w("| classifier | what it decides | which error costs more | verdict |")
    w("|---|---|---|---|")
    w(
        "| `regression_answerability.classify` | whether a re-asked question changed KIND, "
        "in a gate | a false decline MANUFACTURES a regression, and a gate that cries wolf "
        "gets switched off (lessons #141) | **keep separate — correctly conservative**: "
        f"{scores['regression_answerability.classify'][1]}/{n_ans} wrong on hand-confirmed "
        "answers |"
    )
    w(
        "| `publication_gate.is_decline` | whether an answer already declines, so there is "
        "no figure to withhold | a false decline would mark an answered turn as declined in "
        "the session summary the classifier prompt reads | **keep separate — correctly "
        f"conservative**: {scores['publication_gate.is_decline'][1]}/{n_ans} wrong |"
    )
    w(
        "| `grade_answers_rubric.is_decline` | whether a graded row is GOOD_DECLINE rather "
        "than GOOD_ANSWER | a false decline inflates the bucket CAVEAT-784/788 were opened "
        f"about | **the outlier**: {scores['grade_answers_rubric.is_decline'][1]}/{n_ans} = "
        f"{scores['grade_answers_rubric.is_decline'][1] / n_ans:.0%} of hand-confirmed "
        "answers are called declines |"
    )
    w(
        "| `ttl_gap_audit.decline_phrases` | whether a probe answer counted as a gap | "
        "either | **no defensible position**: strictly worse recall than "
        "`publication_gate` for near-identical error |"
    )
    w("")
    w(
        "**So: three must differ and now have a measured justification; one has none.** "
        "The durable fix named in CAVEAT-991 and CAVEAT-887 — record the lane's own outcome "
        "on the bus and compare a FACT — is the only thing that removes the trade-off, and "
        "it is a product change: nothing the server returns today says whether a turn "
        "declined (`ontosage_route` says which lane, `turn_outcome` says whether the "
        "machinery ran)."
    )
    w("")


# ─────────────────────────────────────────────────────────────────────────────────────────
# Section 2 — bucket precision against every hand label
# ─────────────────────────────────────────────────────────────────────────────────────────


def _prove_grader_call_is_the_real_one(corpus: Corpus) -> str:
    """Prove this module's grading call is identical to ``grade_run``'s, before any figure.

    lessons #145: a hand-run query that differs from the one the code sends verifies the
    intent, not the code. The same trap applies to a grader re-implemented in an audit. One
    recorded run is graded BOTH ways and the verdicts compared row for row.
    """
    from scripts.grade_answers_rubric import DeterministicJudge, grade_run

    probe = PHASE0 / "phase0_run6.md.jsonl"
    if not probe.is_file():
        return "SKIPPED — probe file absent"
    judge = DeterministicJudge()
    via_grade_run = [g["verdict"] for g in grade_run(probe, judge)]
    rows = read_jsonl(probe)
    mine = [
        judge.grade(r.get("q") or r.get("question") or "", r.get("answer") or "").verdict
        for r in rows
    ]
    same = sum(1 for a, b in zip(via_grade_run, mine) if a == b)
    return f"{same}/{len(mine)} identical to `grade_run` on {probe.name}"


def _grade_all(corpus: Corpus) -> Dict[int, str]:
    """The grader's verdict for every labelled answer, via the SAME call ``grade_run`` makes."""
    from scripts.grade_answers_rubric import DeterministicJudge

    judge = DeterministicJudge()
    out: Dict[int, str] = {}
    for i, a in enumerate(corpus.answers):
        if not a.verdict:
            continue
        out[i] = judge.grade(a.question, a.answer).verdict
    return out


def section_buckets(corpus: Corpus, out: List[str]) -> Dict[str, object]:
    w = out.append
    labelled = corpus.labelled
    graded = _grade_all(corpus)
    pairs = [(corpus.answers[i].verdict, v, corpus.answers[i]) for i, v in graded.items()]

    w("## 2. What each bucket is worth, against every hand label we hold")
    w("")
    w(f"*Grader-call integrity: {_prove_grader_call_is_the_real_one(corpus)}.*")
    w("")
    w(
        f"**{len(labelled)} hand labels** across {len({a.source for a in labelled})} recorded "
        "runs, each verified row-for-row against its answer file by question text. The "
        "existing calibration audit uses 882 of these (six runs of one 147-question bank); "
        f"the other {len(labelled) - 882} have never been used to calibrate anything."
    )
    w("")
    if corpus.alignment_failures:
        w("**Alignment failures (labels dropped):** " + "; ".join(corpus.alignment_failures))
        w("")

    w("### Confusion: grader bucket (rows) x hand verdict (columns)")
    w("")
    hand_vocab = ["GOOD_ANSWER", "GOOD_DECLINE", "WEIRD"]
    grader_vocab = ["GOOD_ANSWER", "GOOD_DECLINE", "WEIRD"]
    w("| grader \\ hand | " + " | ".join(hand_vocab) + " | total | precision | 95% CI |")
    w("|---|" + "---:|" * (len(hand_vocab) + 3))
    precisions: Dict[str, Tuple[int, int]] = {}
    for gb in grader_vocab:
        row = [sum(1 for h, g, _ in pairs if g == gb and h == hv) for hv in hand_vocab]
        total = sum(row)
        correct = row[hand_vocab.index(gb)]
        precisions[gb] = (correct, total)
        lo, hi = wilson(correct, total)
        p = f"{correct / total:.1%}" if total else "—"
        ci = f"[{lo:.1%}, {hi:.1%}]" if total else "—"
        w(f"| **{gb}** | " + " | ".join(str(x) for x in row) + f" | {total} | {p} | {ci} |")
    w("")

    exact = sum(1 for h, g, _ in pairs if h == g)
    weird_or_not = sum(1 for h, g, _ in pairs if (h == "WEIRD") == (g == "WEIRD"))
    kw = cohen_kappa([h == "WEIRD" for h, _, _ in pairs], [g == "WEIRD" for _, g, _ in pairs])
    w(
        f"Exact 3-way agreement **{exact}/{len(pairs)} ({exact / len(pairs):.1%})**; "
        f"weird-or-not **{weird_or_not / len(pairs):.1%}**, Cohen's kappa **{kw:.3f}**."
    )
    w("")

    w("### Recall — what each hand class gets called")
    w("")
    w("| hand verdict | n | called correctly | recall |")
    w("|---|---:|---:|---:|")
    for hv in hand_vocab:
        n = sum(1 for h, _, _ in pairs if h == hv)
        hit = sum(1 for h, g, _ in pairs if h == hv and g == hv)
        w(f"| {hv} | {n} | {hit} | {hit / n:.1%} |" if n else f"| {hv} | 0 | 0 | — |")
    w("")

    w("### Precision by era, against the base rate it has to beat")
    w("")
    w(
        "A precision figure alone is not comparable across eras: a bucket is easier to hit "
        "where its hand class is common. Each cell below is `correct/total (precision)` and "
        "each era carries the hand BASE RATE of that class, so the column that matters is "
        "LIFT — precision minus base rate. A lift near zero means the bucket carries no "
        "information beyond the prior."
    )
    w("")
    w("| era | n | bucket | precision | hand base rate | lift |")
    w("|---|---:|---|---:|---:|---:|")
    era_rows: Dict[str, Dict[str, Tuple[int, int]]] = {}
    for era_name, _ in list(_ERAS) + [("other", "")]:
        sub = [(h, g) for h, g, a in pairs if a.era == era_name]
        if not sub:
            continue
        era_rows[era_name] = {}
        for gb in grader_vocab:
            tot = sum(1 for _, g in sub if g == gb)
            cor = sum(1 for h, g in sub if g == gb and h == gb)
            era_rows[era_name][gb] = (cor, tot)
            base = sum(1 for h, _ in sub if h == gb) / len(sub)
            if not tot:
                w(f"| {era_name} | {len(sub)} | {gb} | — | {base:.1%} | — |")
                continue
            p = cor / tot
            w(
                f"| {era_name} | {len(sub)} | {gb} | {cor}/{tot} ({p:.1%}) | {base:.1%} | "
                f"{p - base:+.1f} pp |".replace(
                    f"{p - base:+.1f} pp", f"{100 * (p - base):+.1f} pp"
                )
            )
    w("")

    w("### Chance-corrected agreement per era (weird-or-not)")
    w("")
    w("| era | n | hand WEIRD | grader WEIRD | kappa |")
    w("|---|---:|---:|---:|---:|")
    for era_name in era_rows:
        sub = [(h, g) for h, g, a in pairs if a.era == era_name]
        k = cohen_kappa([h == "WEIRD" for h, _ in sub], [g == "WEIRD" for _, g in sub])
        hw = sum(1 for h, _ in sub if h == "WEIRD")
        gw = sum(1 for _, g in sub if g == "WEIRD")
        w(
            f"| {era_name} | {len(sub)} | {hw} ({hw / len(sub):.0%}) | "
            f"{gw} ({gw / len(sub):.0%}) | **{k:.3f}** |"
        )
    w("")

    w("### The same numbers on CONFIDENT hand labels only")
    w("")
    w(
        "CAVEAT-993: the reader's own confidence distribution moved across the six phase0 "
        "runs, so a marginal share computed over all labels is confounded. Restricting to "
        "labels the reader was not unsure about (`high`/`med`) removes that confound at the "
        "cost of sample size."
    )
    w("")
    conf_pairs = [(h, g, a) for h, g, a in pairs if (a.confidence or "").lower() in ("high", "med")]
    w("| grader bucket | n | precision | 95% CI |")
    w("|---|---:|---:|---:|")
    conf_precisions: Dict[str, Tuple[int, int]] = {}
    for gb in grader_vocab:
        tot = sum(1 for _, g, _ in conf_pairs if g == gb)
        cor = sum(1 for h, g, _ in conf_pairs if g == gb and h == gb)
        conf_precisions[gb] = (cor, tot)
        lo, hi = wilson(cor, tot)
        w(
            f"| {gb} | {tot} | {cor / tot:.1%} | [{lo:.1%}, {hi:.1%}] |"
            if tot
            else f"| {gb} | 0 | — | — |"
        )
    w("")

    return {
        "n_labels": len(pairs),
        "precisions": precisions,
        "confident_precisions": conf_precisions,
        "era": era_rows,
        "exact": exact,
        "kappa_weird": kw,
    }


# ─────────────────────────────────────────────────────────────────────────────────────────
# Section 3 — what may be claimed
# ─────────────────────────────────────────────────────────────────────────────────────────


def section_claims(bucket_stats: Dict[str, object], out: List[str]) -> None:
    """State what each bucket supports — OUT OF SAMPLE, because that is where it is used.

    The first version of this section reported one pooled precision per bucket and it
    over-claimed, in exactly the way these ten rows are about: pooling puts 882 labels from
    the grader's own calibration bank beside 744 genuinely held-out ones and reports the
    average. The held-out figure is the one a reader may use, so it leads.
    """
    w = out.append
    prec: Dict[str, Tuple[int, int]] = bucket_stats["precisions"]  # type: ignore[assignment]
    era: Dict[str, Dict[str, Tuple[int, int]]] = bucket_stats["era"]  # type: ignore[assignment]
    n = bucket_stats["n_labels"]
    held_key = next((k for k in era if k.startswith("held-out")), "")
    held = era.get(held_key, {})
    home_key = next((k for k in era if k.startswith("phase0")), "")
    home = era.get(home_key, {})

    w("## 3. What a reader may conclude from each bucket")
    w("")
    w(
        "Generated from the counts above, not restated from a previous run. Each bucket is "
        "reported **in sample** (the phase0 bank, which includes the 294 answers this grader "
        "was calibrated on) and **out of sample** (the held-out dev tails). Only the second "
        "describes what happens when the grader meets an answer it has not been fitted to."
    )
    w("")
    w("| bucket | pooled | in sample (phase0 bank) | OUT OF SAMPLE (held-out tails) |")
    w("|---|---:|---:|---:|")
    for bucket in ("WEIRD", "GOOD_DECLINE", "GOOD_ANSWER"):
        pc, pt = prec.get(bucket, (0, 0))
        hc, ht = home.get(bucket, (0, 0))
        oc, ot = held.get(bucket, (0, 0))
        w(
            f"| **{bucket}** | {pc}/{pt} ({pc / pt:.1%}) "
            f"| {hc}/{ht} ({hc / ht:.1%}) | {oc}/{ot} (**{oc / ot:.1%}**) |"
            if pt and ht and ot
            else f"| **{bucket}** | — | — | — |"
        )
    w("")

    for bucket in ("WEIRD", "GOOD_DECLINE", "GOOD_ANSWER"):
        oc, ot = held.get(bucket, (0, 0))
        if not ot:
            continue
        lo, hi = wilson(oc, ot)
        w(f"### `{bucket}` — out of sample {oc}/{ot} = {oc / ot:.1%}, 95% CI [{lo:.1%}, {hi:.1%}]")
        w("")
        if bucket == "WEIRD":
            hc, ht = home.get(bucket, (0, 0))
            w(
                f"**The claim this project currently permits is an IN-SAMPLE number.** "
                f'CLAUDE.md records "only the WEIRD bucket is trustworthy ({hc / ht:.1%} '
                'precision) and only as a LOWER BOUND". That figure is reproduced exactly '
                f"here — {hc}/{ht} on the phase0 bank — and on the held-out tails the same "
                f"bucket is {oc}/{ot} = {oc / ot:.1%}. **It may be quoted for the phase0 bank "
                "and for nothing else.** Out of sample it carries no lift over the hand base "
                "rate, so a WEIRD count on unseen answers is not even a floor."
            )
        elif bucket == "GOOD_DECLINE":
            w(
                f"**MUST NOT be quoted as evidence of quality, in or out of sample.** "
                f"{oc / ot:.1%} out of sample. CAVEAT-986 located the reason in the source "
                "and it is not a tuning problem: whether a stated absence is TRUE is not "
                "checkable from the answer text, so no re-wording of a shape rule can "
                "separate an honest decline from a false one. That needs the graph."
            )
        else:
            w(
                f'**MUST NOT be quoted.** {oc / ot:.1%} out of sample. Its content is "no '
                'defect was DETECTED", which is a statement about the detector, and it is '
                "the bucket a wording change moves first (CAVEAT-784/788)."
            )
        w("")

    w("### The one sentence")
    w("")
    oc, ot = held.get("WEIRD", (0, 0))
    hc, ht = home.get("WEIRD", (0, 0))
    if ot and ht:
        w(
            f"> Over {n} hand-labelled stored answers, **no bucket of this grader supports a "
            "quality claim about answers it has not been calibrated on.** Its best bucket, "
            f"WEIRD, is {hc}/{ht} = {hc / ht:.1%} precise on the phase0 bank it was fitted to "
            f"and {oc}/{ot} = {oc / ot:.1%} on held-out answers, where its chance-corrected "
            "agreement with a hand reader is at or below zero. The GOOD_ANSWER and "
            "GOOD_DECLINE buckets record that this detector found nothing, which is a "
            "statement about the detector. **Every quality percentage this project can "
            "currently defend comes from a hand read of specific answers, and the only claim "
            "that has survived every correction to those hand reads is the one that never "
            "depended on a classifier: no fabricated figure was confirmed.**"
        )
    w("")


# ─────────────────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────────────────


def build_report(sections: Sequence[str]) -> str:
    corpus = load_corpus()
    out: List[str] = ["# The measurement instrument, measured", ""]
    out.append(
        f"Recomputed from disk. Corpus **{len(corpus.answers)} stored answers**, "
        f"**{len(corpus.labelled)} hand labels**."
    )
    out.append("")
    bucket_stats: Dict[str, object] = {}
    if "classifiers" in sections:
        section_classifiers(corpus, out)
    if "buckets" in sections or "claims" in sections:
        bucket_stats = section_buckets(corpus, out) if "buckets" in sections else {}
        if "claims" in sections:
            if not bucket_stats:
                bucket_stats = section_buckets(corpus, [])
            section_claims(bucket_stats, out)
    return "\n".join(out) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--section",
        action="append",
        choices=["classifiers", "buckets", "claims"],
        help="repeatable; default is all three",
    )
    ap.add_argument("--out", type=Path, help="also write the report here")
    args = ap.parse_args(argv)
    sections = args.section or ["classifiers", "buckets", "claims"]
    report = build_report(sections)
    sys.stdout.write(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
