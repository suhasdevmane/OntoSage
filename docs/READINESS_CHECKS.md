# Readiness checks — is this space ready for what happens next?

A readiness check answers one question about one room, before it is used:

> *"Is Room 4.02 ready for my class?"*

It is deliberately **not** a status dump. Every line carries **where the fact came from and
when it was established**, what could not be assessed is listed as prominently as what
could, and a room with nothing recorded against it is never reported as ready.

```
**Room 4.02 — Computer Laboratory — not ready**
Foundations of Machine Learning at 14:00, starting in about 30 minutes.

**Needs attention before the session:**
- Hearing loop: **unevidenced** _(AV readiness register · date not recorded)_

**Checked and in order:**
- Projector: **ready** _(AV readiness register · 2026-08-28)_
- Network: **strong** _(workspace profile (surveyed) · 2026-09-01)_
- Setup allowance: **8.0 min** _(workspace profile · 2026-09-01)_

**Not known:**
- No workspace profile names Room 4.02.

_Compiled 2026-09-05T13:30 from the building's own records._
```

## The three properties that make it a check

**A source and a date on every line.** *"The projector works"* is worthless without
*"checked 2026-08-28"*. A line whose age cannot be established says **date not recorded**
rather than reading as current.

**The unknowns are as prominent as the facts.** A room with no AV record is not a room with
working AV. A check that silently omits what it could not assess invites exactly that
reading, and contract 4 applies to a notification as much as to an answer.

**Three verdicts, not two.** `ready` · `not ready` · `no blockers found, with gaps` ·
`nothing recorded`. "Ready" and "not ready" cannot express the common case — nothing broken
and nothing checked either — and a room reported ready on no evidence is the failure this
feature exists to avoid.

## Where the facts come from

| source | contributes |
|---|---|
| `ontosage:TimetabledSession` | which session is next, where, and when |
| `ontosage:AVReadiness` | each component's state, its last check date, its evidence |
| `ontosage:WorkspaceProfile` | surveyed network, power, setup allowance |

Every one is **optional**. A building with no AV register gets a check without AV lines and
an explicit note saying so — not an error, and not a silent gap.

## Asking for one

Ask in plain English. The routing recognises *"is X ready for my class"*, *"readiness
check"*, *"before my seminar"*, *"what should I know before teaching in X"*.

- **Naming a room** checks that room.
- **Naming none** uses the next session in the building's own timetable.
- **With no session scheduled** it asks which space you mean, rather than guessing.

## Scheduling it

Off by default. A building that upgrades must not start receiving unsolicited messages.

```bash
READINESS_CHECK_INTERVAL_SECS=300   # how often to look for sessions entering the window
READINESS_LEAD_MINUTES=30           # how far ahead of a session to send (default 30)
```

Checks dispatch through the existing notification channels in `input/<id>/channels.yaml`
(log, webhook, smtp), with severity `warning` when there is a blocker and `info` otherwise.
**Once per session, not once per sweep** — a five-minute interval against a thirty-minute
lead sends one message, not six. An alert that repeats is an alert people learn to ignore.

Leaving the schedule off costs nothing but the timing: the check stays available on demand.

## Building-agnostic

Nothing in `orchestrator/services/readiness_check.py` names a building, a room or a module,
and a test asserts it. Rooms are matched on the identifier the building's **own** labels
carry, falling back to the whole name — so a building numbering rooms `4.02` and one naming
them `Atrium` both work, with no configuration.

## Extending it

The composer builds a list of `ReadinessFact(label, state, source, observed, blocking)`. To
add a source, query the register and append facts — a fact with `blocking=True` moves the
verdict to *not ready* and is rendered first. Prefer adding an **unknown** over omitting a
source that could not be read: an absent line is indistinguishable from a passing one.
