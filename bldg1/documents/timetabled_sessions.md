---
record_type: timetabled_session
owner: "Timetabling Officer"
authority: "Cardiff University Registry - Timetabling"
source_system: "Teaching Timetable"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
simulated: true
tables:
  - name: "Timetabled session register"
    maps_to: timetabled_sessions
---

# Timetabled Session Register - Abacws Building

_**Synthetic demonstration record** - a generated teaching pattern, not a live timetable export._

## Why this register exists

`ontosage:TimetabledSession` was declared in the ontology, given lay terms, and had **zero
instances** - while `input/bldg1_timetable.csv` sat in the same building folder holding 675
real sessions across 44 rooms. The feed meant to load them has never produced a row: the
events store holds 64,738 rows across anomaly, booking, access, workorder and asset_outage,
and not one session among them.

So the building held the timetable, declared the concept, and could answer nothing about
either. This is the third register in this session blocked by a missing mapping rather than
by missing data, which is worth saying plainly: the Record Document standard is three files,
and the file that goes missing is never the data.

**A session is not a booking.** `ontosage:Booking` is a separate class and stays separate. A
timetable says what the institution has **planned**; a booking says what somebody
**reserved**. Where the two disagree an answer has to report the disagreement rather than
quietly prefer one, and that is only possible while they are two registers.

Every room is named by the label the building's own graph carries, not by the bare
identifier the CSV uses, so a session and a room question resolve to the same place.

## Timetabled session register

