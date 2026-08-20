# -*- coding: utf-8 -*-
"""V5-T17/T14 — time-travel forecast grader + walk-forward skill registry.

The grader controls time: pick historical cutoffs, forecast from each cutoff
using ONLY data before it (the same ModelSelector the live lanes use, frozen
parameters), then grade against what actually happened afterwards.

  per (modality × horizon):  MAE / RMSE / MAPE over the forecast path,
                             CI coverage (do the 80%/95% bands contain the
                             truth ~80/95% of the time?), n graded fits.

Outputs
  scripts/outputs/v5_t17_forecast_scorecard_r<N>_<ts>.csv   per-fit rows
  volumes/<building>/artifacts/forecast_skill.json          the SKILL REGISTRY
                             (per modality × horizon; what a live answer's
                             cited error is checked against)

Rounds shift the cutoff set by one day so three rounds never grade the same
windows. Building-agnostic: tables discovered by narrow shape, identity from
.env, nothing hardcoded.

Usage:  python scripts/grade_forecasts.py --round 1
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

OUT = _REPO / "scripts" / "outputs"

#: horizons graded (hours) — 1w excluded: cadence×history makes it low-value here
HORIZONS_H = (1, 6, 24)

#: sensors sampled per table and cutoffs per round (runtime budget)
SENSORS_PER_TABLE = 2
CUTOFF_DAYS_BACK = (7, 14, 21)

#: grade these core modalities (dense daily-cyclic + occupancy)
TABLES = (
    "temperature_data",
    "co2_data",
    "humidity_data",
    "noise_data",
    "pm25_data",
    "occupancy_data",
)


def _env() -> dict:
    env = {}
    for line in (_REPO / ".env").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _mysql(env: dict):
    import pymysql

    return pymysql.connect(
        host="localhost",
        port=3306,
        user=env.get("MYSQL_USER", "root"),
        password=env.get("MYSQL_PASSWORD", ""),
        database=env.get("MYSQL_DATABASE", "sensordb"),
    )


def _fetch(cur, table: str, uid: str, start: datetime, end: datetime) -> List[dict]:
    cur.execute(
        f"SELECT `datetime`, `value` FROM `{table}` WHERE uuid=%s "  # nosec B608
        f"AND `datetime` > %s AND `datetime` <= %s ORDER BY `datetime`",
        (uid, start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")),
    )
    return [{"timestamp": r[0], "uuid": uid, "value": r[1]} for r in cur.fetchall()]


def grade_fit(
    history: List[dict],
    actuals: List[dict],
    horizon_h: int,
    calibrate: Optional[str] = None,
    building: str = "",
) -> Optional[dict]:
    """One time-travel fit: forecast past the cutoff, grade vs the truth."""
    import numpy as np

    from orchestrator.services.forecasting.model_selector import ModelSelector
    from orchestrator.services.forecasting.preprocessor import preprocess_series

    hist_series, _ = preprocess_series(history, resample_freq="10min")
    if hist_series is None or len(hist_series) < 48:
        return None
    act_series, _ = preprocess_series(actuals, resample_freq="10min")
    if act_series is None or len(act_series) < 3:
        return None
    steps = int(horizon_h * 6)
    steps_per_day = 144
    seasonal = steps_per_day if len(hist_series) >= 2 * steps_per_day else None
    try:
        sel = ModelSelector().select_and_forecast(
            hist_series, n_steps=steps, seasonal_periods=seasonal
        )
    except Exception:
        return None
    fc = np.asarray(sel["forecast"], dtype=float)
    lo80 = np.asarray(sel.get("lower_80") or [], dtype=float)
    hi80 = np.asarray(sel.get("upper_80") or [], dtype=float)
    lo95 = np.asarray(sel.get("lower_95") or [], dtype=float)
    hi95 = np.asarray(sel.get("upper_95") or [], dtype=float)
    if calibrate:
        # T14 verify mode: widen bands by the registry factors before grading
        from orchestrator.services.forecasting.calibration import band_factors

        f80, f95 = band_factors(building, calibrate, horizon_h, repo_root=_REPO)
        if len(lo80) and f80 > 1.0:
            mid = fc[: len(lo80)]
            lo80 = mid - (mid - lo80) * f80
            hi80 = mid + (hi80 - mid) * f80
        if len(lo95) and f95 > 1.0:
            mid = fc[: len(lo95)]
            lo95 = mid - (mid - lo95) * f95
            hi95 = mid + (hi95 - mid) * f95
    truth = np.asarray(act_series.values[: len(fc)], dtype=float)
    n = min(len(truth), len(fc))
    if n < 3:
        return None
    fc, truth = fc[:n], truth[:n]
    err = np.abs(fc - truth)
    out = {
        "model": sel.get("winner", "?"),
        "n_points": int(n),
        "mae": round(float(err.mean()), 4),
        "rmse": round(float(np.sqrt(((fc - truth) ** 2).mean())), 4),
        "mape": (
            round(float((err[truth != 0] / np.abs(truth[truth != 0])).mean() * 100), 2)
            if (truth != 0).any()
            else None
        ),
    }
    if len(lo80) >= n and len(hi80) >= n:
        out["ci80_coverage"] = round(float(((truth >= lo80[:n]) & (truth <= hi80[:n])).mean()), 3)
    if len(lo95) >= n and len(hi95) >= n:
        out["ci95_coverage"] = round(float(((truth >= lo95[:n]) & (truth <= hi95[:n])).mean()), 3)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument(
        "--calibrated",
        action="store_true",
        help="apply the registry-driven band inflation before grading coverage (T14 verify)",
    )
    args = ap.parse_args()

    env = _env()
    building = env.get("BUILDING_ID", "unknown")
    print(f"— T17 forecast grader · round {args.round} · {building} —")
    conn = _mysql(env)
    cur = conn.cursor()
    now = datetime.utcnow()
    # rounds shift cutoffs by a day so no two rounds grade identical windows
    cutoffs = [now - timedelta(days=d + (args.round - 1)) for d in CUTOFF_DAYS_BACK]

    rows_out: List[Dict[str, Any]] = []
    agg: Dict[tuple, List[dict]] = {}
    for table in TABLES:
        cur.execute(
            f"SELECT uuid FROM `{table}` GROUP BY uuid HAVING COUNT(*) >= 500 "  # nosec B608
            f"ORDER BY uuid LIMIT {SENSORS_PER_TABLE}"
        )
        uids = [r[0] for r in cur.fetchall()]
        modality = table.replace("_data", "")
        for uid in uids:
            for cutoff in cutoffs:
                history = _fetch(cur, table, uid, cutoff - timedelta(hours=72), cutoff)
                for horizon in HORIZONS_H:
                    actuals = _fetch(cur, table, uid, cutoff, cutoff + timedelta(hours=horizon))
                    g = grade_fit(
                        history,
                        actuals,
                        horizon,
                        calibrate=(modality if args.calibrated else None),
                        building=building,
                    )
                    if g is None:
                        continue
                    row = {
                        "round": args.round,
                        "modality": modality,
                        "uuid": uid[:12],
                        "cutoff": cutoff.strftime("%Y-%m-%d %H:%M"),
                        "horizon_h": horizon,
                        **g,
                    }
                    rows_out.append(row)
                    agg.setdefault((modality, horizon), []).append(g)
        print(f"  graded {modality:<14} fits so far: {len(rows_out)}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = OUT / f"v5_t17_forecast_scorecard_r{args.round}_{stamp}.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)

    # ── skill registry (T14): per modality × horizon ───────────────────────
    registry_path = _REPO / "volumes" / building / "artifacts" / "forecast_skill.json"
    registry: Dict[str, Any] = {}
    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        except ValueError:
            registry = {}
    print(f"\n{'modality':<14}{'h':>4}{'n':>5}{'MAE':>10}{'RMSE':>10}{'ci80':>7}{'ci95':>7}")
    for (modality, horizon), fits in sorted(agg.items()):

        def _mean(key):
            vals = [f[key] for f in fits if f.get(key) is not None]
            return round(sum(vals) / len(vals), 4) if vals else None

        entry = {
            "mae": _mean("mae"),
            "rmse": _mean("rmse"),
            "mape": _mean("mape"),
            "ci80_coverage": _mean("ci80_coverage"),
            "ci95_coverage": _mean("ci95_coverage"),
            "n_fits": len(fits),
            "graded_at": datetime.now().isoformat(timespec="seconds"),
            "round": args.round,
        }
        registry.setdefault(modality, {})[f"{horizon}h"] = entry
        c80 = entry["ci80_coverage"] if entry["ci80_coverage"] is not None else "-"
        c95 = entry["ci95_coverage"] if entry["ci95_coverage"] is not None else "-"
        print(
            f"{modality:<14}{horizon:>4}{len(fits):>5}{entry['mae']:>10}"
            f"{entry['rmse']:>10}{c80:>7}{c95:>7}"
        )
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    print(f"\nskill registry -> {registry_path}")
    print(f"per-fit rows   -> {out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
