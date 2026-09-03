# -*- coding: utf-8 -*-
"""V5-T13 verify artifact — hold-out backtest table on the ACTIVE building's data.

For each saturation modality table found in the active building's MySQL DB,
sample a few sensor series, run the ModelSelector's individual forecasters on
an 80/20 hold-out split, and tabulate MAE per model. Proves (on real stored
series, not synthetic fixtures) whether the seasonal-naive tier earns its
place for daily-cyclic modalities.

Usage (host, active building):
    python scripts/forecast_backtest_table.py [--per-table 5] [--window-hours 72]

Building-agnostic: identity comes from .env, tables are discovered from
information_schema by the (uuid, datetime, value) narrow shape — nothing is
hardcoded to any building.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import pymysql  # noqa: E402

from orchestrator.services.forecasting.models.exp_smoothing_forecaster import (  # noqa: E402
    ExpSmoothingForecaster,
)
from orchestrator.services.forecasting.models.linear_forecaster import (  # noqa: E402
    LinearTrendForecaster,
)
from orchestrator.services.forecasting.models.seasonal_naive_forecaster import (  # noqa: E402
    SeasonalNaiveForecaster,
)
from orchestrator.services.forecasting.preprocessor import (  # noqa: E402
    preprocess_series,
)
from shared.db_clock import UTC_SESSION_INIT

_MODELS = {
    "linear": lambda: LinearTrendForecaster(degree=1),
    "exp_smoothing": lambda: ExpSmoothingForecaster(),
    "seasonal_naive": lambda: SeasonalNaiveForecaster(),
}


def _env() -> dict:
    env = {}
    env_path = _REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _mysql(env: dict):
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", env.get("MYSQL_USER", "root")),
        password=os.environ.get("MYSQL_PASSWORD", env.get("MYSQL_PASSWORD", "")),
        database=os.environ.get("MYSQL_DATABASE", env.get("MYSQL_DATABASE", "sensordb")),
        # Same clock the rows are stamped in (BUG-403).
        init_command=UTC_SESSION_INIT,
    )


def _narrow_tables(cur) -> list:
    """Tables with EXACTLY the narrow (uuid, datetime, value) reading shape."""
    cur.execute(
        "SELECT table_name FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND column_name IN ('uuid','datetime','value') "
        "GROUP BY table_name HAVING COUNT(DISTINCT column_name) = 3"
    )
    return sorted(r[0] for r in cur.fetchall() if r[0] != "events")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-table", type=int, default=5)
    ap.add_argument("--window-hours", type=int, default=72)
    args = ap.parse_args()

    env = _env()
    building = env.get("BUILDING_ID", os.environ.get("BUILDING_ID", "unknown"))
    conn = _mysql(env)
    cur = conn.cursor()
    tables = _narrow_tables(cur)
    if not tables:
        print("No narrow (uuid, datetime, value) tables found — nothing to backtest.")
        return 1

    rows_out = []
    for table in tables:
        cur.execute(
            f"SELECT uuid, COUNT(*) AS n FROM `{table}` "  # nosec B608 — table from info_schema
            f"GROUP BY uuid HAVING n >= 48 ORDER BY uuid LIMIT %s",
            (args.per_table,),
        )
        uuids = [r[0] for r in cur.fetchall()]
        for uid in uuids:
            cur.execute(
                f"SELECT `datetime`, `value` FROM `{table}` WHERE uuid=%s "  # nosec B608
                f"AND `datetime` >= NOW() - INTERVAL %s HOUR ORDER BY `datetime`",
                (uid, args.window_hours),
            )
            recs = [{"timestamp": r[0], "uuid": uid, "value": r[1]} for r in cur.fetchall()]
            if len(recs) < 48:
                continue
            series, _info = preprocess_series(recs, resample_freq="10min")
            if series is None or len(series) < 48:
                series, _info = preprocess_series(recs, resample_freq="1h")
            if series is None or len(series) < 24:
                continue
            maes = {}
            for name, factory in _MODELS.items():
                try:
                    maes[name] = round(factory().fit_predict(series, n_steps=6)["metrics"].mae, 4)
                except Exception:
                    maes[name] = None
            valid = {k: v for k, v in maes.items() if v is not None}
            if not valid:
                continue
            rows_out.append(
                {
                    "building": building,
                    "table": table,
                    "uuid": uid[:12],
                    "n_points": len(series),
                    **{f"mae_{k}": maes.get(k) for k in _MODELS},
                    "winner": min(valid, key=valid.get),
                }
            )

    out_dir = _REPO_ROOT / "scripts" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"v5_t13_backtest_{building}.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)

    # ── summary table ──────────────────────────────────────────────────────
    print(f"\nBacktest @ {datetime.now():%Y-%m-%d %H:%M} — {building}, {len(rows_out)} series")
    print(f"{'table':<24}{'n':>4}  {'linear':>10}{'exp_smooth':>12}{'seas_naive':>12}  wins(sn)")
    by_table: dict = {}
    for r in rows_out:
        by_table.setdefault(r["table"], []).append(r)
    for table, rs in sorted(by_table.items()):

        def _mean(key):
            vals = [r[key] for r in rs if r[key] is not None]
            return f"{sum(vals) / len(vals):10.3f}" if vals else "         -"

        sn_wins = sum(1 for r in rs if r["winner"] == "seasonal_naive")
        print(
            f"{table:<24}{len(rs):>4}  {_mean('mae_linear')}{_mean('mae_exp_smoothing'):>12}"
            f"{_mean('mae_seasonal_naive'):>12}  {sn_wins}/{len(rs)}"
        )
    total_sn = sum(1 for r in rows_out if r["winner"] == "seasonal_naive")
    print(f"\nseasonal-naive wins {total_sn}/{len(rows_out)} series overall -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
