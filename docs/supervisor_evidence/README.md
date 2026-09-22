# OntoSage — evidence that the system answers, and where it does not

**Start here.** This folder is a record of the system being asked 26 questions on 21 September 2026
and answering them, captured as full-page screenshots of the real browser. It exists so that a claim
about what the system can do can be checked rather than taken on trust.

## What to read, in order

| file | what it is |
|---|---|
| **[INDEX.md](INDEX.md)** | The contents page: every question, its verdict, how long it took, and a link to its screenshot, with the answer text quoted so the pack can be read without opening 26 images. |
| **[screenshots/](screenshots/)** | One PNG per question, numbered to match the index. |
| [`../SUPERVISOR_BRIEF.md`](../SUPERVISOR_BRIEF.md) | The one-page brief this pack supports: which question shapes work, which disappoint, and what the system will never do. |
| `answers.jsonl` · `review.json` | The raw capture record and the hand-written verdicts, kept so the index can be regenerated and the judgements audited. |

## How it was produced

Each question was asked through Open WebUI in a **fresh chat**, signed in as `facility01` — a
facility-manager account, not an administrator, so nothing here is admin-only output. Both answer
caches were flushed first, so every answer is a first pass and none was served from cache. The
capture script waits for the whole answer before taking the shot and records whether it completed;
all 26 did.

To reproduce it:

```bash
python scripts/demo_prepare.py                                    # health, flush caches, warm the model
python scripts/capture_evidence_screenshots.py                    # ask, wait, screenshot
python scripts/build_evidence_index.py                            # rebuild INDEX.md
```

## What it shows

**23 of the 26 answer the question. 3 do not, and they are named at the top of the index.**

The pack deliberately includes two things a promotional pack would leave out.

**The questions the system declines.** Refusing to answer what it cannot ground is the behaviour
being claimed, so it has to be evidenced. Asked for a radiation level it does not measure, it says a
figure would be invented and lists what it does measure. Asked where a named person was yesterday,
it refuses for every role and offers the aggregate alternative. Asked for the open work orders and
which are overdue, it lists the nine open ones and then states plainly that the register holds no due
date, so "overdue" cannot be derived from it — answering half the question and saying why.

**The answers that came out wrong.** One is a routing failure: "where's the coolest place to work"
is a temperature question and the workspace register answers it. One declines correctly but leaks an
internal error string. One is more serious and is flagged in the index: the defibrillator answer
states positions as fact while the record behind it calls them "modelled". It is not to be relied on
until the building's owner confirms those positions.

A pack showing only the successes would not be evidence. The failures are what make the rest
checkable.

## Two caveats worth stating plainly

**Timings are the local model, not a hang.** Median 56 seconds, slowest 203. A few questions take
one to three minutes.

**This is one building on one day.** The pack shows that these 26 question shapes work; it is not a
measurement of how often an arbitrary question succeeds. That figure is measured separately, on
questions nobody tuned the system on, and is quoted in the brief.
