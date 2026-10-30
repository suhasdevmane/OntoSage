#!/usr/bin/env python3
"""The pre-registered A-minus run (plan 03 section 7.2), unattended and self-restoring (TODO 2.4).

    python e6_aminus.py            # waits for the comparison and stability runs, then does everything below

1. Waits until runs/e6_comparison_A_B.jsonl has 200 rows and runs/e6_stability_A_B_x3.jsonl 180, both quiet 90 s.
2. Re-runs each provider failure once (e6_rerun_pf.py), BEFORE the configuration changes.
3. Records the state: configuration hash (the freeze method: sha256 of .env without KEY/SECRET/PASSWORD/TOKEN lines),
   the full .env hash, the container's start time; saves the orchestrator log (gz) to raw_restricted.
4. Backs up .env to .env.before_aminus (git-ignored, local only), appends
       REFERENT_VALIDATION_ENABLED=false
       ANSWER_RELEVANCE_GATE=false
   recreates the orchestrator (docker compose up -d --no-deps --force-recreate orchestrator), waits for /health,
   checks both values INSIDE the container, and warms up with one neutral question (discarded).
5. Runs e6_run.py --systems A --config A-minus on inputs/comparison_sample.jsonl -> runs/e6_comparison_Aminus.jsonl.
6. ALWAYS (finally): saves the A-minus container's log (gz, raw_restricted; added after the first run lost it),
   restores .env from the backup, checks its full hash equals step 3, recreates the orchestrator,
   waits for /health, checks both values are gone from the container and the configuration hash is the logged one;
   deletes the backup only if every check passed.
Every step, time and hash goes to e6_offline_runs/aminus_record.json. Secrets are never printed or copied.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from study_paths import E6, RAW, REPO  # noqa: E402

ENV = REPO / ".env"
BAK = REPO / ".env.before_aminus"
RUNS = E6 / "runs"
REC = E6 / "aminus_record.json"
LOGGED_HASH = "204d8062eabc84a5e481d325d1a2e26d7ffef15c23ba3739ffb471363ab84338"
LINES = "\n# A-minus run (pre-registered ablation, plan 03 7.2) - TEMPORARY, removed by e6_aminus.py\n" \
        "REFERENT_VALIDATION_ENABLED=false\nANSWER_RELEVANCE_GATE=false\n"
record: dict = {"steps": []}


def log(step: str, **kw) -> None:
    kw = {"step": step, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **kw}
    record["steps"].append(kw)
    REC.write_text(json.dumps(record, indent=1), encoding="utf-8")
    print(json.dumps(kw), flush=True)


def config_hash() -> str:
    keep = [ln for ln in ENV.read_text(encoding="utf-8").splitlines(keepends=True)
            if not any(w in ln for w in ("KEY", "SECRET", "PASSWORD", "TOKEN"))]
    return hashlib.sha256("".join(keep).encode("utf-8")).hexdigest()


def file_hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def sh(args: list, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def rows(p: Path) -> int:
    return sum(1 for ln in p.open(encoding="utf-8") if ln.strip()) if p.exists() else 0


def healthy(wait_s: int = 900) -> bool:
    t0 = time.time()
    while time.time() - t0 < wait_s:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=10) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(10)
    return False


def container_flags() -> dict:
    out = sh(["docker", "exec", "ontosage-orchestrator", "sh", "-c",
              "env | grep -E '^(REFERENT_VALIDATION_ENABLED|ANSWER_RELEVANCE_GATE)=' || true"]).stdout
    return dict(ln.split("=", 1) for ln in out.split() if "=" in ln)


def recreate() -> str:
    p = sh(["docker", "compose", "up", "-d", "--no-deps", "--force-recreate", "orchestrator"], timeout=900)
    started = sh(["docker", "inspect", "--format", "{{.State.StartedAt}}", "ontosage-orchestrator"]).stdout.strip()
    return f"exit {p.returncode}; StartedAt {started}"


def main() -> int:
    comp, stab = RUNS / "e6_comparison_A_B.jsonl", RUNS / "e6_stability_A_B_x3.jsonl"
    log("waiting for the runs", comparison=rows(comp), stability=rows(stab))
    while True:
        done = rows(comp) >= 200 and rows(stab) >= 180
        quiet = all(time.time() - p.stat().st_mtime > 90 for p in (comp, stab) if p.exists())
        if done and quiet:
            break
        time.sleep(60)
    log("runs complete", comparison=rows(comp), stability=rows(stab))
    p = subprocess.run([sys.executable, str(HERE / "e6_rerun_pf.py"), str(comp), str(stab), "--tag", "pf2"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    log("provider-failure re-runs", output=p.stdout[-800:], exit=p.returncode)
    pre_cfg, pre_full = config_hash(), file_hash(ENV)
    started = sh(["docker", "inspect", "--format", "{{.State.StartedAt}}", "ontosage-orchestrator"]).stdout.strip()
    log("state before", config_hash=pre_cfg, config_hash_matches_logged=(pre_cfg == LOGGED_HASH),
        env_full_sha256_prefix=pre_full[:16], container_started=started, flags_in_container=container_flags())
    if pre_cfg != LOGGED_HASH:
        log("ABORT: configuration hash is not the logged one; nothing changed")
        return 2
    logdir = RAW / "ontosage" / "orchestrator_logs"
    logdir.mkdir(parents=True, exist_ok=True)
    lg = sh(["docker", "logs", "--timestamps", "ontosage-orchestrator"], timeout=600)
    out = logdir / f"orchestrator_before_aminus_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.log.gz"
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        fh.write(lg.stdout + lg.stderr)
    log("orchestrator log saved", file=out.name, bytes=out.stat().st_size)
    shutil.copy2(ENV, BAK)
    ok_all = False
    try:
        with ENV.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(LINES)
        log("env changed", config_hash=config_hash(), recreate=recreate())
        h = healthy()
        flags = container_flags()
        log("A-minus up", healthy=h, flags_in_container=flags)
        if not h or flags.get("REFERENT_VALIDATION_ENABLED") != "false" or flags.get("ANSWER_RELEVANCE_GATE") != "false":
            log("ABORT: A-minus not confirmed in the container; restoring")
            return 3
        sys.path.insert(0, str(REPO / "scripts" / "instructed_baseline"))
        import run_comparison as rc  # noqa: E402
        rc.flush()
        w = rc.ask_ontosage("How many floors does the building have?", "offline@study.example.com", 420)
        log("warm-up (discarded)", seconds=w.get("seconds"), error=bool(w.get("error")))
        p = subprocess.run([sys.executable, str(HERE / "e6_run.py"), "--in", str(E6 / "inputs" / "comparison_sample.jsonl"),
                            "--out", str(RUNS / "e6_comparison_Aminus.jsonl"), "--systems", "A", "--config", "A-minus",
                            "--email", "offline@study.example.com", "--tag", "am"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        (E6 / "logs" / "aminus_run.log").write_text(p.stdout + p.stderr, encoding="utf-8")
        log("A-minus run finished", exit=p.returncode, rows=rows(RUNS / "e6_comparison_Aminus.jsonl"))
    finally:
        # Keep the A-minus container's own log (its check records) before the restore recreates the container: the
        # first run (24 Oct) lost it this way. A failure here must never stop the restore.
        try:
            lg2 = sh(["docker", "logs", "--timestamps", "ontosage-orchestrator"], timeout=600)
            out2 = logdir / f"orchestrator_aminus_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.log.gz"
            with gzip.open(out2, "wt", encoding="utf-8") as fh:
                fh.write(lg2.stdout + lg2.stderr)
            log("A-minus orchestrator log saved", file=out2.name, bytes=out2.stat().st_size)
        except Exception as exc:  # noqa: BLE001 - the restore below must run whatever happened here
            log("A-minus orchestrator log NOT saved", error=type(exc).__name__)
        shutil.copy2(BAK, ENV)
        restored = file_hash(ENV) == pre_full
        rc_out = recreate()
        h = healthy()
        flags = container_flags()
        cfg = config_hash()
        ok_all = restored and h and not flags and cfg == LOGGED_HASH
        log("restored", env_identical=restored, recreate=rc_out, healthy=h, flags_in_container=flags,
            config_hash=cfg, config_hash_matches_logged=(cfg == LOGGED_HASH), all_checks_passed=ok_all)
        if ok_all:
            BAK.unlink()
            log("backup removed")
        else:
            log("CHECK FAILED: .env.before_aminus kept in the repo root; see this record")
    return 0 if ok_all else 4


if __name__ == "__main__":
    raise SystemExit(main())
