"""Build the LLM-judge pool for the v1/v2/ablation blinded read.

    python scripts/llm_panel_build.py <work_dir>

Every answer becomes one opaque record (a001...). Judges see question, shape, answerability,
criteria and ONE answer -- never which system wrote it, never two answers to the same item.
Three rounds, each a different deterministic shuffle cut into batches with no repeated item.
The private map (answer id -> set/item/slot) lives in <work_dir>/private/ and is not given to
judges. Run after make_blinded_sheet.py, before eval/compound/scoring/llm_panel/panel_workflow.js
(the judge prompt and rubric as run on 2026-10-08), then scripts/llm_panel_apply.py.
Prints counts only. All seeds are fixed, so the same sheets give the same batches.
"""
import csv
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1])
BATCH = 7
ROUNDS = 3

(OUT / "batches").mkdir(parents=True, exist_ok=True)
(OUT / "private").mkdir(parents=True, exist_ok=True)

pool = []
for s in ("T-REAL", "T-REAL-SUPPLEMENT", "T-CAT"):
    rows = list(csv.DictReader(open(REPO / f"eval/compound/scoring/{s}_sheet.csv", encoding="utf-8-sig")))
    meta = {r["id"]: r for r in rows}
    for r in rows:
        for slot in ("X", "Y"):
            pool.append({"set": s, "item": r["id"], "slot": slot, "answer": r[f"answer_{slot}"], "row": r})
    abl = REPO / f"eval/compound/results/v2-ablation/{s}.jsonl"
    if abl.exists():
        for line in abl.open(encoding="utf-8"):
            o = json.loads(line)
            r = meta[o["id"]]
            ans = o.get("answer") or f"[no answer: {o.get('error', 'missing')}]"
            pool.append({"set": s, "item": o["id"], "slot": "Z", "answer": ans, "row": r})

rng = random.Random(20261008)
rng.shuffle(pool)  # opaque ids carry no order information
private, public = {}, {}
for n, p in enumerate(pool, 1):
    aid = f"a{n:03d}"
    r = p["row"]
    private[aid] = {"set": p["set"], "item": p["item"], "slot": p["slot"]}
    public[aid] = {
        "answer_id": aid,
        "question": r["question"],
        "shape": r["shape"],
        "answerability": r["answerability"],
        "criteria_needed": [c.strip() for c in r["criteria_needed"].split(";") if c.strip()],
        "answer": p["answer"],
    }
    public[aid]["_item"] = f'{p["set"]}|{p["item"]}'  # used only for batching below

(OUT / "private" / "answer_map.json").write_text(json.dumps(private, indent=1), encoding="utf-8")

rounds = []
for rd in range(ROUNDS):
    ids = sorted(public)
    random.Random(1000 + rd).shuffle(ids)
    batches = []
    for aid in ids:
        item = public[aid]["_item"]
        for b in batches:  # first batch with room and no answer to the same item
            if len(b) < BATCH and all(public[x]["_item"] != item for x in b):
                b.append(aid)
                break
        else:
            batches.append([aid])
    paths = []
    for k, b in enumerate(batches, 1):
        recs = [{kk: vv for kk, vv in public[a].items() if kk != "_item"} for a in b]
        p = OUT / "batches" / f"r{rd + 1}_b{k:02d}.json"
        p.write_text(json.dumps(recs, indent=1, ensure_ascii=False), encoding="utf-8")
        paths.append(str(p))
    rounds.append(paths)

index = {a: {k: v for k, v in rec.items() if k != "_item"} for a, rec in public.items()}
(OUT / "answers_index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")
(OUT / "rounds.json").write_text(json.dumps(rounds, indent=1), encoding="utf-8")
by_slot = {}
for v in private.values():
    by_slot[v["slot"]] = by_slot.get(v["slot"], 0) + 1
print(len(pool), "answers;", by_slot, "; batches per round:", [len(r) for r in rounds],
      "; max batch:", max(len(json.load(open(p, encoding="utf-8"))) for r in rounds for p in r))
