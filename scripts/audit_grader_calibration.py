# -*- coding: utf-8 -*-
"""Measure the measurement apparatus, before any quality number is published (Wave F).

WHY THIS EXISTS
---------------
This project's hardest-won lesson is that **the measurement apparatus was wrong more often
than the system** (``tasks/lessons.md`` #20-22): four of five P1s in one session were in
graders and harnesses, and the same weak heuristic hid a fabrication one day and
manufactured a perfect score the next. Five of the nine P1s open on 2026-09-30 are about
the grader rather than the system -- CAVEAT-784, CAVEAT-788, CAVEAT-790, CAVEAT-791,
BUG-785/787.

Those rows quote numbers. A row whose number no longer reproduces is a different problem
from one that does, so the first job is to re-derive each number from the artefact that
produced it. That is what this script does, and nothing else: it changes no grader and
fixes no defect. It is read-only over ``docs/phase0``.

WHAT IT MEASURES, AND WHICH ROW EACH SECTION SETTLES
----------------------------------------------------
``series``     the hand-read weird share per run, with a Wilson interval and the reader's
               own confidence bands                                          (CAVEAT-790)
``mcnemar``    paired exact McNemar for every run pair, with the McNemar odds ratio, the
               paired risk difference and its interval, plus a complete-case analysis that
               drops the labels the reader marked low confidence              (CAVEAT-790)
``agreement``  the deterministic grader against the same labels: 3-way agreement, Cohen's
               kappa, and per-bucket precision and recall            (CAVEAT-784, CAVEAT-788)
``direction``  whether the grader agrees with the hand read about the SIGN of each
               consecutive wave delta -- the one use the write-up still claims for it
``patterns``   which decline pattern put each GOOD_DECLINE row in that bucket, and how many
               of each pattern's rows the hand read calls WEIRD                (CAVEAT-784)
``candidates`` candidate redefinitions of ``is_decline``, each scored against all 882 hand
               labels, so a proposed repair is measured before it lands        (CAVEAT-784)
``census``     the register-census leak, counted mechanically over all six runs
                                                                       (BUG-785, BUG-787)
``binding``    the three claim-binding partitions, read from the committed artefact rather
               than from any write-up                                          (CAVEAT-791)

NOT AN ESTIMATE OF CORRECTNESS. The hand labels are treated as ground truth because they
are the only judgement in this project made by reading the answer against the question.
They are not blind: one reader read the same 147 answers six times knowing which run was
which, and the reader's own low-confidence rate falls from 31 of 147 to 5 of 147 across the
series. ``series`` and ``mcnemar`` report that, because a label set that is not stationary
is a confound in every delta computed from it.

OFFLINE. No network, no live system, no model. Building-agnostic: every path is an
argument and no building name appears.

USAGE
    python scripts/audit_grader_calibration.py                    # every section
    python scripts/audit_grader_calibration.py --section mcnemar
    python scripts/audit_grader_calibration.py --out scripts/outputs/wave_f_audit.md
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from datetime import date as dt_date
from itertools import combinations
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

WEIRD = "WEIRD"
GOOD_ANSWER = "GOOD_ANSWER"
GOOD_DECLINE = "GOOD_DECLINE"

#: The six recorded runs of the 147-question bank and the hand read of each. ``answers`` is
#: the recorded run; ``read`` is the label file. Both are relative to --phase0.
RUNS: Tuple[Tuple[str, str, str], ...] = (
    ("run1", "phase0_baseline.md.jsonl", "phase0_read.jsonl"),
    ("run2", "phase0_rerun.md.jsonl", "phase0_rerun_read.jsonl"),
    ("run3", "phase0_run3.md.jsonl", "phase0_run3_read.jsonl"),
    ("run4", "phase0_run4.md.jsonl", "phase0_run4_read.jsonl"),
    ("run5", "phase0_run5.md.jsonl", "phase0_run5_read.jsonl"),
    ("run6", "phase0_run6.md.jsonl", "phase0_run6_read.jsonl"),
)

SECTIONS = (
    "series",
    "mcnemar",
    "agreement",
    "direction",
    "patterns",
    "candidates",
    "census",
    "binding",
)


# ─────────────────────────────────────────────────────────────────────────────────────────
# statistics, with no scipy dependency
# ─────────────────────────────────────────────────────────────────────────────────────────

Z95 = 1.959963984540054


def binom_cdf(k: int, n: int, p: float = 0.5) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return sum(math.comb(n, i) * p**i * (1.0 - p) ** (n - i) for i in range(k + 1))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar: a binomial sign test on the discordant pairs.

    The exact form is used rather than the chi-square because the discordant total is
    small in several of these pairs (4 in run2->run5) and the asymptotic test is not
    valid there. The continuity-corrected chi-square is reported beside it so the two
    can be compared.
    """
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2.0 * binom_cdf(min(b, c), n, 0.5))


