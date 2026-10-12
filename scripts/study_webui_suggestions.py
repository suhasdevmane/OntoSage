#!/usr/bin/env python3
"""Clear (for the Paper 3 study) or restore Open WebUI's new-chat prompt suggestions.

The suggestions ("Where's the coolest place to work in the building right now?", ...) sit on every
new chat. A participant could click one instead of phrasing their own question, which is exactly
what the study's first-question data (T-LIVE) must not contain. Open WebUI keeps them in its
database (config.ui.default_prompt_suggestions), where they override any environment variable.

    docker compose stop open-webui
    python scripts/study_webui_suggestions.py --clear     # saves the originals, then empties the list
    python scripts/study_webui_suggestions.py --restore   # after the study
    docker compose up -d open-webui

Only run it with Open WebUI STOPPED (the database must not be written while the app holds it).
A timestamped copy of the database is made before every change.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def db_path() -> Path:
    bid = ""
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("BUILDING_ID="):
            bid = line.split("=", 1)[1].strip()
    return REPO / "volumes" / bid / "open-webui" / "webui.db"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--clear", action="store_true")
    g.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    db = db_path()
    saved = db.parent / "study_saved_prompt_suggestions.json"
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(db, db.with_name(f"webui.db.bak-study-{stamp}"))
    con = sqlite3.connect(db)
    cid, data = con.execute("select id, data from config order by id desc limit 1").fetchone()
    cfg = json.loads(data)
    ui = cfg.setdefault("ui", {})
    if args.clear:
        current = ui.get("default_prompt_suggestions") or []
        if current and not saved.exists():
            saved.write_text(
                json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        ui["default_prompt_suggestions"] = []
        print(f"cleared {len(current)} suggestions; originals in {saved.name}")
    else:
        if not saved.exists():
            print("nothing saved to restore")
            return 1
        ui["default_prompt_suggestions"] = json.loads(saved.read_text(encoding="utf-8"))
        print(f"restored {len(ui['default_prompt_suggestions'])} suggestions")
    con.execute("update config set data = ? where id = ?", (json.dumps(cfg), cid))
    con.commit()
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
