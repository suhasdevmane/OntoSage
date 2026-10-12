#!/usr/bin/env python3
"""Run the instructed assistant from the host: copy the package into the orchestrator container and
run it there, where the graph, the stores and the model gateway resolve exactly as OntoSage's do.

    python scripts/instructed_baseline/launch.py --in questions.jsonl --out dev_run1.jsonl [--repeat 3]

``--in`` is copied to outputs/instructed_baseline/inputs/ (bind-mounted at /app/outputs) and the
results land in outputs/instructed_baseline/<out>. The orchestrator itself is untouched: the package
lives in /tmp inside the container and nothing in orchestrator/ imports it (requirement R4).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PKG = Path(__file__).resolve().parent
HOST_DIR = REPO / "outputs" / "instructed_baseline"
CONTAINER = "ontosage-orchestrator"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True, help="file name under outputs/instructed_baseline/")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--prompt", default="v1.txt")
    ap.add_argument("--qids", default="")
    args = ap.parse_args()

    (HOST_DIR / "inputs").mkdir(parents=True, exist_ok=True)
    src = Path(args.inp)
    dst = HOST_DIR / "inputs" / src.name
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    subprocess.run(
        ["docker", "exec", "-u", "root", CONTAINER, "rm", "-rf", "/tmp/instructed_baseline"],
        check=True,
    )
    subprocess.run(["docker", "cp", str(PKG), f"{CONTAINER}:/tmp/instructed_baseline"], check=True)
    cmd = [
        "docker",
        "exec",
        "-e",
        "PYTHONPATH=/app:/tmp",
        "-w",
        "/tmp",
        CONTAINER,
        "python",
        "-m",
        "instructed_baseline.run",
        "--in",
        f"/app/outputs/instructed_baseline/inputs/{dst.name}",
        "--out",
        f"/app/outputs/instructed_baseline/{args.out}",
        "--repeat",
        str(args.repeat),
        "--prompt",
        args.prompt,
    ]
    if args.qids:
        cmd += ["--qids", args.qids]
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    sys.exit(main())
