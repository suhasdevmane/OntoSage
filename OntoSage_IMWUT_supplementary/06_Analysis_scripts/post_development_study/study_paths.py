"""Shared paths and helpers for the Paper 3 analysis scripts (F_Analysis).

Every analysis script reads ONLY the de-identified dataset (G_Study_Data/deidentified_v1/). The restricted raw copy
(G_Study_Data/raw_restricted/) holds identifiable material (consent forms, sign-up e-mails) and is read only by
build_study_dataset.py.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Optional

F = Path(__file__).resolve().parent                 # 11_Study_Materials/F_Analysis
SM = F.parent                                       # 11_Study_Materials
V9 = SM.parent                                      # [anonymised]
REPO = V9.parents[2]                                # OntoSage repository root
APP = SM / "B_Session" / "survey_app"
BANK = SM / "C_Task_Bank_and_Keys" / "task_bank.csv"
INSTANCES = SM / "C_Task_Bank_and_Keys" / "task_bank_instances.json"
ORDERS = F / "outputs" / "version_orders.csv"
SCHEDULE = F / "outputs" / "assignment_schedule.csv"
EXPORTS = F / "data" / "exports"
G = SM / "G_Study_Data"
RAW = G / "raw_restricted"
DEID = G / "deidentified_v1"
LABELS = G / "labels"
E6 = G / "e6_offline_runs"
RESULTS = F / "results"          # analysis outputs (tables, numbers) — real data, de-identified
FIGS = F / "figures"             # figures (PDF + PNG) and their code
MAIN_CODES = [f"P{n:02d}" for n in range(1, 31)]
SEED = 20261009                  # the project's pre-declared seed (make_partA_samples.py, draw_double_coding_sample.py)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def T(x) -> Optional[dt.datetime]:
    """ISO text (with Z/offset, or naive = UTC) -> aware UTC datetime."""
    if not x:
        return None
    if isinstance(x, dt.datetime):
        return x if x.tzinfo else x.replace(tzinfo=dt.timezone.utc)
    s = str(x).strip().replace("Z", "+00:00").replace(" ", "T", 1)
    if "." in s:  # normalise fractional seconds to 6 digits for Python 3.10
        head, frac = s.split(".", 1)
        tail = ""
        for i, ch in enumerate(frac):
            if not ch.isdigit():
                tail = frac[i:]
                frac = frac[:i]
                break
        s = f"{head}.{(frac + '000000')[:6]}{tail}"
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def write_manifest(folder: Path, inputs: dict, note: str = "") -> None:
    """manifest.json: SHA-256 of every input and every file in the folder (except the manifest)."""
    out = {"written_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "note": note,
           "inputs": {k: sha256(Path(v)) for k, v in inputs.items() if Path(v).is_file()},
           "outputs": {p.relative_to(folder).as_posix(): sha256(p) for p in sorted(folder.rglob("*"))
                       if p.is_file() and p.name != "manifest.json"}}
    (folder / "manifest.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


PASS1_SOURCES = (("answer_labels_agreed.csv", "HUMAN_AGREED"), ("answer_labels_author.csv", "AUTHOR_CHECKED"),
                 ("answer_labels_ai_prelabel.csv", "PROVISIONAL_AI_PRELABEL"))


def pass1_labels() -> tuple:
    """The labels of the answers participants saw, and their source: the file agreed by two coders, else the
    author's check of every AI pre-label (plan 19, Option A), else the AI pre-labels."""
    for name, src in PASS1_SOURCES:
        if (LABELS / name).exists():
            return LABELS / name, src
    return None, "none"
