# How to score the v1 / v2 comparison (the blinded read)

You are the one reader the protocol names (`tasks/V2_COMPOUND_PLAN.md` section 5). Nothing here
should be scored by a script; the scripts only arrange and count.

## 1. Make the sheets (once v1 and v2 are both captured)

```bash
python scripts/make_blinded_sheet.py --set eval/compound/T-REAL.jsonl            --a v1 --b v2
python scripts/make_blinded_sheet.py --set eval/compound/T-REAL-SUPPLEMENT.jsonl --a v1 --b v2
python scripts/make_blinded_sheet.py --set eval/compound/T-CAT.jsonl             --a v1 --b v2
```

Each writes, under `eval/compound/scoring/`:

| file | what it is | open it? |
|---|---|---|
| `<set>_sheet.html` | every item, its two answers as **X** and **Y** | yes — read here |
| `<set>_sheet.csv` | the same items, one row each, with empty label columns | yes — score here |
| `<set>_key.json` | which system wrote X and which wrote Y | **no — not until every row is scored** |

The order of X and Y is drawn per item from a fixed seed, so it is not always v1 first.

## 2. Score each answer ON ITS OWN, then the pair

Read the question, then answer X, label it, then answer Y, label it. Do not compare them until
both have a label. One label per answer:

| Label | Meaning |
|---|---|
| **A** — full | every criterion addressed with grounded evidence, the right operation |
| **B** — honest partial | the answerable criteria addressed, the rest named as not assessable |
| **C** — correct decline | the building does not hold what the question needs, and the answer says so |
| **D** — false decline / silent partial | answerable but declined, or parts dropped without saying so |
| **E** — wrong | wrong entity, facet, operation or number |
| **F** — fabricated | a figure or fact the building's data does not support |

Where the item names criteria, also fill how many of them each answer covered with evidence.

Things to keep in mind:

- **Judge what the answer establishes, not how it looks.** v2's operation answers have a
  recognisable layout; the label is about the right facets, the right operation and grounded
  figures, not the table.
- **Readings move.** The two answers were captured on different days, so a "right now" figure may
  differ between them. Do not mark one wrong for that; judge each against its own data.
- **A provider-failure fallback** ("…couldn't summarise them … just now", "…able to generate an
  answer just now", "…language model … is not responding") is labelled as what the reader saw — D
  if the item was answerable. The sensitivity analysis removes these items separately.
- **Answerability** (FULL / PARTIAL / NONE) is already recorded per item in `LABELS.json`; you do
  not need to judge it, and you should not open that file before scoring either.

## 3. Count

```bash
python scripts/score_blinded.py --set eval/compound/T-REAL.jsonl --set eval/compound/T-REAL-SUPPLEMENT.jsonl --a v1 --b v2
python scripts/score_blinded.py --set eval/compound/T-CAT.jsonl --a v1 --b v2
```

The first is the pre-registered primary analysis (the two real sets pooled, n = 49); the script
also reports T-REAL alone (the sensitivity analysis) when run on that set by itself. It refuses an
unfinished sheet. Then `eval/compound/BEFORE_AFTER.md` is written from these counts — and only
these.
