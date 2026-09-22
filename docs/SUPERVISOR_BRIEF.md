# OntoSage — a one-page brief for a free question session

**Read this before asking the system anything.** It answers from one building's own records and live
readings, and it is honest about what it does not hold. It is strong on some question shapes and weak
on others, and it says which by declining rather than guessing. Measured on questions nobody had
tuned it on: **about three in four are answered well or declined honestly; about one in four
disappoints; about one in eleven is confidently wrong.** (Source: `docs/READINESS_2026-09-19.md` is check after every update.)

## Ask these — they work

| shape | example |
|---|---|
| A room or floor, and a quantity | "What is the CO2 level in room 5.01 right now?" · "Which floor is the warmest right now?" |
| A comparison of floors or weeks | "Compare the average CO2 on floor 1 versus floor 3" · "Compare this week's electricity use with last week" |
| A register, by record id | "Who owns CLN-0010?" · "What is the name of WS-28?" · "Which permits are open?" |
| "Which … are overdue / open / have no …" | "Which hazard controls are overdue for test?" · "Which departments have no out-of-hours route?" |
| Where something is | "What is the nearest accessible toilet to room 3.10?" · "Is there a muster point outside the building?" |
| Is a room ready or free | "Is Room 1.06 ready for my class?" · "Is Room 1.06 free for the next two hours?" |
| Something the building does not measure | "What is the radiation level in the atrium?" — it declines, says why, and says what it does measure |
| A fault report | "The toilet on floor 2 is leaking." — it files a report and says so |

## Expect these to disappoint

- **Long questions naming four or five things at once** ("which … and which … and where …"). It tends to
  answer one clause, or decline the whole.
- **Governance and assurance wording** ("are the records current, valid, correctly scoped and traceable?").
  The registers record status and dates, not judgement, and it will say so.
- **Predictions and "what would happen if".** It does not model the building; it declines.
- **A person's whereabouts or behaviour.** Refused for every role, by design.
- **Anything needing a fact the building has not recorded** (a defibrillator's position, a parking fee,
  refuge points). It says the fact is not recorded and does not guess. The checklist of what is missing is available to work ahead at   `docs/OWNER_FACTS_CHECKLIST.md`.

## Timing

Most answers take 10–50 seconds on the local model. A few take 60–160 seconds (weekly comparisons, full
reports, long register questions). That is the local model, not a hang. Wait for it.

## If an answer looks wrong

Ask it again in different words once. If it is still wrong, that is a real finding — note the exact
question and the answer. The system logs the route each answer took, so a wrong one can be traced.

## What it will never do

Say the data is anything other than the building's own readings; identify or track an individual; change a
physical system (it declines and lists the few setpoints a facility manager can approve); or state a
safety-critical fact it was not given.
