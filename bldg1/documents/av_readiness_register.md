---
record_type: av_readiness
owner: "Teaching and AV Support Lead"
authority: "School of Computer Science — Teaching Support"
source_system: "Teaching AV Readiness Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
simulated: true
tables:
  - name: "AV readiness register"
    maps_to: av_components
---

# Teaching AV Readiness Register — Abacws Building

_**Synthetic demonstration record** — fictional check history, not a live AV inventory._

## Why components are rows and readiness is computed

A room with a working projector, a working display and a dead microphone is not "mostly
ready" — it cannot run a lecture that needs amplification. **The audio path is a chain and
is recorded as one**: each component carries its own state and its own last check, and a
room's readiness for a given teaching format follows from the chain rather than from a
single flag someone set.

**`last_checked` and `evidence_ref` are both required.** "Checked" without a record is a
claim. These questions ask for evidence by name, and a room withheld from service on
somebody's recollection is the thing the team is trying to avoid.

## Teaching formats and what each needs

| format | needs |
|---|---|
| **Lecture** | Display + projector + room microphone + amplification |
| **Seminar** | Display only |
| **Hybrid** | Everything a lecture needs, plus camera and conferencing audio |
| **Practical** | Display + bench power; no amplification |

## AV readiness register

| component | name | room | kind | audio_path | supports_format | last_checked | evidence_ref | next_due | state | owner | note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| AV-106-DSP | Room 1.06 display | Room 1.06 — Computer Laboratory | Display | false | Lecture, Seminar, Hybrid, Practical | 2026-08-28 | AV-CHK-2026-0812 | 2026-11-28 | Ready | Teaching and AV Support Lead | |
| AV-106-PRJ | Room 1.06 projector | Room 1.06 — Computer Laboratory | Projector | false | Lecture, Hybrid | 2026-08-28 | AV-CHK-2026-0813 | 2026-11-28 | Ready | Teaching and AV Support Lead | |
| AV-106-MIC | Room 1.06 room microphone | Room 1.06 — Computer Laboratory | Microphone | true | Lecture, Hybrid | 2026-08-28 | AV-CHK-2026-0814 | 2026-11-28 | Ready | Teaching and AV Support Lead | |
| AV-106-AMP | Room 1.06 amplifier | Room 1.06 — Computer Laboratory | Amplifier | true | Lecture, Hybrid | 2026-08-28 | AV-CHK-2026-0815 | 2026-11-28 | Ready | Teaching and AV Support Lead | |
| AV-106-LOOP | Room 1.06 hearing loop | Room 1.06 — Computer Laboratory | Hearing loop | true | Lecture, Hybrid | | | 2026-09-10 | Unevidenced | Teaching and AV Support Lead | Installed 2026-04; never tested. APR-032 is conditional on this test. |
| AV-106-CAM | Room 1.06 camera | Room 1.06 — Computer Laboratory | Camera | false | Hybrid | 2026-08-28 | AV-CHK-2026-0816 | 2026-11-28 | Ready | Teaching and AV Support Lead | |
| AV-104-DSP | Atrium display | Room 1.04 — Common Area / Atrium | Display | false | Seminar | 2026-08-14 | AV-CHK-2026-0790 | 2026-11-14 | Ready | Teaching and AV Support Lead | |
| AV-104-MIC | Atrium roving microphone | Room 1.04 — Common Area / Atrium | Microphone | true | Lecture | 2026-09-01 | AV-CHK-2026-0821 | 2026-12-01 | Ready | Teaching and AV Support Lead | |
| AV-104-AMP | Atrium amplifier | Room 1.04 — Common Area / Atrium | Amplifier | true | Lecture | 2026-09-01 | AV-CHK-2026-0822 | 2026-12-01 | Ready | Teaching and AV Support Lead | |
| AV-104-LOOP | Atrium hearing loop | Room 1.04 — Common Area / Atrium | Hearing loop | true | Lecture | 2026-09-01 | AV-CHK-2026-0823 | 2026-12-01 | Ready | Teaching and AV Support Lead | Front two rows only. |
| AV-201-DSP | Room 2.01 display | Room 2.01 — Research Laboratory | Display | false | Seminar, Practical | 2026-07-30 | AV-CHK-2026-0742 | 2026-10-30 | Ready | Teaching and AV Support Lead | |
| AV-201-PRJ | Room 2.01 projector | Room 2.01 — Research Laboratory | Projector | false | Lecture | 2026-09-02 | AV-CHK-2026-0830 | 2026-12-02 | Failed | Teaching and AV Support Lead | Lamp failure during maintenance 2026-09-02; replacement on order. |
| AV-201-MIC | Room 2.01 microphone | Room 2.01 — Research Laboratory | Microphone | true | Lecture | 2026-07-30 | AV-CHK-2026-0743 | 2026-10-30 | Ready | Teaching and AV Support Lead | |
| AV-202-DSP | Room 2.02 display | Room 2.02 — Research Laboratory | Display | false | Seminar, Practical | 2026-08-05 | AV-CHK-2026-0761 | 2026-11-05 | Ready | Teaching and AV Support Lead | |
| AV-202-MIC | Room 2.02 microphone | Room 2.02 — Research Laboratory | Microphone | true | Lecture | 2026-08-05 | AV-CHK-2026-0762 | 2026-11-05 | Degraded | Teaching and AV Support Lead | Intermittent dropout reported 2026-09-01; usable for seminar, not for a lecture. |
| AV-301-DSP | Room 3.01 display | Room 3.01 — Research Laboratory | Display | false | Seminar, Practical | 2026-08-19 | AV-CHK-2026-0801 | 2026-11-19 | Ready | Teaching and AV Support Lead | |
| AV-301-PRJ | Room 3.01 projector | Room 3.01 — Research Laboratory | Projector | false | Lecture | 2026-08-19 | AV-CHK-2026-0802 | 2026-11-19 | Ready | Teaching and AV Support Lead | |
| AV-301-MIC | Room 3.01 microphone | Room 3.01 — Research Laboratory | Microphone | true | Lecture | 2026-08-19 | AV-CHK-2026-0803 | 2026-11-19 | Ready | Teaching and AV Support Lead | |
| AV-301-AMP | Room 3.01 amplifier | Room 3.01 — Research Laboratory | Amplifier | true | Lecture | 2026-08-19 | AV-CHK-2026-0804 | 2026-11-19 | Ready | Teaching and AV Support Lead | |
| AV-401-DSP | Room 4.01 display | Room 4.01 — Research Laboratory | Display | false | Seminar, Practical | 2026-06-11 | AV-CHK-2026-0655 | 2026-09-11 | Ready | Teaching and AV Support Lead | Check due within a week. |
| AV-401-MIC | Room 4.01 microphone | Room 4.01 — Research Laboratory | Microphone | true | Lecture | 2026-06-11 | AV-CHK-2026-0656 | 2026-09-11 | Ready | Teaching and AV Support Lead | Check due within a week. |
| AV-504-DSP | Room 5.04 display | Room 5.04 — Academic Office | Display | false | Seminar | 2026-08-22 | AV-CHK-2026-0808 | 2026-11-22 | Ready | Teaching and AV Support Lead | |

## Rooms and what they can run today

- **Room 1.06** — lecture, seminar, hybrid and practical all ready, **except** that the
  hearing loop has never been tested. A lecture can run; a lecture with a declared
  hearing-loop requirement cannot be evidenced.
- **Room 1.04 (Atrium)** — lecture and seminar ready, hearing loop evidenced.
- **Room 2.01** — seminar and practical ready. **Lecture withheld:** the projector failed
  during maintenance on 2026-09-02 and there is no post-work evidence to return it to
  service.
- **Room 2.02** — seminar ready. **Lecture not supported:** the microphone is degraded, so
  the audio path is broken.
- **Room 3.01** — everything ready and evidenced.
- **Room 4.01** — ready, but both checks fall due on 2026-09-11.