def mcnemar_chi2_cc(b: int, c: int) -> Tuple[float, float]:
    """Continuity-corrected McNemar chi-square and its p-value (1 degree of freedom)."""
    n = b + c
    if n == 0:
        return 0.0, 1.0
    stat = (abs(b - c) - 1) ** 2 / n
    return stat, math.erfc(math.sqrt(stat / 2.0))


def paired_risk_diff(b: int, c: int, n: int) -> Tuple[float, float, float]:
    """Paired risk difference (b - c)/n and its 95% interval.

    b = improved (weird in the first run, not in the second), c = regressed. The variance
    is the standard paired-proportions form, which accounts for the concordant pairs
    contributing nothing to the difference.
    """
    diff = (b - c) / n
    var = (b + c - (b - c) ** 2 / n) / (n * n)
    se = math.sqrt(max(var, 0.0))
    return diff, diff - Z95 * se, diff + Z95 * se


def wilson(k: int, n: int) -> Tuple[float, float]:
    """Wilson score interval for a single proportion."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1.0 + Z95 * Z95 / n
    centre = (p + Z95 * Z95 / (2 * n)) / denom
    half = Z95 * math.sqrt(p * (1 - p) / n + Z95 * Z95 / (4 * n * n)) / denom
    return centre - half, centre + half


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    """Cohen's kappa over however many labels the two sequences use between them."""
    n = len(a)
    if n == 0:
        return float("nan")
    labels = sorted(set(a) | set(b))
    obs = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    exp = sum((ca[lab] / n) * (cb[lab] / n) for lab in labels)
    return (obs - exp) / (1 - exp) if exp < 1 else 1.0


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    """Spearman rank correlation, average ranks for ties."""

    def ranks(xs: Sequence[float]) -> List[float]:
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        out = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    ra, rb = ranks(a), ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else float("nan")


# ─────────────────────────────────────────────────────────────────────────────────────────
# loading
# ─────────────────────────────────────────────────────────────────────────────────────────