| code | module | room | floor | session_date | weekday | starts_at | ends_at | duration_minutes | session_kind | status |
|---|---|---|---|---|---|---|---|---|---|---|
| TS-0001 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-07-27 | Monday | 09:00 | 11:00 | 120 | seminar | Completed |
| TS-0002 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-07-27 | Monday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0003 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-07-27 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0004 | Applied Software Engineering | Room 5.03 — Research Laboratory | 5 | 2026-07-27 | Monday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0005 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-07-27 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0006 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-07-27 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0007 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-07-27 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0008 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-07-27 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0009 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-07-27 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0010 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-07-27 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0011 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-07-27 | Monday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0012 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-07-27 | Monday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0013 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-07-27 | Monday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0014 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-07-27 | Monday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0015 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-07-27 | Monday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0016 | Applied Software Engineering | Room 3.04 — Research Laboratory | 3 | 2026-07-27 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0017 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-07-27 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0018 | Introduction to Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-07-27 | Monday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0019 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-07-27 | Monday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0020 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-07-28 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0021 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-07-28 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0022 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-07-28 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0023 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-07-28 | Tuesday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0024 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-07-28 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0025 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-07-28 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0026 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-07-28 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0027 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-07-28 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0028 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-07-28 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0029 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-07-28 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0030 | Advanced Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-07-28 | Tuesday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0031 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-07-28 | Tuesday | 15:00 | 17:00 | 120 | seminar | Completed |
| TS-0032 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-07-28 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0033 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-07-28 | Tuesday | 16:00 | 18:00 | 120 | seminar | Completed |
| TS-0034 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-07-28 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0035 | Applied Cyber Security | Room 5.17 — Meeting Room | 5 | 2026-07-28 | Tuesday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-0036 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-07-29 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Completed |
| TS-0037 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-07-29 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0038 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-07-29 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0039 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-07-29 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0040 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-07-29 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0041 | Foundations of Machine Learning | Room 4.56 — Research Laboratory | 4 | 2026-07-29 | Wednesday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0042 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-07-29 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0043 | Research Methods in Cyber Security | Room 2.53 — Research Laboratory | 2 | 2026-07-29 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0044 | Introduction to Cyber Security | Room 3.03 — Research Laboratory | 3 | 2026-07-29 | Wednesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0045 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-07-29 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0046 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-07-29 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Completed |
| TS-0047 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-07-29 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0048 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-07-30 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Completed |
| TS-0049 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-07-30 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0050 | Advanced Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-07-30 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0051 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-07-30 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0052 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-07-30 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0053 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-07-30 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0054 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-07-30 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Completed |
| TS-0055 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-07-30 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0056 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-07-30 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0057 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-07-30 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0058 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-07-30 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0059 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-07-30 | Thursday | 13:00 | 14:00 | 60 | small-group session | Completed |
| TS-0060 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-07-30 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0061 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-07-30 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0062 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-07-30 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0063 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-07-30 | Thursday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0064 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-07-30 | Thursday | 14:00 | 16:00 | 120 | seminar | Completed |
| TS-0065 | Introduction to Computer Science | Room 4.01 — Research Laboratory | 4 | 2026-07-30 | Thursday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0066 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-07-30 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0067 | Applied Cyber Security | Room 5.53 — Research Laboratory | 5 | 2026-07-30 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0068 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-07-31 | Friday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0069 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-07-31 | Friday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0070 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-07-31 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0071 | Foundations of Human-Computer Interaction | Room 4.19 — Research Laboratory | 4 | 2026-07-31 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0072 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-07-31 | Friday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0073 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-07-31 | Friday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0074 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-07-31 | Friday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0075 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-07-31 | Friday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0076 | Research Methods in Cyber Security | Room 2.17 — Research Laboratory | 2 | 2026-07-31 | Friday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0077 | Research Methods in Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-07-31 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0078 | Introduction to Computer Science | Room 3.57 — Research Laboratory | 3 | 2026-07-31 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0079 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-07-31 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0080 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-07-31 | Friday | 15:00 | 17:00 | 120 | small-group session | Completed |
| TS-0081 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-07-31 | Friday | 16:00 | 18:00 | 120 | computer lab session | Completed |
| TS-0082 | Research Methods in Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-07-31 | Friday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0083 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-07-31 | Friday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0084 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-08-03 | Monday | 09:00 | 11:00 | 120 | seminar | Completed |
| TS-0085 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-08-03 | Monday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0086 | Foundations of Data Analysis | Room 3.16 — Meeting Room | 3 | 2026-08-03 | Monday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0087 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-08-03 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0088 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-08-03 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0089 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-08-03 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0090 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-08-03 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0091 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-08-03 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0092 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-08-03 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0093 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-08-03 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0094 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-08-03 | Monday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0095 | Introduction to Software Engineering | Room 4.13 — Seminar Room | 4 | 2026-08-03 | Monday | 13:00 | 14:00 | 60 | seminar | Completed |
| TS-0096 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-08-03 | Monday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0097 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-08-03 | Monday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0098 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-08-03 | Monday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0099 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-08-03 | Monday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0100 | Applied Software Engineering | Room 3.04 — Research Laboratory | 3 | 2026-08-03 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0101 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-08-03 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0102 | Introduction to Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-08-03 | Monday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0103 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-08-03 | Monday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0104 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-08-04 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0105 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-08-04 | Tuesday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0106 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-08-04 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0107 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-08-04 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0108 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-08-04 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0109 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-08-04 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0110 | Advanced Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-08-04 | Tuesday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0111 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-08-04 | Tuesday | 15:00 | 17:00 | 120 | seminar | Completed |
| TS-0112 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-08-04 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0113 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-08-04 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0114 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-08-04 | Tuesday | 16:00 | 18:00 | 120 | seminar | Completed |
| TS-0115 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-08-04 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0116 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-08-05 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Completed |
| TS-0117 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-08-05 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0118 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-08-05 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0119 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-08-05 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0120 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-08-05 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0121 | Introduction to Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-08-05 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0122 | Foundations of Machine Learning | Room 4.56 — Research Laboratory | 4 | 2026-08-05 | Wednesday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0123 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-08-05 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Completed |
| TS-0124 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-08-05 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0125 | Research Methods in Cyber Security | Room 2.53 — Research Laboratory | 2 | 2026-08-05 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0126 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-08-05 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0127 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-08-05 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Completed |
| TS-0128 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-08-06 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Completed |
| TS-0129 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-08-06 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0130 | Advanced Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-08-06 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0131 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-08-06 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0132 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-08-06 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0133 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-08-06 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0134 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-08-06 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Completed |
| TS-0135 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-08-06 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0136 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-08-06 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0137 | Applied Computer Science | Room 4.05 — Computer Laboratory | 4 | 2026-08-06 | Thursday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0138 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-08-06 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0139 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-08-06 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0140 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-08-06 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0141 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-08-06 | Thursday | 13:00 | 14:00 | 60 | small-group session | Completed |
| TS-0142 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-08-06 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0143 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-08-06 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0144 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-08-06 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0145 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-08-06 | Thursday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0146 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-08-06 | Thursday | 14:00 | 16:00 | 120 | seminar | Completed |
| TS-0147 | Introduction to Computer Science | Room 4.01 — Research Laboratory | 4 | 2026-08-06 | Thursday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0148 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-08-06 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0149 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-08-07 | Friday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0150 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-08-07 | Friday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0151 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-08-07 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0152 | Foundations of Human-Computer Interaction | Room 4.19 — Research Laboratory | 4 | 2026-08-07 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0153 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-08-07 | Friday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0154 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-08-07 | Friday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0155 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-08-07 | Friday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0156 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-08-07 | Friday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0157 | Research Methods in Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-08-07 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0158 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-08-07 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0159 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-08-07 | Friday | 15:00 | 17:00 | 120 | small-group session | Completed |
| TS-0160 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-08-07 | Friday | 16:00 | 18:00 | 120 | computer lab session | Completed |
| TS-0161 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-08-07 | Friday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-0162 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-08-07 | Friday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0163 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-08-10 | Monday | 09:00 | 11:00 | 120 | seminar | Completed |
| TS-0164 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-08-10 | Monday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0165 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-08-10 | Monday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0166 | Foundations of Data Analysis | Room 3.16 — Meeting Room | 3 | 2026-08-10 | Monday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0167 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-08-10 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0168 | Applied Software Engineering | Room 5.03 — Research Laboratory | 5 | 2026-08-10 | Monday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0169 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-08-10 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0170 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-08-10 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0171 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-08-10 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0172 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-08-10 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0173 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-08-10 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0174 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-08-10 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0175 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-08-10 | Monday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0176 | Introduction to Software Engineering | Room 4.13 — Seminar Room | 4 | 2026-08-10 | Monday | 13:00 | 14:00 | 60 | seminar | Completed |
| TS-0177 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-08-10 | Monday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0178 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-08-10 | Monday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0179 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-08-10 | Monday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0180 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-08-10 | Monday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0181 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-08-10 | Monday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0182 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-08-10 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0183 | Introduction to Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-08-10 | Monday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0184 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-08-10 | Monday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0185 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-08-11 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0186 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-08-11 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0187 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-08-11 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0188 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-08-11 | Tuesday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0189 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-08-11 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0190 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-08-11 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0191 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-08-11 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0192 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-08-11 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0193 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-08-11 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0194 | Advanced Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-08-11 | Tuesday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0195 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-08-11 | Tuesday | 15:00 | 17:00 | 120 | seminar | Completed |
| TS-0196 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-08-11 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0197 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-08-11 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0198 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-08-11 | Tuesday | 16:00 | 18:00 | 120 | seminar | Completed |
| TS-0199 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-08-11 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0200 | Applied Cyber Security | Room 5.17 — Meeting Room | 5 | 2026-08-11 | Tuesday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-0201 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-08-12 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Completed |
| TS-0202 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-08-12 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0203 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-08-12 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0204 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-08-12 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0205 | Introduction to Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-08-12 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0206 | Foundations of Machine Learning | Room 4.56 — Research Laboratory | 4 | 2026-08-12 | Wednesday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0207 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-08-12 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Completed |
| TS-0208 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-08-12 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0209 | Research Methods in Cyber Security | Room 2.53 — Research Laboratory | 2 | 2026-08-12 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0210 | Introduction to Cyber Security | Room 3.03 — Research Laboratory | 3 | 2026-08-12 | Wednesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0211 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-08-12 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0212 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-08-12 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Completed |
| TS-0213 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-08-12 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0214 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-08-13 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Completed |
| TS-0215 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-08-13 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0216 | Advanced Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-08-13 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0217 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-08-13 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0218 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-08-13 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0219 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-08-13 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0220 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-08-13 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Completed |
| TS-0221 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-08-13 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0222 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-08-13 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0223 | Applied Computer Science | Room 3.58 — Research Laboratory | 3 | 2026-08-13 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0224 | Applied Computer Science | Room 4.05 — Computer Laboratory | 4 | 2026-08-13 | Thursday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0225 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-08-13 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0226 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-08-13 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0227 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-08-13 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0228 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-08-13 | Thursday | 13:00 | 14:00 | 60 | small-group session | Completed |
| TS-0229 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-08-13 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0230 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-08-13 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0231 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-08-13 | Thursday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0232 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-08-13 | Thursday | 14:00 | 16:00 | 120 | seminar | Completed |
| TS-0233 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-08-13 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0234 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-08-14 | Friday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0235 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-08-14 | Friday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0236 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-08-14 | Friday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0237 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-08-14 | Friday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0238 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-08-14 | Friday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0239 | Research Methods in Cyber Security | Room 2.17 — Research Laboratory | 2 | 2026-08-14 | Friday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0240 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-08-14 | Friday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0241 | Research Methods in Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-08-14 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0242 | Introduction to Computer Science | Room 3.57 — Research Laboratory | 3 | 2026-08-14 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0243 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-08-14 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0244 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-08-14 | Friday | 15:00 | 17:00 | 120 | small-group session | Completed |
| TS-0245 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-08-14 | Friday | 16:00 | 18:00 | 120 | computer lab session | Completed |
| TS-0246 | Research Methods in Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-08-14 | Friday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0247 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-08-14 | Friday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-0248 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-08-14 | Friday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0249 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-08-17 | Monday | 09:00 | 11:00 | 120 | seminar | Completed |
| TS-0250 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-08-17 | Monday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0251 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-08-17 | Monday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0252 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-08-17 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0253 | Applied Software Engineering | Room 5.03 — Research Laboratory | 5 | 2026-08-17 | Monday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0254 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-08-17 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0255 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-08-17 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0256 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-08-17 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0257 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-08-17 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0258 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-08-17 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0259 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-08-17 | Monday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0260 | Introduction to Software Engineering | Room 4.13 — Seminar Room | 4 | 2026-08-17 | Monday | 13:00 | 14:00 | 60 | seminar | Completed |
| TS-0261 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-08-17 | Monday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0262 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-08-17 | Monday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0263 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-08-17 | Monday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0264 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-08-17 | Monday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0265 | Applied Software Engineering | Room 3.04 — Research Laboratory | 3 | 2026-08-17 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0266 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-08-17 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0267 | Introduction to Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-08-17 | Monday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0268 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-08-17 | Monday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0269 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-08-18 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0270 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-08-18 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0271 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-08-18 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0272 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-08-18 | Tuesday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0273 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-08-18 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0274 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-08-18 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0275 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-08-18 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0276 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-08-18 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0277 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-08-18 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0278 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-08-18 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0279 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-08-18 | Tuesday | 15:00 | 17:00 | 120 | seminar | Completed |
| TS-0280 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-08-18 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0281 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-08-18 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0282 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-08-19 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Completed |
| TS-0283 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-08-19 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0284 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-08-19 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0285 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-08-19 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0286 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-08-19 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0287 | Introduction to Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-08-19 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0288 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-08-19 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Completed |
| TS-0289 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-08-19 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0290 | Research Methods in Cyber Security | Room 2.53 — Research Laboratory | 2 | 2026-08-19 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0291 | Introduction to Cyber Security | Room 3.03 — Research Laboratory | 3 | 2026-08-19 | Wednesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0292 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-08-19 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0293 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-08-19 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Completed |
| TS-0294 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-08-19 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0295 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-08-20 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Completed |
| TS-0296 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-08-20 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0297 | Advanced Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-08-20 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0298 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-08-20 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0299 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-08-20 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0300 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-08-20 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0301 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-08-20 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Completed |
| TS-0302 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-08-20 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0303 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-08-20 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0304 | Applied Computer Science | Room 3.58 — Research Laboratory | 3 | 2026-08-20 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0305 | Applied Computer Science | Room 4.05 — Computer Laboratory | 4 | 2026-08-20 | Thursday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0306 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-08-20 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0307 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-08-20 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0308 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-08-20 | Thursday | 13:00 | 14:00 | 60 | small-group session | Completed |
| TS-0309 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-08-20 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0310 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-08-20 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0311 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-08-20 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0312 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-08-20 | Thursday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0313 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-08-20 | Thursday | 14:00 | 16:00 | 120 | seminar | Completed |
| TS-0314 | Introduction to Computer Science | Room 4.01 — Research Laboratory | 4 | 2026-08-20 | Thursday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0315 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-08-20 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0316 | Applied Cyber Security | Room 5.53 — Research Laboratory | 5 | 2026-08-20 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0317 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-08-21 | Friday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0318 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-08-21 | Friday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0319 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-08-21 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0320 | Foundations of Human-Computer Interaction | Room 4.19 — Research Laboratory | 4 | 2026-08-21 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0321 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-08-21 | Friday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0322 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-08-21 | Friday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0323 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-08-21 | Friday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0324 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-08-21 | Friday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0325 | Research Methods in Cyber Security | Room 2.17 — Research Laboratory | 2 | 2026-08-21 | Friday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0326 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-08-21 | Friday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0327 | Introduction to Computer Science | Room 3.57 — Research Laboratory | 3 | 2026-08-21 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0328 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-08-21 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0329 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-08-21 | Friday | 15:00 | 17:00 | 120 | small-group session | Completed |
| TS-0330 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-08-21 | Friday | 16:00 | 18:00 | 120 | computer lab session | Completed |
| TS-0331 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-08-21 | Friday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-0332 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-08-21 | Friday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0333 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-08-24 | Monday | 09:00 | 11:00 | 120 | seminar | Completed |
| TS-0334 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-08-24 | Monday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0335 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-08-24 | Monday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0336 | Foundations of Data Analysis | Room 3.16 — Meeting Room | 3 | 2026-08-24 | Monday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0337 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-08-24 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0338 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-08-24 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0339 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-08-24 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0340 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-08-24 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0341 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-08-24 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0342 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-08-24 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0343 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-08-24 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0344 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-08-24 | Monday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0345 | Introduction to Software Engineering | Room 4.13 — Seminar Room | 4 | 2026-08-24 | Monday | 13:00 | 14:00 | 60 | seminar | Completed |
| TS-0346 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-08-24 | Monday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0347 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-08-24 | Monday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0348 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-08-24 | Monday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0349 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-08-24 | Monday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0350 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-08-24 | Monday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0351 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-08-24 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0352 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-08-25 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0353 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-08-25 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0354 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-08-25 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0355 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-08-25 | Tuesday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0356 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-08-25 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0357 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-08-25 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0358 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-08-25 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0359 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-08-25 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0360 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-08-25 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0361 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-08-25 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0362 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-08-25 | Tuesday | 15:00 | 17:00 | 120 | seminar | Completed |
| TS-0363 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-08-25 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0364 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-08-25 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0365 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-08-25 | Tuesday | 16:00 | 18:00 | 120 | seminar | Completed |
| TS-0366 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-08-25 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0367 | Applied Cyber Security | Room 5.17 — Meeting Room | 5 | 2026-08-25 | Tuesday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-0368 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-08-26 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Completed |
| TS-0369 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-08-26 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0370 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-08-26 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0371 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-08-26 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0372 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-08-26 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0373 | Introduction to Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-08-26 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0374 | Foundations of Machine Learning | Room 4.56 — Research Laboratory | 4 | 2026-08-26 | Wednesday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0375 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-08-26 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Completed |
| TS-0376 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-08-26 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0377 | Research Methods in Cyber Security | Room 2.53 — Research Laboratory | 2 | 2026-08-26 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0378 | Introduction to Cyber Security | Room 3.03 — Research Laboratory | 3 | 2026-08-26 | Wednesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0379 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-08-26 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0380 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-08-26 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Completed |
| TS-0381 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-08-26 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0382 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-08-27 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Completed |
| TS-0383 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-08-27 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0384 | Advanced Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-08-27 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0385 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-08-27 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0386 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-08-27 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0387 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-08-27 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0388 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-08-27 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Completed |
| TS-0389 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-08-27 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0390 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-08-27 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0391 | Applied Computer Science | Room 3.58 — Research Laboratory | 3 | 2026-08-27 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0392 | Applied Computer Science | Room 4.05 — Computer Laboratory | 4 | 2026-08-27 | Thursday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0393 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-08-27 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0394 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-08-27 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0395 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-08-27 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0396 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-08-27 | Thursday | 13:00 | 14:00 | 60 | small-group session | Completed |
| TS-0397 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-08-27 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0398 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-08-27 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0399 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-08-27 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0400 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-08-27 | Thursday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0401 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-08-27 | Thursday | 14:00 | 16:00 | 120 | seminar | Completed |
| TS-0402 | Introduction to Computer Science | Room 4.01 — Research Laboratory | 4 | 2026-08-27 | Thursday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0403 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-08-27 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0404 | Applied Cyber Security | Room 5.53 — Research Laboratory | 5 | 2026-08-27 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0405 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-08-28 | Friday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0406 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-08-28 | Friday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0407 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-08-28 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0408 | Foundations of Human-Computer Interaction | Room 4.19 — Research Laboratory | 4 | 2026-08-28 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0409 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-08-28 | Friday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0410 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-08-28 | Friday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0411 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-08-28 | Friday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0412 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-08-28 | Friday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0413 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-08-28 | Friday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0414 | Research Methods in Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-08-28 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0415 | Introduction to Computer Science | Room 3.57 — Research Laboratory | 3 | 2026-08-28 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0416 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-08-28 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0417 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-08-28 | Friday | 15:00 | 17:00 | 120 | small-group session | Completed |
| TS-0418 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-08-28 | Friday | 16:00 | 18:00 | 120 | computer lab session | Completed |
| TS-0419 | Research Methods in Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-08-28 | Friday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0420 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-08-28 | Friday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-0421 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-08-28 | Friday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0422 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-08-31 | Monday | 09:00 | 11:00 | 120 | seminar | Completed |
| TS-0423 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-08-31 | Monday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0424 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-08-31 | Monday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0425 | Foundations of Data Analysis | Room 3.16 — Meeting Room | 3 | 2026-08-31 | Monday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0426 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-08-31 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0427 | Applied Software Engineering | Room 5.03 — Research Laboratory | 5 | 2026-08-31 | Monday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0428 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-08-31 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0429 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-08-31 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0430 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-08-31 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0431 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-08-31 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0432 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-08-31 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0433 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-08-31 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0434 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-08-31 | Monday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0435 | Introduction to Software Engineering | Room 4.13 — Seminar Room | 4 | 2026-08-31 | Monday | 13:00 | 14:00 | 60 | seminar | Completed |
| TS-0436 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-08-31 | Monday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0437 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-08-31 | Monday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0438 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-08-31 | Monday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0439 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-08-31 | Monday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0440 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-08-31 | Monday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0441 | Applied Software Engineering | Room 3.04 — Research Laboratory | 3 | 2026-08-31 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0442 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-08-31 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0443 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-08-31 | Monday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0444 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-09-01 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0445 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-09-01 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0446 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-09-01 | Tuesday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0447 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-09-01 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0448 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-09-01 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0449 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-09-01 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0450 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-09-01 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0451 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-09-01 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0452 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-09-01 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0453 | Advanced Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-09-01 | Tuesday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0454 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-09-01 | Tuesday | 15:00 | 17:00 | 120 | seminar | Completed |
| TS-0455 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-09-01 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0456 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-09-01 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0457 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-09-01 | Tuesday | 16:00 | 18:00 | 120 | seminar | Completed |
| TS-0458 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-09-01 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0459 | Applied Cyber Security | Room 5.17 — Meeting Room | 5 | 2026-09-01 | Tuesday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-0460 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-09-02 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Completed |
| TS-0461 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-09-02 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0462 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-09-02 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0463 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-09-02 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0464 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-09-02 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0465 | Foundations of Machine Learning | Room 4.56 — Research Laboratory | 4 | 2026-09-02 | Wednesday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0466 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-09-02 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Completed |
| TS-0467 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-09-02 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0468 | Research Methods in Cyber Security | Room 2.53 — Research Laboratory | 2 | 2026-09-02 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0469 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-09-02 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0470 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-09-02 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Completed |
| TS-0471 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-09-02 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0472 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-09-03 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Completed |
| TS-0473 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-09-03 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0474 | Advanced Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-09-03 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0475 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-09-03 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0476 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-09-03 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0477 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-09-03 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0478 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-09-03 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Completed |
| TS-0479 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-09-03 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0480 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-09-03 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0481 | Applied Computer Science | Room 3.58 — Research Laboratory | 3 | 2026-09-03 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0482 | Applied Computer Science | Room 4.05 — Computer Laboratory | 4 | 2026-09-03 | Thursday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0483 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-09-03 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0484 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-09-03 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0485 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-09-03 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0486 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-09-03 | Thursday | 13:00 | 14:00 | 60 | small-group session | Completed |
| TS-0487 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-09-03 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0488 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-09-03 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0489 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-09-03 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0490 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-09-03 | Thursday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0491 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-09-03 | Thursday | 14:00 | 16:00 | 120 | seminar | Completed |
| TS-0492 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-09-03 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0493 | Applied Cyber Security | Room 5.53 — Research Laboratory | 5 | 2026-09-03 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0494 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-09-04 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0495 | Foundations of Human-Computer Interaction | Room 4.19 — Research Laboratory | 4 | 2026-09-04 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0496 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-09-04 | Friday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0497 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-09-04 | Friday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0498 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-09-04 | Friday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0499 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-09-04 | Friday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0500 | Research Methods in Cyber Security | Room 2.17 — Research Laboratory | 2 | 2026-09-04 | Friday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0501 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-09-04 | Friday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0502 | Introduction to Computer Science | Room 3.57 — Research Laboratory | 3 | 2026-09-04 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0503 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-09-04 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0504 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-09-04 | Friday | 15:00 | 17:00 | 120 | small-group session | Completed |
| TS-0505 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-09-04 | Friday | 16:00 | 18:00 | 120 | computer lab session | Completed |
| TS-0506 | Research Methods in Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-09-04 | Friday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0507 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-09-04 | Friday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-0508 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-09-07 | Monday | 09:00 | 11:00 | 120 | seminar | Scheduled |
| TS-0509 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-09-07 | Monday | 09:00 | 10:00 | 60 | laboratory session | Scheduled |
| TS-0510 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-09-07 | Monday | 10:00 | 12:00 | 120 | seminar | Scheduled |
| TS-0511 | Foundations of Data Analysis | Room 3.16 — Meeting Room | 3 | 2026-09-07 | Monday | 10:00 | 12:00 | 120 | small-group session | Scheduled |
| TS-0512 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-09-07 | Monday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-0513 | Applied Software Engineering | Room 5.03 — Research Laboratory | 5 | 2026-09-07 | Monday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-0514 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-09-07 | Monday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-0515 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-09-07 | Monday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-0516 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-09-07 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-0517 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-09-07 | Monday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-0518 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-09-07 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-0519 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-09-07 | Monday | 13:00 | 15:00 | 120 | seminar | Scheduled |
| TS-0520 | Introduction to Software Engineering | Room 4.13 — Seminar Room | 4 | 2026-09-07 | Monday | 13:00 | 14:00 | 60 | seminar | Scheduled |
| TS-0521 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-09-07 | Monday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-0522 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-09-07 | Monday | 14:00 | 15:00 | 60 | small-group session | Scheduled |
| TS-0523 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-09-07 | Monday | 14:00 | 15:00 | 60 | laboratory session | Scheduled |
| TS-0524 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-09-07 | Monday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-0525 | Applied Software Engineering | Room 3.04 — Research Laboratory | 3 | 2026-09-07 | Monday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-0526 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-09-07 | Monday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-0527 | Introduction to Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-09-07 | Monday | 16:00 | 17:00 | 60 | laboratory session | Scheduled |
| TS-0528 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-09-07 | Monday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-0529 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-09-08 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-0530 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-09-08 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-0531 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-09-08 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Scheduled |
| TS-0532 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-09-08 | Tuesday | 10:00 | 12:00 | 120 | seminar | Scheduled |
| TS-0533 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-09-08 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-0534 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-09-08 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-0535 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-09-08 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-0536 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-09-08 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-0537 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-09-08 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-0538 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-09-08 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-0539 | Advanced Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-09-08 | Tuesday | 14:00 | 15:00 | 60 | laboratory session | Scheduled |
| TS-0540 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-09-08 | Tuesday | 15:00 | 17:00 | 120 | seminar | Scheduled |
| TS-0541 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-09-08 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-0542 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-09-08 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-0543 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-09-08 | Tuesday | 16:00 | 18:00 | 120 | seminar | Scheduled |
| TS-0544 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-09-08 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-0545 | Applied Cyber Security | Room 5.17 — Meeting Room | 5 | 2026-09-08 | Tuesday | 16:00 | 18:00 | 120 | small-group session | Scheduled |
| TS-0546 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-09-09 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Scheduled |
| TS-0547 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-09-09 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Scheduled |
| TS-0548 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-09-09 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Scheduled |
| TS-0549 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-09-09 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-0550 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-09-09 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Scheduled |
| TS-0551 | Introduction to Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-09-09 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-0552 | Foundations of Machine Learning | Room 4.56 — Research Laboratory | 4 | 2026-09-09 | Wednesday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-0553 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-09-09 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Scheduled |
| TS-0554 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-09-09 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-0555 | Introduction to Cyber Security | Room 3.03 — Research Laboratory | 3 | 2026-09-09 | Wednesday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-0556 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-09-09 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-0557 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-09-09 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Scheduled |
| TS-0558 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-09-09 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Scheduled |
| TS-0559 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-09-10 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Scheduled |
| TS-0560 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-09-10 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-0561 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-09-10 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-0562 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-09-10 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-0563 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-09-10 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Scheduled |
| TS-0564 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-09-10 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-0565 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-09-10 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-0566 | Applied Computer Science | Room 3.58 — Research Laboratory | 3 | 2026-09-10 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-0567 | Applied Computer Science | Room 4.05 — Computer Laboratory | 4 | 2026-09-10 | Thursday | 11:00 | 13:00 | 120 | computer lab session | Scheduled |
| TS-0568 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-09-10 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-0569 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-09-10 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-0570 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-09-10 | Thursday | 13:00 | 14:00 | 60 | small-group session | Scheduled |
| TS-0571 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-09-10 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-0572 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-09-10 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-0573 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-09-10 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-0574 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-09-10 | Thursday | 14:00 | 15:00 | 60 | small-group session | Scheduled |
| TS-0575 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-09-10 | Thursday | 14:00 | 16:00 | 120 | seminar | Scheduled |
| TS-0576 | Introduction to Computer Science | Room 4.01 — Research Laboratory | 4 | 2026-09-10 | Thursday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-0577 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-09-10 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-0578 | Applied Cyber Security | Room 5.53 — Research Laboratory | 5 | 2026-09-10 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-0579 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-09-11 | Friday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-0580 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-09-11 | Friday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-0581 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-09-11 | Friday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-0582 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-09-11 | Friday | 11:00 | 13:00 | 120 | computer lab session | Scheduled |
| TS-0583 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-09-11 | Friday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-0584 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-09-11 | Friday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-0585 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-09-11 | Friday | 13:00 | 15:00 | 120 | seminar | Scheduled |
| TS-0586 | Research Methods in Cyber Security | Room 2.17 — Research Laboratory | 2 | 2026-09-11 | Friday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-0587 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-09-11 | Friday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-0588 | Research Methods in Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-09-11 | Friday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-0589 | Introduction to Computer Science | Room 3.57 — Research Laboratory | 3 | 2026-09-11 | Friday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-0590 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-09-11 | Friday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-0591 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-09-11 | Friday | 15:00 | 17:00 | 120 | small-group session | Scheduled |
| TS-0592 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-09-11 | Friday | 16:00 | 18:00 | 120 | computer lab session | Scheduled |
| TS-0593 | Research Methods in Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-09-11 | Friday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-0594 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-09-11 | Friday | 16:00 | 18:00 | 120 | small-group session | Scheduled |
| TS-0595 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-09-11 | Friday | 16:00 | 17:00 | 60 | laboratory session | Scheduled |
| TS-0596 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-09-14 | Monday | 09:00 | 11:00 | 120 | seminar | Scheduled |
| TS-0597 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-09-14 | Monday | 09:00 | 10:00 | 60 | laboratory session | Scheduled |
| TS-0598 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-09-14 | Monday | 10:00 | 12:00 | 120 | seminar | Scheduled |
| TS-0599 | Foundations of Data Analysis | Room 3.16 — Meeting Room | 3 | 2026-09-14 | Monday | 10:00 | 12:00 | 120 | small-group session | Scheduled |
| TS-0600 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-09-14 | Monday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-0601 | Applied Software Engineering | Room 5.03 — Research Laboratory | 5 | 2026-09-14 | Monday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-0602 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-09-14 | Monday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-0603 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-09-14 | Monday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-0604 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-09-14 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-0605 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-09-14 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-0606 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-09-14 | Monday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-0607 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-09-14 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-0608 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-09-14 | Monday | 13:00 | 15:00 | 120 | seminar | Scheduled |
| TS-0609 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-09-14 | Monday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-0610 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-09-14 | Monday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-0611 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-09-14 | Monday | 14:00 | 15:00 | 60 | small-group session | Scheduled |
| TS-0612 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-09-14 | Monday | 14:00 | 15:00 | 60 | laboratory session | Scheduled |
| TS-0613 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-09-14 | Monday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-0614 | Applied Software Engineering | Room 3.04 — Research Laboratory | 3 | 2026-09-14 | Monday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-0615 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-09-14 | Monday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-0616 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-09-14 | Monday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-0617 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-09-15 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-0618 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-09-15 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-0619 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-09-15 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Scheduled |
| TS-0620 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-09-15 | Tuesday | 10:00 | 12:00 | 120 | seminar | Scheduled |
| TS-0621 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-09-15 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-0622 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-09-15 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-0623 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-09-15 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-0624 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-09-15 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-0625 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-09-15 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-0626 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-09-15 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-0627 | Advanced Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-09-15 | Tuesday | 14:00 | 15:00 | 60 | laboratory session | Scheduled |
| TS-0628 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-09-15 | Tuesday | 15:00 | 17:00 | 120 | seminar | Scheduled |
| TS-0629 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-09-15 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-0630 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-09-15 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-0631 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-09-15 | Tuesday | 16:00 | 18:00 | 120 | seminar | Scheduled |
| TS-0632 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-09-15 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-0633 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-09-16 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Scheduled |
| TS-0634 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-09-16 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Scheduled |
| TS-0635 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-09-16 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Scheduled |
| TS-0636 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-09-16 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-0637 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-09-16 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Scheduled |
| TS-0638 | Introduction to Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-09-16 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-0639 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-09-16 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Scheduled |
| TS-0640 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-09-16 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-0641 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-09-16 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-0642 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-09-16 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Scheduled |
| TS-0643 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-09-16 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Scheduled |
| TS-0644 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-09-17 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Scheduled |
| TS-0645 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-09-17 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Scheduled |
| TS-0646 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-09-17 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-0647 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-09-17 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Scheduled |
| TS-0648 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-09-17 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-0649 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-09-17 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-0650 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-09-17 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-0651 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-09-17 | Thursday | 13:00 | 14:00 | 60 | small-group session | Scheduled |
| TS-0652 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-09-17 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-0653 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-09-17 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-0654 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-09-17 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-0655 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-09-17 | Thursday | 14:00 | 15:00 | 60 | small-group session | Scheduled |
| TS-0656 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-09-17 | Thursday | 14:00 | 16:00 | 120 | seminar | Scheduled |
| TS-0657 | Introduction to Computer Science | Room 4.01 — Research Laboratory | 4 | 2026-09-17 | Thursday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-0658 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-09-17 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-0659 | Applied Cyber Security | Room 5.53 — Research Laboratory | 5 | 2026-09-17 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-0660 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-09-18 | Friday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-0661 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-09-18 | Friday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-0662 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-09-18 | Friday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-0663 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-09-18 | Friday | 11:00 | 13:00 | 120 | computer lab session | Scheduled |
| TS-0664 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-09-18 | Friday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-0665 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-09-18 | Friday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-0666 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-09-18 | Friday | 13:00 | 15:00 | 120 | seminar | Scheduled |
| TS-0667 | Research Methods in Cyber Security | Room 2.17 — Research Laboratory | 2 | 2026-09-18 | Friday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-0668 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-09-18 | Friday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-0669 | Research Methods in Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-09-18 | Friday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-0670 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-09-18 | Friday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-0671 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-09-18 | Friday | 15:00 | 17:00 | 120 | small-group session | Scheduled |
| TS-0672 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-09-18 | Friday | 16:00 | 18:00 | 120 | computer lab session | Scheduled |
| TS-0673 | Research Methods in Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-09-18 | Friday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-0674 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-09-18 | Friday | 16:00 | 18:00 | 120 | small-group session | Scheduled |
| TS-0675 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-09-18 | Friday | 16:00 | 17:00 | 60 | laboratory session | Scheduled |

**675 sessions across 44 rooms. 168 are still to come and 507 have already run. The register covers 2026-07-27 to 2026-09-18.**