def load_jsonl(path: Path) -> List[dict]:
    rows: List[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


class Corpus:
    """The six runs, their hand labels, and the grader's verdict for each row."""

    def __init__(
        self, phase0: Path, bank: Optional[Path] = None, asof: Optional[dt_date] = None
    ) -> None:
        self.phase0 = phase0
        self.asof = asof
        self.bank = bank
        self.answers: Dict[str, List[dict]] = {}
        self.hand: Dict[str, List[dict]] = {}
        self.missing: List[str] = []
        self.boundaries: Dict[str, str] = {}
        if bank and bank.is_file():
            self.boundaries = {b["question"]: b.get("boundary", "") for b in load_jsonl(bank)}
        for label, ansf, readf in RUNS:
            ap, rp = phase0 / ansf, phase0 / readf
            if not (ap.is_file() and rp.is_file()):
                self.missing.append(label)
                continue
            self.answers[label] = load_jsonl(ap)
            self.hand[label] = load_jsonl(rp)
        self.labels = [lab for lab, _, _ in RUNS if lab in self.answers]

    def graded(self, label: str, is_decline: Callable[[str], bool]) -> List[str]:
        return grader_verdicts(self.answers[label], is_decline, self.boundaries, self.asof)

    @property
    def aligned(self) -> bool:
        """True when every run holds the same questions in the same order."""
        ids = [[r.get("id") for r in self.hand[lab]] for lab in self.labels]
        return bool(ids) and all(x == ids[0] for x in ids)

    def hand_verdicts(self, label: str) -> List[str]:
        return [r.get("verdict") or "" for r in self.hand[label]]

    def confidences(self, label: str) -> List[str]:
        return [(r.get("confidence") or "").lower() for r in self.hand[label]]

    def check_fidelity(self) -> List[str]:
        """Prove this module's grader call reproduces ``grade_run`` row for row.

        An audit built on a reimplementation of the thing it audits is worth nothing if
        the two diverge. This grades every run through the shipped ``grade_run`` and
        compares verdicts. Measured 2026-09-30: without the bank boundary and the
        recording date the two disagreed on one run-1 row, which is exactly the size of
        divergence nobody would notice.
        """
        from scripts.grade_answers_rubric import DeterministicJudge, grade_run

        problems: List[str] = []
        dec = _shipped_is_decline()
        judge = DeterministicJudge()
        for label, ansf, _ in RUNS:
            if label not in self.answers:
                continue
            shipped = grade_run(
                self.phase0 / ansf,
                judge,
                bank=self.bank if self.bank and self.bank.is_file() else None,
                asof=self.asof,
            )
            mine = self.graded(label, dec)
            diff = [
                i for i, (a, b) in enumerate(zip([g["verdict"] for g in shipped], mine)) if a != b
            ]
            if diff:
                problems.append(
                    f"{label}: {len(diff)} row(s) disagree with grade_run at " f"{diff[:8]}"
                )
        return problems


# ─────────────────────────────────────────────────────────────────────────────────────────
# sections
# ─────────────────────────────────────────────────────────────────────────────────────────


def sec_series(c: Corpus, w: Callable[[str], None]) -> None:
    w("## series -- the hand-read weird share per run (CAVEAT-790)\n")
    w("| run | n | weird | share | 95% CI (Wilson) | high-conf weird | low-conf weird |")
    w("|---|---:|---:|---:|---|---:|---:|")
    for lab in c.labels:
        hv, cf = c.hand_verdicts(lab), c.confidences(lab)
        n = len(hv)
        weird = [i for i, v in enumerate(hv) if v == WEIRD]
        lo, hi = wilson(len(weird), n)
        band = Counter(cf[i] for i in weird)
        w(
            f"| {lab} | {n} | {len(weird)} | {len(weird)/n*100:.1f}% | "
            f"[{lo*100:.1f}%, {hi*100:.1f}%] | {band.get('high', 0)} | {band.get('low', 0)} |"
        )
    w("")
    w("The reader's own confidence distribution over ALL rows, which is what makes the")
    w("label set non-stationary and is therefore a confound in every delta below:\n")
    w("| run | high | med | low |")
    w("|---|---:|---:|---:|")
    for lab in c.labels:
        band = Counter(c.confidences(lab))
        w(
            f"| {lab} | {band.get('high', 0)} | {band.get('med', 0) + band.get('medium', 0)} "
            f"| {band.get('low', 0)} |"
        )
    w("")
    w("Counting only the weird labels the reader was NOT unsure about (dropping low):\n")
    counts = []
    for lab in c.labels:
        hv, cf = c.hand_verdicts(lab), c.confidences(lab)
        counts.append(sum(1 for v, f in zip(hv, cf) if v == WEIRD and f != "low"))
    w("| " + " | ".join(c.labels) + " |")
    w("|" + "---:|" * len(c.labels))
    w("| " + " | ".join(str(x) for x in counts) + " |")
    w("")


def _paired(a: Sequence[bool], b: Sequence[bool]) -> Tuple[int, int, int]:
    improved = sum(1 for x, y in zip(a, b) if x and not y)
    regressed = sum(1 for x, y in zip(a, b) if y and not x)
    return improved, regressed, len(a) - improved - regressed


def sec_mcnemar(c: Corpus, w: Callable[[str], None]) -> None:
    w("## mcnemar -- paired exact McNemar for every run pair (CAVEAT-790)\n")
    w("Same 147 questions, same reader, same method, so the pairing is valid. `improved`")
    w("means WEIRD in the first run and not WEIRD in the second. The exact test is used")
    w("because several pairs have a discordant total below 10.\n")
    w(
        "| pair | improved | regressed | concordant | p exact | chi2 (cc) | p chi2 | "
        "risk diff | 95% CI | McNemar OR |"
    )
    w("|---|---:|---:|---:|---:|---:|---:|---:|---|---:|")
    for i, j in combinations(range(len(c.labels)), 2):
        a, b = c.labels[i], c.labels[j]
        wa = [v == WEIRD for v in c.hand_verdicts(a)]
        wb = [v == WEIRD for v in c.hand_verdicts(b)]
        imp, reg, con = _paired(wa, wb)
        p = mcnemar_exact(imp, reg)
        stat, pchi = mcnemar_chi2_cc(imp, reg)
        diff, lo, hi = paired_risk_diff(imp, reg, len(wa))
        orat = f"{imp/reg:.2f}" if reg else "inf"
        star = " **\\***" if p < 0.05 else ""
        w(
            f"| {a} -> {b}{star} | {imp} | {reg} | {con} | {p:.3f} | {stat:.2f} | {pchi:.3f} "
            f"| {diff*100:+.1f} pp | [{lo*100:+.1f}, {hi*100:+.1f}] pp | {orat} |"
        )
    w("")
    w("### complete-case: the labels the reader marked LOW confidence dropped\n")
    w("A low-confidence label is the reader saying they could not decide. Treating it as a")
    w("verdict and treating it as missing are different analyses, and the second is the one")
    w("CAVEAT-790 asks for. Rows low-confidence in EITHER run of the pair are excluded, so")
    w("`n` differs per pair.\n")
    w("| pair | n | improved | regressed | p exact | risk diff | 95% CI |")
    w("|---|---:|---:|---:|---:|---:|---|")
    for i, j in combinations(range(len(c.labels)), 2):
        a, b = c.labels[i], c.labels[j]
        hva, hvb = c.hand_verdicts(a), c.hand_verdicts(b)
        cfa, cfb = c.confidences(a), c.confidences(b)
        keep = [k for k in range(len(hva)) if cfa[k] != "low" and cfb[k] != "low"]
        wa = [hva[k] == WEIRD for k in keep]
        wb = [hvb[k] == WEIRD for k in keep]
        imp, reg, _ = _paired(wa, wb)
        p = mcnemar_exact(imp, reg)
        diff, lo, hi = paired_risk_diff(imp, reg, max(len(keep), 1))
        star = " **\\***" if p < 0.05 else ""
        w(
            f"| {a} -> {b}{star} | {len(keep)} | {imp} | {reg} | {p:.3f} | "
            f"{diff*100:+.1f} pp | [{lo*100:+.1f}, {hi*100:+.1f}] pp |"
        )
    w("")


def grader_verdicts(
    answers: Sequence[dict],
    is_decline: Callable[[str], bool],
    boundaries: Optional[Dict[str, str]] = None,
    asof: Optional[dt_date] = None,
) -> List[str]:
    """The deterministic grader's verdict per row, with `is_decline` supplied.

    Only ``is_decline`` varies between candidates; the signal detectors are identical, so
    a row with a detected defect is WEIRD under every candidate and what moves is the
    GOOD_DECLINE / GOOD_ANSWER split. That is the bucket CAVEAT-784 and CAVEAT-788 are
    about.

    ``boundaries`` and ``asof`` must be passed exactly as ``grade_run`` passes them, or
    this reimplementation is not the shipped grader. Without the bank boundary and the
    recording date, one run-1 row loses its stale-date signal and the bucket counts differ
    by one -- which is the kind of silent divergence that makes an audit worthless.
    ``check_fidelity`` asserts the agreement.
    """
    from scripts.grade_answers_rubric import body_of, detect_signals

    boundaries = boundaries or {}
    out: List[str] = []
    for row in answers:
        text = row.get("answer") or ""
        question = row.get("q") or row.get("question") or ""
        if detect_signals(question, text, boundary=boundaries.get(question, ""), asof=asof):
            out.append(WEIRD)
        elif is_decline(body_of(text)):
            out.append(GOOD_DECLINE)
        else:
            out.append(GOOD_ANSWER)
    return out


def _shipped_is_decline() -> Callable[[str], bool]:
    from scripts.grade_answers_rubric import _DECLINE_RE

    return lambda body: bool(_DECLINE_RE.search(body))


def sec_agreement(c: Corpus, w: Callable[[str], None]) -> None:
    w(
        "## agreement -- the deterministic grader against the same labels "
        "(CAVEAT-784, CAVEAT-788)\n"
    )
    dec = _shipped_is_decline()
    w(
        "| run | grader weird | hand weird | agree 3-way | kappa | agree weird/not | "
        "kappa weird/not |"
    )
    w("|---|---:|---:|---:|---:|---:|---:|")
    pooled_g: List[str] = []
    pooled_h: List[str] = []
    for lab in c.labels:
        gv = c.graded(lab, dec)
        hv = c.hand_verdicts(lab)
        n = len(gv)
        a3 = sum(1 for x, y in zip(gv, hv) if x == y) / n
        gw = [WEIRD if v == WEIRD else "N" for v in gv]
        hw = [WEIRD if v == WEIRD else "N" for v in hv]
        a2 = sum(1 for x, y in zip(gw, hw) if x == y) / n
        gws = sum(1 for v in gv if v == WEIRD) / n
        hws = sum(1 for v in hv if v == WEIRD) / n
        w(
            f"| {lab} | {gws*100:.1f}% | {hws*100:.1f}% | {a3*100:.1f}% | "
            f"{cohen_kappa(gv, hv):.3f} | {a2*100:.1f}% | {cohen_kappa(gw, hw):.3f} |"
        )
        pooled_g.extend(gv)
        pooled_h.extend(hv)
    n = len(pooled_g)
    a3 = sum(1 for x, y in zip(pooled_g, pooled_h) if x == y) / n
    w(
        f"| **pooled ({n} labels)** | | | {a3*100:.1f}% | "
        f"{cohen_kappa(pooled_g, pooled_h):.3f} | | |"
    )
    w("")
    w("### per-bucket precision and recall against the hand label\n")
    w("`GOOD_* precision` is the share of that bucket the hand read does NOT call weird;")
    w("`WEIRD precision` is the share it does. Recall is over the hand's weird rows.\n")
    w("| run | bucket | n | correct | precision | 95% CI | recall |")
    w("|---|---|---:|---:|---:|---|---:|")
    for lab in c.labels:
        gv = c.graded(lab, dec)
        hv = c.hand_verdicts(lab)
        hand_weird = sum(1 for v in hv if v == WEIRD)
        for bucket in (GOOD_ANSWER, GOOD_DECLINE, WEIRD):
            idx = [k for k, v in enumerate(gv) if v == bucket]
            if not idx:
                continue
            want = bucket == WEIRD
            ok = sum(1 for k in idx if (hv[k] == WEIRD) == want)
            lo, hi = wilson(ok, len(idx))
            rec = f"{ok/hand_weird*100:.1f}%" if want and hand_weird else "-"
            w(
                f"| {lab} | {bucket} | {len(idx)} | {ok} | {ok/len(idx)*100:.1f}% | "
                f"[{lo*100:.1f}%, {hi*100:.1f}%] | {rec} |"
            )
    w("")
    # Pooled WEIRD-bucket precision, which is the one defensible use of this grader.
    tot = ok = 0
    hand_tot = hand_hit = 0
    for lab in c.labels:
        gv = c.graded(lab, dec)
        hv = c.hand_verdicts(lab)
        idx = [k for k, v in enumerate(gv) if v == WEIRD]
        tot += len(idx)
        ok += sum(1 for k in idx if hv[k] == WEIRD)
        hw = sum(1 for v in hv if v == WEIRD)
        hand_tot += hw
        hand_hit += sum(1 for k in idx if hv[k] == WEIRD)
    lo, hi = wilson(ok, tot)
    w(
        f"**Pooled WEIRD-bucket precision: {ok}/{tot} = {ok/tot*100:.1f}% "
        f"[{lo*100:.1f}%, {hi*100:.1f}%]; recall {hand_hit}/{hand_tot} = "
        f"{hand_hit/hand_tot*100:.1f}%.**"
    )
    w("")
    w("That asymmetry is the only defensible reading of this instrument: the count of rows")
    w("it calls WEIRD is a LOWER BOUND on the weird share, not an estimate of it. Its")
    w("GOOD_DECLINE bucket cannot be used as evidence of quality at all, because whether a")
    w("stated absence is TRUE is not checkable from the answer text -- the grader's own")
    w("reason string says so.")
    w("")


def sec_direction(c: Corpus, w: Callable[[str], None]) -> None:
    w("## direction -- does the grader agree with the hand read about the SIGN of a delta?\n")
    w("The write-up's surviving claim for this grader is \"trust its direction, not its")
    w('value". This tests that claim on the five consecutive wave deltas.\n')
    dec = _shipped_is_decline()
    gw = [sum(1 for v in c.graded(lab, dec) if v == WEIRD) for lab in c.labels]
    hw = [sum(1 for v in c.hand_verdicts(lab) if v == WEIRD) for lab in c.labels]
    w("| delta | grader weird | hand weird | grader says | hand says | agree? |")
    w("|---|---|---|---|---|---|")
    agree = 0
    for k in range(len(c.labels) - 1):
        gd, hd = gw[k + 1] - gw[k], hw[k + 1] - hw[k]
        gs = "better" if gd < 0 else ("worse" if gd > 0 else "flat")
        hs = "better" if hd < 0 else ("worse" if hd > 0 else "flat")
        ok = gs == hs
        agree += int(ok)
        w(
            f"| {c.labels[k]} -> {c.labels[k+1]} | {gw[k]} -> {gw[k+1]} | "
            f"{hw[k]} -> {hw[k+1]} | {gs} | {hs} | {'yes' if ok else '**NO**'} |"
        )
    w("")
    w(
        f"Agrees on {agree} of {len(c.labels)-1} consecutive deltas. "
        f"Spearman over the six runs: {spearman(gw, hw):.3f}."
    )
    w("")
    best_g = c.labels[gw.index(min(gw))]
    best_h = c.labels[hw.index(min(hw))]
    w(f"The grader's best run is **{best_g}**; the hand read's best run is **{best_h}**.")
    w("")


def sec_patterns(c: Corpus, w: Callable[[str], None]) -> None:
    from scripts.grade_answers_rubric import _DECLINE_PATTERNS, body_of

    w(
        "## patterns -- which decline pattern put each GOOD_DECLINE row in that bucket "
        "(CAVEAT-784)\n"
    )
    w('CAVEAT-784 names the mechanism: the register census wording "the register does not')
    w('record X" is "the exact shape the grader\'s decline rule rewards". `sole` counts the')
    w("rows for which a pattern is the ONLY decline evidence, so removing it would move")
    w("them out of the bucket.\n")
    compiled = [(p, re.compile(p, re.I)) for p in _DECLINE_PATTERNS]
    dec = _shipped_is_decline()
    for lab in c.labels:
        gv = c.graded(lab, dec)
        hv = c.hand_verdicts(lab)
        bucket = [k for k, v in enumerate(gv) if v == GOOD_DECLINE]
        if not bucket:
            continue
        bad = sum(1 for k in bucket if hv[k] == WEIRD)
        w(
            f"### {lab}: bucket {len(bucket)} rows, {bad} WEIRD by hand "
            f"({bad/len(bucket)*100:.0f}%)\n"
        )
        w("| pattern | fires | of those WEIRD | sole evidence | sole and WEIRD |")
        w("|---|---:|---:|---:|---:|")
        fires: Counter = Counter()
        fires_w: Counter = Counter()
        sole: Counter = Counter()
        sole_w: Counter = Counter()
        for k in bucket:
            body = body_of(c.answers[lab][k].get("answer") or "")
            hits = [p for p, rx in compiled if rx.search(body)]
            bad_row = hv[k] == WEIRD
            for p in hits:
                fires[p] += 1
                fires_w[p] += int(bad_row)
            if len(hits) == 1:
                sole[hits[0]] += 1
                sole_w[hits[0]] += int(bad_row)
        for p, _ in compiled:
            if fires[p]:
                w(f"| `{p}` | {fires[p]} | {fires_w[p]} | {sole[p]} | {sole_w[p]} |")
        w("")


# ── candidate redefinitions of is_decline, each measured against all 882 labels ──────────

#: The register census, mechanically: an absence or presence stated OF A WORD, TERM or
#: CONCEPT rather than of a thing. This set reproduces READER-6's published run-6 row list
#: exactly -- 8 rows, indices 23, 26, 37, 38, 53, 61, 98, 107 -- which is the only external
#: check available on it.
CENSUS_FORMS: Tuple[re.Pattern, ...] = (
    re.compile(
        r"(contain|include|hold|mention|not[ei]|match)\w*\s+(?:the\s+)?"
        r"(?:word|words|term|terms|phrase|phrases|keyword|keywords)\b",
        re.I,
    ),
    re.compile(r"no\s+field\s+(?:name\s+)?or\s+value", re.I),
    re.compile(r"\bthe\s+terms\s+['‘’\"“]", re.I),
    re.compile(r"\|\s*\**\s*Word\(?s\)?\s+found", re.I),
    re.compile(r"\|\s*\**\s*(?:Concept|Keyword|Term|Word)\s*\**\s*\|", re.I),
    re.compile(r"\bconcepts?\s+of\s+[‘’“”'\"]", re.I),
)

#: A printed table row or a bolded bullet: evidence that the answer also answers something.
PRINTED_ROWS = re.compile(r"^\s*(?:\|.*\|\s*$|[-*•]\s+\*\*)", re.M)


def _candidates() -> Dict[str, Callable[[str], bool]]:
    from scripts.grade_answers_rubric import _DECLINE_PATTERNS

    broad = re.compile(_DECLINE_PATTERNS[0], re.I)
    others = [re.compile(p, re.I) for p in _DECLINE_PATTERNS[1:]]

    def shipped(body: str) -> bool:
        return bool(broad.search(body) or any(rx.search(body) for rx in others))

    def no_census(body: str) -> bool:
        if any(rx.search(body) for rx in others):
            return True
        if broad.search(body):
            return not any(rx.search(body) for rx in CENSUS_FORMS)
        return False

    def no_broad_beside_rows(body: str) -> bool:
        if any(rx.search(body) for rx in others):
            return True
        if broad.search(body):
            return len(PRINTED_ROWS.findall(body)) < 3
        return False

    def drop_broad(body: str) -> bool:
        return any(rx.search(body) for rx in others)

    return {
        "shipped": shipped,
        "no_census": no_census,
        "no_broad_beside_rows": no_broad_beside_rows,
        "drop_broad": drop_broad,
    }


def sec_candidates(c: Corpus, w: Callable[[str], None]) -> None:
    w("## candidates -- proposed repairs to `is_decline`, scored before landing (CAVEAT-784)\n")
    w("Each candidate changes ONLY `is_decline`; the signal detectors are untouched. A")
    w("candidate is worth landing when pooled kappa over all the hand labels rises AND no")
    w("run's WEIRD precision falls. `shipped` is the current definition.\n")
    w("| candidate | pooled agree 3-way | pooled kappa | worst-run GOOD_DECLINE precision |")
    w("|---|---:|---:|---:|")
    for name, fn in _candidates().items():
        pg: List[str] = []
        ph: List[str] = []
        worst = 1.0
        for lab in c.labels:
            gv = c.graded(lab, fn)
            hv = c.hand_verdicts(lab)
            pg.extend(gv)
            ph.extend(hv)
            idx = [k for k, v in enumerate(gv) if v == GOOD_DECLINE]
            if idx:
                ok = sum(1 for k in idx if hv[k] != WEIRD) / len(idx)
                worst = min(worst, ok)
        n = len(pg)
        a3 = sum(1 for x, y in zip(pg, ph) if x == y) / n
        w(f"| {name} | {a3*100:.1f}% | {cohen_kappa(pg, ph):.3f} | {worst*100:.1f}% |")
    w("")


def sec_census(c: Corpus, w: Callable[[str], None]) -> None:
    w("## census -- the register-census leak, counted mechanically (BUG-785, BUG-787)\n")
    w("Two forms, as READER-6 defined them: the `word-level` census states an absence or")
    w("presence OF A WORD; the `paraphrase` states it of a FIELD. READER-6's counts were")
    w("produced by regexes that were never committed, so this is an independent")
    w("re-derivation, not a replay.\n")
    paraphrase = re.compile(
        r"\b(?:no|none of the|not any)\s+(?:\w+\s+){0,2}?fields?\b[^.\n]{0,50}?"
        r"\b(?:record|records|recording|specif\w*|captur\w*|directly\s+answer\w*)\b",
        re.I,
    )
    w("| form | " + " | ".join(c.labels) + " |")
    w("|---|" + "---:|" * len(c.labels))
    wl_rows: Dict[str, List[int]] = {}
    for form, name in ((None, "word-level"), (paraphrase, "word-level + paraphrase")):
        cells = []
        for lab in c.labels:
            hits = []
            for k, row in enumerate(c.answers[lab]):
                text = row.get("answer") or ""
                if any(rx.search(text) for rx in CENSUS_FORMS):
                    hits.append(k)
                elif form is not None and form.search(text):
                    hits.append(k)
            cells.append(len(hits))
            if form is None:
                wl_rows[lab] = hits
        w(f"| {name} (re-derived) | " + " | ".join(str(x) for x in cells) + " |")
    w("| word-level (READER-6 published) | 0 | 0 | 0 | 0 | 17 | 8 |")
    w("| + paraphrase (READER-6 published) | 1 | 1 | 8 | 6 | 34 | 19 |")
    w("| word-level (READER-5 published, run 5 only) | | | | | 23 | |")
    w("")
    for lab in c.labels:
        if wl_rows.get(lab):
            w(f"- {lab} word-level rows (0-based): {wl_rows[lab]}")
    w("")
    w("READER-6 named the run-6 word-level rows as 23, 26, 37, 38, 53, 61, 98, 107. A")
    w("re-derivation that matches that set exactly is the check on this detector; the run-5")
    w("level does not match either published figure.")
    w("")


def sec_binding(c: Corpus, w: Callable[[str], None], artefact: Path) -> None:
    w("## binding -- the three claim-binding partitions, from the artefact (CAVEAT-791)\n")
    if not artefact.is_file():
        w(f"artefact not present: {artefact}")
        w("")
        return
    data = json.loads(artefact.read_text(encoding="utf-8"))
    src = data.get("generated_from") or {}
    w(f"Artefact: `{artefact.as_posix()}`")
    w(f"Generated from: `{src.get('answers', '?')}`, hand read `{src.get('hand_read', '?')}`,")
    w(f"evidence `{src.get('evidence', '?')}`.")
    # WHICH RUN the headline is measured on is not stated where the headline is quoted, and
    # it is not the latest. Naming it here, with that run's own hand-read weird share, is
    # the difference between a partition caveat and a stale measurement.
    source = str(src.get("answers") or "").replace("\\", "/").rsplit("/", 1)[-1]
    matched = [lab for lab, ansf, _ in RUNS if ansf == source and lab in c.hand]
    if matched:
        lab = matched[0]
        hv = c.hand_verdicts(lab)
        share = sum(1 for v in hv if v == WEIRD) / len(hv) * 100
        ranked = sorted(
            c.labels,
            key=lambda x: sum(1 for v in c.hand_verdicts(x) if v == WEIRD)
            / len(c.hand_verdicts(x)),
        )
        w("")
        w(
            f"That is **{lab}**, whose own hand read is {share:.1f}% weird -- rank "
            f"{ranked.index(lab)+1} of {len(ranked)} by that measure "
            f"(1 = best). The headline is therefore not measured on the frozen state."
        )
    w("")
    caveat = data.get("caveat")
    if caveat:
        w(f"> {caveat}")
        w("")
    w(
        "| partition | answers | claims | assessed | bound | unbound | unbound rate | "
        "answers with an unbound claim |"
    )
    w("|---|---:|---:|---:|---:|---:|---:|---:|")
    total_answers = 0
    for part in data.get("overall", []):
        rate = part.get("unbound_rate")
        total = part.get("answers") or 0
        if part.get("label", "").startswith("ALL"):
            total_answers = total
        w(
            f"| {part.get('label')} | {total} | {part.get('claims')} | "
            f"{part.get('assessed')} | {part.get('bound')} | {part.get('unbound')} | "
            f"{'-' if rate is None else f'{rate*100:.1f}%'} | "
            f"{part.get('answers_with_an_unbound_claim')} |"
        )
    w("")
    head = next(
        (p for p in data.get("overall", []) if str(p.get("label", "")).startswith("HEADLINE")), None
    )
    if head and total_answers:
        w(
            f"The headline partition covers **{head['answers']} of {total_answers} answers "
            f"= {head['answers']/total_answers*100:.1f}%** of the bank."
        )
        w("")


# ─────────────────────────────────────────────────────────────────────────────────────────
# entry point
# ─────────────────────────────────────────────────────────────────────────────────────────


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--phase0",
        default=str(REPO / "docs" / "phase0"),
        help="directory holding the recorded runs and their hand reads",
    )
    ap.add_argument(
        "--binding-artefact",
        default=str(REPO / "docs" / "phase0" / "claim_binding_measurement.json"),
    )
    ap.add_argument(
        "--bank",
        default=str(REPO / "docs" / "phase0" / "phase0_bank.jsonl"),
        help="the question bank, for each question's written answer boundary",
    )
    ap.add_argument(
        "--asof",
        default="2026-09-18",
        help="YYYY-MM-DD the runs were recorded; enables the grader's stale-date check",
    )
    ap.add_argument("--section", action="append", choices=list(SECTIONS), default=None)
    ap.add_argument("--out", help="also write the report to this path")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except AttributeError:  # pragma: no cover - older interpreters
        pass

    asof: Optional[dt_date] = None
    if args.asof:
        try:
            asof = dt_date.fromisoformat(args.asof)
        except ValueError:
            print(f"--asof must be YYYY-MM-DD, got {args.asof!r}", file=sys.stderr)
            return 2

    corpus = Corpus(Path(args.phase0), bank=Path(args.bank), asof=asof)
    if not corpus.labels:
        print(f"no recorded runs found under {args.phase0}", file=sys.stderr)
        return 2

    lines: List[str] = []

    def w(line: str = "") -> None:
        lines.append(line)

    w("# Wave F -- the measurement apparatus, re-derived")
    w("")
    w(
        f"Source: `{Path(args.phase0).as_posix()}`. Runs found: "
        f"{', '.join(corpus.labels)}"
        + (f"; MISSING: {', '.join(corpus.missing)}" if corpus.missing else "")
        + "."
    )
    w(
        f"Same questions in the same order across every run: "
        f"**{'yes' if corpus.aligned else 'NO -- the pairing below is invalid'}**."
    )
    problems = corpus.check_fidelity()
    w(
        "This module's grader call reproduces `grade_run` row for row: "
        + ("**yes**." if not problems else "**NO** -- " + "; ".join(problems))
    )
    w("")

    wanted = args.section or list(SECTIONS)
    for name in SECTIONS:
        if name not in wanted:
            continue
        if name == "series":
            sec_series(corpus, w)
        elif name == "mcnemar":
            sec_mcnemar(corpus, w)
        elif name == "agreement":
            sec_agreement(corpus, w)
        elif name == "direction":
            sec_direction(corpus, w)
        elif name == "patterns":
            sec_patterns(corpus, w)
        elif name == "candidates":
            sec_candidates(corpus, w)
        elif name == "census":
            sec_census(corpus, w)
        elif name == "binding":
            sec_binding(corpus, w, Path(args.binding_artefact))

    report = "\n".join(lines)
    print(report)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report + "\n", encoding="utf-8")
        print(f"\nwrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
