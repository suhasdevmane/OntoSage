---
record_type: timetabled_session
owner: "Timetabling Officer"
authority: "Cardiff University Registry - Timetabling"
source_system: "Teaching Timetable"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
tables:
  - name: "Timetabled session register"
    maps_to: timetabled_sessions
---

# Timetabled Session Register - Abacws Building

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
| TS-0508 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-09-07 | Monday | 09:00 | 11:00 | 120 | seminar | Completed |
| TS-0509 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-09-07 | Monday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0510 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-09-07 | Monday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0511 | Foundations of Data Analysis | Room 3.16 — Meeting Room | 3 | 2026-09-07 | Monday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0512 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-09-07 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0513 | Applied Software Engineering | Room 5.03 — Research Laboratory | 5 | 2026-09-07 | Monday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0514 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-09-07 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0515 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-09-07 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0516 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-09-07 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0517 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-09-07 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0518 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-09-07 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0519 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-09-07 | Monday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0520 | Introduction to Software Engineering | Room 4.13 — Seminar Room | 4 | 2026-09-07 | Monday | 13:00 | 14:00 | 60 | seminar | Completed |
| TS-0521 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-09-07 | Monday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0522 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-09-07 | Monday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0523 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-09-07 | Monday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0524 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-09-07 | Monday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0525 | Applied Software Engineering | Room 3.04 — Research Laboratory | 3 | 2026-09-07 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0526 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-09-07 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0527 | Introduction to Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-09-07 | Monday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0528 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-09-07 | Monday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0529 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-09-08 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0530 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-09-08 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0531 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-09-08 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0532 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-09-08 | Tuesday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0533 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-09-08 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0534 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-09-08 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0535 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-09-08 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0536 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-09-08 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0537 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-09-08 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0538 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-09-08 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0539 | Advanced Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-09-08 | Tuesday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0540 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-09-08 | Tuesday | 15:00 | 17:00 | 120 | seminar | Completed |
| TS-0541 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-09-08 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0542 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-09-08 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0543 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-09-08 | Tuesday | 16:00 | 18:00 | 120 | seminar | Completed |
| TS-0544 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-09-08 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0545 | Applied Cyber Security | Room 5.17 — Meeting Room | 5 | 2026-09-08 | Tuesday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-0546 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-09-09 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Completed |
| TS-0547 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-09-09 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0548 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-09-09 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0549 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-09-09 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0550 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-09-09 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0551 | Introduction to Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-09-09 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0552 | Foundations of Machine Learning | Room 4.56 — Research Laboratory | 4 | 2026-09-09 | Wednesday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0553 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-09-09 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Completed |
| TS-0554 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-09-09 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0555 | Introduction to Cyber Security | Room 3.03 — Research Laboratory | 3 | 2026-09-09 | Wednesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0556 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-09-09 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0557 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-09-09 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Completed |
| TS-0558 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-09-09 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0559 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-09-10 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Completed |
| TS-0560 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-09-10 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0561 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-09-10 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0562 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-09-10 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0563 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-09-10 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Completed |
| TS-0564 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-09-10 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0565 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-09-10 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0566 | Applied Computer Science | Room 3.58 — Research Laboratory | 3 | 2026-09-10 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0567 | Applied Computer Science | Room 4.05 — Computer Laboratory | 4 | 2026-09-10 | Thursday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0568 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-09-10 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0569 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-09-10 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0570 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-09-10 | Thursday | 13:00 | 14:00 | 60 | small-group session | Completed |
| TS-0571 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-09-10 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0572 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-09-10 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0573 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-09-10 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0574 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-09-10 | Thursday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0575 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-09-10 | Thursday | 14:00 | 16:00 | 120 | seminar | Completed |
| TS-0576 | Introduction to Computer Science | Room 4.01 — Research Laboratory | 4 | 2026-09-10 | Thursday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0577 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-09-10 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0578 | Applied Cyber Security | Room 5.53 — Research Laboratory | 5 | 2026-09-10 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0579 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-09-11 | Friday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0580 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-09-11 | Friday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0581 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-09-11 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0582 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-09-11 | Friday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0583 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-09-11 | Friday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0584 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-09-11 | Friday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0585 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-09-11 | Friday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0586 | Research Methods in Cyber Security | Room 2.17 — Research Laboratory | 2 | 2026-09-11 | Friday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0587 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-09-11 | Friday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0588 | Research Methods in Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-09-11 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0589 | Introduction to Computer Science | Room 3.57 — Research Laboratory | 3 | 2026-09-11 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0590 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-09-11 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0591 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-09-11 | Friday | 15:00 | 17:00 | 120 | small-group session | Completed |
| TS-0592 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-09-11 | Friday | 16:00 | 18:00 | 120 | computer lab session | Completed |
| TS-0593 | Research Methods in Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-09-11 | Friday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0594 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-09-11 | Friday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-0595 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-09-11 | Friday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0596 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-09-14 | Monday | 09:00 | 11:00 | 120 | seminar | Completed |
| TS-0597 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-09-14 | Monday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0598 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-09-14 | Monday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0599 | Foundations of Data Analysis | Room 3.16 — Meeting Room | 3 | 2026-09-14 | Monday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0600 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-09-14 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0601 | Applied Software Engineering | Room 5.03 — Research Laboratory | 5 | 2026-09-14 | Monday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0602 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-09-14 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0603 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-09-14 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0604 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-09-14 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0605 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-09-14 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0606 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-09-14 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0607 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-09-14 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0608 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-09-14 | Monday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0609 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-09-14 | Monday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0610 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-09-14 | Monday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0611 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-09-14 | Monday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0612 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-09-14 | Monday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0613 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-09-14 | Monday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0614 | Applied Software Engineering | Room 3.04 — Research Laboratory | 3 | 2026-09-14 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0615 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-09-14 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0616 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-09-14 | Monday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0617 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-09-15 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0618 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-09-15 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0619 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-09-15 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0620 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-09-15 | Tuesday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0621 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-09-15 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0622 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-09-15 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0623 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-09-15 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0624 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-09-15 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0625 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-09-15 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0626 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-09-15 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0627 | Advanced Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-09-15 | Tuesday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0628 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-09-15 | Tuesday | 15:00 | 17:00 | 120 | seminar | Completed |
| TS-0629 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-09-15 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0630 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-09-15 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0631 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-09-15 | Tuesday | 16:00 | 18:00 | 120 | seminar | Completed |
| TS-0632 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-09-15 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0633 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-09-16 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Completed |
| TS-0634 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-09-16 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0635 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-09-16 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0636 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-09-16 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0637 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-09-16 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0638 | Introduction to Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-09-16 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0639 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-09-16 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Completed |
| TS-0640 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-09-16 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0641 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-09-16 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0642 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-09-16 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Completed |
| TS-0643 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-09-16 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0644 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-09-17 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Completed |
| TS-0645 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-09-17 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0646 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-09-17 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0647 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-09-17 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Completed |
| TS-0648 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-09-17 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0649 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-09-17 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0650 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-09-17 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0651 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-09-17 | Thursday | 13:00 | 14:00 | 60 | small-group session | Completed |
| TS-0652 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-09-17 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0653 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-09-17 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0654 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-09-17 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0655 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-09-17 | Thursday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0656 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-09-17 | Thursday | 14:00 | 16:00 | 120 | seminar | Completed |
| TS-0657 | Introduction to Computer Science | Room 4.01 — Research Laboratory | 4 | 2026-09-17 | Thursday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0658 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-09-17 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0659 | Applied Cyber Security | Room 5.53 — Research Laboratory | 5 | 2026-09-17 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0660 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-09-18 | Friday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0661 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-09-18 | Friday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0662 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-09-18 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0663 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-09-18 | Friday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0664 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-09-18 | Friday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0665 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-09-18 | Friday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0666 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-09-18 | Friday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0667 | Research Methods in Cyber Security | Room 2.17 — Research Laboratory | 2 | 2026-09-18 | Friday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0668 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-09-18 | Friday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0669 | Research Methods in Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-09-18 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0670 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-09-18 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0671 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-09-18 | Friday | 15:00 | 17:00 | 120 | small-group session | Completed |
| TS-0672 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-09-18 | Friday | 16:00 | 18:00 | 120 | computer lab session | Completed |
| TS-0673 | Research Methods in Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-09-18 | Friday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0674 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-09-18 | Friday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-0675 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-09-18 | Friday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0676 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-09-21 | Monday | 09:00 | 11:00 | 120 | seminar | Completed |
| TS-0677 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-09-21 | Monday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0678 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-09-21 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0679 | Applied Software Engineering | Room 5.03 — Research Laboratory | 5 | 2026-09-21 | Monday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0680 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-09-21 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0681 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-09-21 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0682 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-09-21 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0683 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-09-21 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0684 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-09-21 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0685 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-09-21 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0686 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-09-21 | Monday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0687 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-09-21 | Monday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0688 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-09-21 | Monday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0689 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-09-21 | Monday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0690 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-09-21 | Monday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0691 | Applied Software Engineering | Room 3.04 — Research Laboratory | 3 | 2026-09-21 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0692 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-09-21 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0693 | Introduction to Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-09-21 | Monday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0694 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-09-21 | Monday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0695 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-09-22 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0696 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-09-22 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0697 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-09-22 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0698 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-09-22 | Tuesday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0699 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-09-22 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0700 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-09-22 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0701 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-09-22 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0702 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-09-22 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0703 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-09-22 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0704 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-09-22 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0705 | Advanced Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-09-22 | Tuesday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0706 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-09-22 | Tuesday | 15:00 | 17:00 | 120 | seminar | Completed |
| TS-0707 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-09-22 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0708 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-09-22 | Tuesday | 16:00 | 18:00 | 120 | seminar | Completed |
| TS-0709 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-09-22 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0710 | Applied Cyber Security | Room 5.17 — Meeting Room | 5 | 2026-09-22 | Tuesday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-0711 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-09-23 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Completed |
| TS-0712 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-09-23 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0713 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-09-23 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0714 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-09-23 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0715 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-09-23 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0716 | Foundations of Machine Learning | Room 4.56 — Research Laboratory | 4 | 2026-09-23 | Wednesday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0717 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-09-23 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0718 | Research Methods in Cyber Security | Room 2.53 — Research Laboratory | 2 | 2026-09-23 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0719 | Introduction to Cyber Security | Room 3.03 — Research Laboratory | 3 | 2026-09-23 | Wednesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0720 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-09-23 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0721 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-09-23 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Completed |
| TS-0722 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-09-23 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0723 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-09-24 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Completed |
| TS-0724 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-09-24 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0725 | Advanced Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-09-24 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0726 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-09-24 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0727 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-09-24 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0728 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-09-24 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0729 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-09-24 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Completed |
| TS-0730 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-09-24 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0731 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-09-24 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0732 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-09-24 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0733 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-09-24 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0734 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-09-24 | Thursday | 13:00 | 14:00 | 60 | small-group session | Completed |
| TS-0735 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-09-24 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0736 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-09-24 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0737 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-09-24 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0738 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-09-24 | Thursday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0739 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-09-24 | Thursday | 14:00 | 16:00 | 120 | seminar | Completed |
| TS-0740 | Introduction to Computer Science | Room 4.01 — Research Laboratory | 4 | 2026-09-24 | Thursday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0741 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-09-24 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0742 | Applied Cyber Security | Room 5.53 — Research Laboratory | 5 | 2026-09-24 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0743 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-09-25 | Friday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0744 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-09-25 | Friday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0745 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-09-25 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0746 | Foundations of Human-Computer Interaction | Room 4.19 — Research Laboratory | 4 | 2026-09-25 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0747 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-09-25 | Friday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0748 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-09-25 | Friday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0749 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-09-25 | Friday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0750 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-09-25 | Friday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0751 | Research Methods in Cyber Security | Room 2.17 — Research Laboratory | 2 | 2026-09-25 | Friday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0752 | Research Methods in Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-09-25 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0753 | Introduction to Computer Science | Room 3.57 — Research Laboratory | 3 | 2026-09-25 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0754 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-09-25 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0755 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-09-25 | Friday | 15:00 | 17:00 | 120 | small-group session | Completed |
| TS-0756 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-09-25 | Friday | 16:00 | 18:00 | 120 | computer lab session | Completed |
| TS-0757 | Research Methods in Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-09-25 | Friday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0758 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-09-25 | Friday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0759 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-09-28 | Monday | 09:00 | 11:00 | 120 | seminar | Completed |
| TS-0760 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-09-28 | Monday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0761 | Foundations of Data Analysis | Room 3.16 — Meeting Room | 3 | 2026-09-28 | Monday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0762 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-09-28 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0763 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-09-28 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0764 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-09-28 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0765 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-09-28 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0766 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-09-28 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0767 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-09-28 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0768 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-09-28 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0769 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-09-28 | Monday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0770 | Introduction to Software Engineering | Room 4.13 — Seminar Room | 4 | 2026-09-28 | Monday | 13:00 | 14:00 | 60 | seminar | Completed |
| TS-0771 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-09-28 | Monday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0772 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-09-28 | Monday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0773 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-09-28 | Monday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0774 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-09-28 | Monday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0775 | Applied Software Engineering | Room 3.04 — Research Laboratory | 3 | 2026-09-28 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0776 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-09-28 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0777 | Introduction to Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-09-28 | Monday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0778 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-09-28 | Monday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0779 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-09-29 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0780 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-09-29 | Tuesday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0781 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-09-29 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0782 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-09-29 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0783 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-09-29 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0784 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-09-29 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0785 | Advanced Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-09-29 | Tuesday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0786 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-09-29 | Tuesday | 15:00 | 17:00 | 120 | seminar | Completed |
| TS-0787 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-09-29 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0788 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-09-29 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0789 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-09-29 | Tuesday | 16:00 | 18:00 | 120 | seminar | Completed |
| TS-0790 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-09-29 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0791 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-09-30 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Completed |
| TS-0792 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-09-30 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0793 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-09-30 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0794 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-09-30 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0795 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-09-30 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0796 | Introduction to Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-09-30 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0797 | Foundations of Machine Learning | Room 4.56 — Research Laboratory | 4 | 2026-09-30 | Wednesday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0798 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-09-30 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Completed |
| TS-0799 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-09-30 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0800 | Research Methods in Cyber Security | Room 2.53 — Research Laboratory | 2 | 2026-09-30 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0801 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-09-30 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0802 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-09-30 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Completed |
| TS-0803 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-10-01 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Completed |
| TS-0804 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-10-01 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0805 | Advanced Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-10-01 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0806 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-10-01 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0807 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-10-01 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0808 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-10-01 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0809 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-10-01 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Completed |
| TS-0810 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-10-01 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0811 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-10-01 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0812 | Applied Computer Science | Room 4.05 — Computer Laboratory | 4 | 2026-10-01 | Thursday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0813 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-10-01 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0814 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-10-01 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0815 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-10-01 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0816 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-10-01 | Thursday | 13:00 | 14:00 | 60 | small-group session | Completed |
| TS-0817 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-10-01 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0818 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-10-01 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0819 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-10-01 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0820 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-10-01 | Thursday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0821 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-10-01 | Thursday | 14:00 | 16:00 | 120 | seminar | Completed |
| TS-0822 | Introduction to Computer Science | Room 4.01 — Research Laboratory | 4 | 2026-10-01 | Thursday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0823 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-10-01 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0824 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-10-02 | Friday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0825 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-10-02 | Friday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0826 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-10-02 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0827 | Foundations of Human-Computer Interaction | Room 4.19 — Research Laboratory | 4 | 2026-10-02 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0828 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-10-02 | Friday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0829 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-10-02 | Friday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0830 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-10-02 | Friday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0831 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-10-02 | Friday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0832 | Research Methods in Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-10-02 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0833 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-10-02 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0834 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-10-02 | Friday | 15:00 | 17:00 | 120 | small-group session | Completed |
| TS-0835 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-10-02 | Friday | 16:00 | 18:00 | 120 | computer lab session | Completed |
| TS-0836 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-10-02 | Friday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-0837 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-10-02 | Friday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0838 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-10-05 | Monday | 09:00 | 11:00 | 120 | seminar | Completed |
| TS-0839 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-10-05 | Monday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0840 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-10-05 | Monday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0841 | Foundations of Data Analysis | Room 3.16 — Meeting Room | 3 | 2026-10-05 | Monday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0842 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-10-05 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0843 | Applied Software Engineering | Room 5.03 — Research Laboratory | 5 | 2026-10-05 | Monday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0844 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-10-05 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0845 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-10-05 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0846 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-10-05 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0847 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-10-05 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0848 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-10-05 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0849 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-10-05 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0850 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-10-05 | Monday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0851 | Introduction to Software Engineering | Room 4.13 — Seminar Room | 4 | 2026-10-05 | Monday | 13:00 | 14:00 | 60 | seminar | Completed |
| TS-0852 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-10-05 | Monday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0853 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-10-05 | Monday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0854 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-10-05 | Monday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0855 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-10-05 | Monday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0856 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-10-05 | Monday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0857 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-10-05 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0858 | Introduction to Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-10-05 | Monday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0859 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-10-05 | Monday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0860 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-10-06 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0861 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-10-06 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0862 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-10-06 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0863 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-10-06 | Tuesday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0864 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-10-06 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0865 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-10-06 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0866 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-10-06 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0867 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-10-06 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0868 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-10-06 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0869 | Advanced Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-10-06 | Tuesday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0870 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-10-06 | Tuesday | 15:00 | 17:00 | 120 | seminar | Completed |
| TS-0871 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-10-06 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0872 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-10-06 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0873 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-10-06 | Tuesday | 16:00 | 18:00 | 120 | seminar | Completed |
| TS-0874 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-10-06 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0875 | Applied Cyber Security | Room 5.17 — Meeting Room | 5 | 2026-10-06 | Tuesday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-0876 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-10-07 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Completed |
| TS-0877 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-10-07 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0878 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-10-07 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0879 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-10-07 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0880 | Introduction to Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-10-07 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0881 | Foundations of Machine Learning | Room 4.56 — Research Laboratory | 4 | 2026-10-07 | Wednesday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0882 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-10-07 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Completed |
| TS-0883 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-10-07 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0884 | Research Methods in Cyber Security | Room 2.53 — Research Laboratory | 2 | 2026-10-07 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0885 | Introduction to Cyber Security | Room 3.03 — Research Laboratory | 3 | 2026-10-07 | Wednesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0886 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-10-07 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0887 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-10-07 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Completed |
| TS-0888 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-10-07 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0889 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-10-08 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Completed |
| TS-0890 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-10-08 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0891 | Advanced Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-10-08 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0892 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-10-08 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0893 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-10-08 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0894 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-10-08 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0895 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-10-08 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Completed |
| TS-0896 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-10-08 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0897 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-10-08 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0898 | Applied Computer Science | Room 3.58 — Research Laboratory | 3 | 2026-10-08 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0899 | Applied Computer Science | Room 4.05 — Computer Laboratory | 4 | 2026-10-08 | Thursday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0900 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-10-08 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0901 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-10-08 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0902 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-10-08 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0903 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-10-08 | Thursday | 13:00 | 14:00 | 60 | small-group session | Completed |
| TS-0904 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-10-08 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0905 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-10-08 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0906 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-10-08 | Thursday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0907 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-10-08 | Thursday | 14:00 | 16:00 | 120 | seminar | Completed |
| TS-0908 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-10-08 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0909 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-10-09 | Friday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0910 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-10-09 | Friday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0911 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-10-09 | Friday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0912 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-10-09 | Friday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0913 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-10-09 | Friday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0914 | Research Methods in Cyber Security | Room 2.17 — Research Laboratory | 2 | 2026-10-09 | Friday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0915 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-10-09 | Friday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0916 | Research Methods in Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-10-09 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0917 | Introduction to Computer Science | Room 3.57 — Research Laboratory | 3 | 2026-10-09 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0918 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-10-09 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0919 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-10-09 | Friday | 15:00 | 17:00 | 120 | small-group session | Completed |
| TS-0920 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-10-09 | Friday | 16:00 | 18:00 | 120 | computer lab session | Completed |
| TS-0921 | Research Methods in Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-10-09 | Friday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0922 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-10-09 | Friday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-0923 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-10-09 | Friday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0924 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-10-12 | Monday | 09:00 | 11:00 | 120 | seminar | Completed |
| TS-0925 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-10-12 | Monday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0926 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-10-12 | Monday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0927 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-10-12 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0928 | Applied Software Engineering | Room 5.03 — Research Laboratory | 5 | 2026-10-12 | Monday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0929 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-10-12 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0930 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-10-12 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0931 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-10-12 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0932 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-10-12 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0933 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-10-12 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0934 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-10-12 | Monday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-0935 | Introduction to Software Engineering | Room 4.13 — Seminar Room | 4 | 2026-10-12 | Monday | 13:00 | 14:00 | 60 | seminar | Completed |
| TS-0936 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-10-12 | Monday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0937 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-10-12 | Monday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0938 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-10-12 | Monday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-0939 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-10-12 | Monday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0940 | Applied Software Engineering | Room 3.04 — Research Laboratory | 3 | 2026-10-12 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0941 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-10-12 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0942 | Introduction to Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-10-12 | Monday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0943 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-10-12 | Monday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0944 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-10-13 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0945 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-10-13 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0946 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-10-13 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0947 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-10-13 | Tuesday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-0948 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-10-13 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0949 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-10-13 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0950 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-10-13 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0951 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-10-13 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0952 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-10-13 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0953 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-10-13 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0954 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-10-13 | Tuesday | 15:00 | 17:00 | 120 | seminar | Completed |
| TS-0955 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-10-13 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0956 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-10-13 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0957 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-10-14 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Completed |
| TS-0958 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-10-14 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0959 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-10-14 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-0960 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-10-14 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0961 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-10-14 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-0962 | Introduction to Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-10-14 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0963 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-10-14 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Completed |
| TS-0964 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-10-14 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0965 | Research Methods in Cyber Security | Room 2.53 — Research Laboratory | 2 | 2026-10-14 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0966 | Introduction to Cyber Security | Room 3.03 — Research Laboratory | 3 | 2026-10-14 | Wednesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-0967 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-10-14 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0968 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-10-14 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Completed |
| TS-0969 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-10-14 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-0970 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-10-15 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Completed |
| TS-0971 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-10-15 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0972 | Advanced Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-10-15 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0973 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-10-15 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-0974 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-10-15 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0975 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-10-15 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0976 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-10-15 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Completed |
| TS-0977 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-10-15 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0978 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-10-15 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0979 | Applied Computer Science | Room 3.58 — Research Laboratory | 3 | 2026-10-15 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0980 | Applied Computer Science | Room 4.05 — Computer Laboratory | 4 | 2026-10-15 | Thursday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0981 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-10-15 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0982 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-10-15 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-0983 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-10-15 | Thursday | 13:00 | 14:00 | 60 | small-group session | Completed |
| TS-0984 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-10-15 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0985 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-10-15 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-0986 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-10-15 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-0987 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-10-15 | Thursday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-0988 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-10-15 | Thursday | 14:00 | 16:00 | 120 | seminar | Completed |
| TS-0989 | Introduction to Computer Science | Room 4.01 — Research Laboratory | 4 | 2026-10-15 | Thursday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-0990 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-10-15 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0991 | Applied Cyber Security | Room 5.53 — Research Laboratory | 5 | 2026-10-15 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-0992 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-10-16 | Friday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-0993 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-10-16 | Friday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-0994 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-10-16 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0995 | Foundations of Human-Computer Interaction | Room 4.19 — Research Laboratory | 4 | 2026-10-16 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-0996 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-10-16 | Friday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-0997 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-10-16 | Friday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-0998 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-10-16 | Friday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-0999 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-10-16 | Friday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-1000 | Research Methods in Cyber Security | Room 2.17 — Research Laboratory | 2 | 2026-10-16 | Friday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-1001 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-10-16 | Friday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-1002 | Introduction to Computer Science | Room 3.57 — Research Laboratory | 3 | 2026-10-16 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1003 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-10-16 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1004 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-10-16 | Friday | 15:00 | 17:00 | 120 | small-group session | Completed |
| TS-1005 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-10-16 | Friday | 16:00 | 18:00 | 120 | computer lab session | Completed |
| TS-1006 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-10-16 | Friday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-1007 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-10-16 | Friday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-1008 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-10-19 | Monday | 09:00 | 11:00 | 120 | seminar | Completed |
| TS-1009 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-10-19 | Monday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-1010 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-10-19 | Monday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-1011 | Foundations of Data Analysis | Room 3.16 — Meeting Room | 3 | 2026-10-19 | Monday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-1012 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-10-19 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1013 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-10-19 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1014 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-10-19 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-1015 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-10-19 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1016 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-10-19 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1017 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-10-19 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-1018 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-10-19 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1019 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-10-19 | Monday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-1020 | Introduction to Software Engineering | Room 4.13 — Seminar Room | 4 | 2026-10-19 | Monday | 13:00 | 14:00 | 60 | seminar | Completed |
| TS-1021 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-10-19 | Monday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-1022 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-10-19 | Monday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-1023 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-10-19 | Monday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-1024 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-10-19 | Monday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-1025 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-10-19 | Monday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1026 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-10-19 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-1027 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-10-20 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-1028 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-10-20 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-1029 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-10-20 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-1030 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-10-20 | Tuesday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-1031 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-10-20 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1032 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-10-20 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-1033 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-10-20 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1034 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-10-20 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-1035 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-10-20 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-1036 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-10-20 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-1037 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-10-20 | Tuesday | 15:00 | 17:00 | 120 | seminar | Completed |
| TS-1038 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-10-20 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1039 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-10-20 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-1040 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-10-20 | Tuesday | 16:00 | 18:00 | 120 | seminar | Completed |
| TS-1041 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-10-20 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-1042 | Applied Cyber Security | Room 5.17 — Meeting Room | 5 | 2026-10-20 | Tuesday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-1043 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-10-21 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Completed |
| TS-1044 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-10-21 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-1045 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-10-21 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-1046 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-10-21 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1047 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-10-21 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-1048 | Introduction to Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-10-21 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1049 | Foundations of Machine Learning | Room 4.56 — Research Laboratory | 4 | 2026-10-21 | Wednesday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-1050 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-10-21 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Completed |
| TS-1051 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-10-21 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-1052 | Research Methods in Cyber Security | Room 2.53 — Research Laboratory | 2 | 2026-10-21 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1053 | Introduction to Cyber Security | Room 3.03 — Research Laboratory | 3 | 2026-10-21 | Wednesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-1054 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-10-21 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1055 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-10-21 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Completed |
| TS-1056 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-10-21 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-1057 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-10-22 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Completed |
| TS-1058 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-10-22 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-1059 | Advanced Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-10-22 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-1060 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-10-22 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-1061 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-10-22 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-1062 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-10-22 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-1063 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-10-22 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Completed |
| TS-1064 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-10-22 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-1065 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-10-22 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1066 | Applied Computer Science | Room 3.58 — Research Laboratory | 3 | 2026-10-22 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1067 | Applied Computer Science | Room 4.05 — Computer Laboratory | 4 | 2026-10-22 | Thursday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-1068 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-10-22 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1069 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-10-22 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-1070 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-10-22 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-1071 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-10-22 | Thursday | 13:00 | 14:00 | 60 | small-group session | Completed |
| TS-1072 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-10-22 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-1073 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-10-22 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-1074 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-10-22 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-1075 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-10-22 | Thursday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-1076 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-10-22 | Thursday | 14:00 | 16:00 | 120 | seminar | Completed |
| TS-1077 | Introduction to Computer Science | Room 4.01 — Research Laboratory | 4 | 2026-10-22 | Thursday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1078 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-10-22 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-1079 | Applied Cyber Security | Room 5.53 — Research Laboratory | 5 | 2026-10-22 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-1080 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-10-23 | Friday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-1081 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-10-23 | Friday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1082 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-10-23 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-1083 | Foundations of Human-Computer Interaction | Room 4.19 — Research Laboratory | 4 | 2026-10-23 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-1084 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-10-23 | Friday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-1085 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-10-23 | Friday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1086 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-10-23 | Friday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-1087 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-10-23 | Friday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-1088 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-10-23 | Friday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-1089 | Research Methods in Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-10-23 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1090 | Introduction to Computer Science | Room 3.57 — Research Laboratory | 3 | 2026-10-23 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1091 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-10-23 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1092 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-10-23 | Friday | 15:00 | 17:00 | 120 | small-group session | Completed |
| TS-1093 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-10-23 | Friday | 16:00 | 18:00 | 120 | computer lab session | Completed |
| TS-1094 | Research Methods in Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-10-23 | Friday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-1095 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-10-23 | Friday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-1096 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-10-23 | Friday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-1097 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-10-26 | Monday | 09:00 | 11:00 | 120 | seminar | Completed |
| TS-1098 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-10-26 | Monday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-1099 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-10-26 | Monday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-1100 | Foundations of Data Analysis | Room 3.16 — Meeting Room | 3 | 2026-10-26 | Monday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-1101 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-10-26 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1102 | Applied Software Engineering | Room 5.03 — Research Laboratory | 5 | 2026-10-26 | Monday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-1103 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-10-26 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1104 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-10-26 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-1105 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-10-26 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1106 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-10-26 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1107 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-10-26 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-1108 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-10-26 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1109 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-10-26 | Monday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-1110 | Introduction to Software Engineering | Room 4.13 — Seminar Room | 4 | 2026-10-26 | Monday | 13:00 | 14:00 | 60 | seminar | Completed |
| TS-1111 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-10-26 | Monday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-1112 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-10-26 | Monday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-1113 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-10-26 | Monday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-1114 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-10-26 | Monday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-1115 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-10-26 | Monday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1116 | Applied Software Engineering | Room 3.04 — Research Laboratory | 3 | 2026-10-26 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-1117 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-10-26 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-1118 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-10-26 | Monday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-1119 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-10-27 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-1120 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-10-27 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-1121 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-10-27 | Tuesday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-1122 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-10-27 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1123 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-10-27 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-1124 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-10-27 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1125 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-10-27 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-1126 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-10-27 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-1127 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-10-27 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-1128 | Advanced Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-10-27 | Tuesday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-1129 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-10-27 | Tuesday | 15:00 | 17:00 | 120 | seminar | Completed |
| TS-1130 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-10-27 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1131 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-10-27 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-1132 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-10-27 | Tuesday | 16:00 | 18:00 | 120 | seminar | Completed |
| TS-1133 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-10-27 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-1134 | Applied Cyber Security | Room 5.17 — Meeting Room | 5 | 2026-10-27 | Tuesday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-1135 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-10-28 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Completed |
| TS-1136 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-10-28 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-1137 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-10-28 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-1138 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-10-28 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1139 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-10-28 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-1140 | Foundations of Machine Learning | Room 4.56 — Research Laboratory | 4 | 2026-10-28 | Wednesday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-1141 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-10-28 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Completed |
| TS-1142 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-10-28 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-1143 | Research Methods in Cyber Security | Room 2.53 — Research Laboratory | 2 | 2026-10-28 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1144 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-10-28 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1145 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-10-28 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Completed |
| TS-1146 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-10-28 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-1147 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-10-29 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Completed |
| TS-1148 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-10-29 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-1149 | Advanced Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-10-29 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-1150 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-10-29 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-1151 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-10-29 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-1152 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-10-29 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-1153 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-10-29 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Completed |
| TS-1154 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-10-29 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-1155 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-10-29 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1156 | Applied Computer Science | Room 3.58 — Research Laboratory | 3 | 2026-10-29 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1157 | Applied Computer Science | Room 4.05 — Computer Laboratory | 4 | 2026-10-29 | Thursday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-1158 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-10-29 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1159 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-10-29 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-1160 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-10-29 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-1161 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-10-29 | Thursday | 13:00 | 14:00 | 60 | small-group session | Completed |
| TS-1162 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-10-29 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-1163 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-10-29 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-1164 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-10-29 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-1165 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-10-29 | Thursday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-1166 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-10-29 | Thursday | 14:00 | 16:00 | 120 | seminar | Completed |
| TS-1167 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-10-29 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-1168 | Applied Cyber Security | Room 5.53 — Research Laboratory | 5 | 2026-10-29 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-1169 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-10-30 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-1170 | Foundations of Human-Computer Interaction | Room 4.19 — Research Laboratory | 4 | 2026-10-30 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-1171 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-10-30 | Friday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-1172 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-10-30 | Friday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1173 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-10-30 | Friday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-1174 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-10-30 | Friday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-1175 | Research Methods in Cyber Security | Room 2.17 — Research Laboratory | 2 | 2026-10-30 | Friday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-1176 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-10-30 | Friday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-1177 | Introduction to Computer Science | Room 3.57 — Research Laboratory | 3 | 2026-10-30 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1178 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-10-30 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1179 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-10-30 | Friday | 15:00 | 17:00 | 120 | small-group session | Completed |
| TS-1180 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-10-30 | Friday | 16:00 | 18:00 | 120 | computer lab session | Completed |
| TS-1181 | Research Methods in Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-10-30 | Friday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-1182 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-10-30 | Friday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-1183 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-11-02 | Monday | 09:00 | 11:00 | 120 | seminar | Completed |
| TS-1184 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-11-02 | Monday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-1185 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-11-02 | Monday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-1186 | Foundations of Data Analysis | Room 3.16 — Meeting Room | 3 | 2026-11-02 | Monday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-1187 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-11-02 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1188 | Applied Software Engineering | Room 5.03 — Research Laboratory | 5 | 2026-11-02 | Monday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-1189 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-11-02 | Monday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1190 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-11-02 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-1191 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-11-02 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1192 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-11-02 | Monday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-1193 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-11-02 | Monday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1194 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-11-02 | Monday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-1195 | Introduction to Software Engineering | Room 4.13 — Seminar Room | 4 | 2026-11-02 | Monday | 13:00 | 14:00 | 60 | seminar | Completed |
| TS-1196 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-11-02 | Monday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-1197 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-11-02 | Monday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-1198 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-11-02 | Monday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-1199 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-11-02 | Monday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1200 | Applied Software Engineering | Room 3.04 — Research Laboratory | 3 | 2026-11-02 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-1201 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-11-02 | Monday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-1202 | Introduction to Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-11-02 | Monday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-1203 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-11-02 | Monday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-1204 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-11-03 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-1205 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-11-03 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-1206 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-11-03 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Completed |
| TS-1207 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-11-03 | Tuesday | 10:00 | 12:00 | 120 | seminar | Completed |
| TS-1208 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-11-03 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1209 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-11-03 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-1210 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-11-03 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1211 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-11-03 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-1212 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-11-03 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-1213 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-11-03 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-1214 | Advanced Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-11-03 | Tuesday | 14:00 | 15:00 | 60 | laboratory session | Completed |
| TS-1215 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-11-03 | Tuesday | 15:00 | 17:00 | 120 | seminar | Completed |
| TS-1216 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-11-03 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1217 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-11-03 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-1218 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-11-03 | Tuesday | 16:00 | 18:00 | 120 | seminar | Completed |
| TS-1219 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-11-03 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-1220 | Applied Cyber Security | Room 5.17 — Meeting Room | 5 | 2026-11-03 | Tuesday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-1221 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-11-04 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Completed |
| TS-1222 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-11-04 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-1223 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-11-04 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Completed |
| TS-1224 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-11-04 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1225 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-11-04 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Completed |
| TS-1226 | Introduction to Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-11-04 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1227 | Foundations of Machine Learning | Room 4.56 — Research Laboratory | 4 | 2026-11-04 | Wednesday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-1228 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-11-04 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Completed |
| TS-1229 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-11-04 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-1230 | Introduction to Cyber Security | Room 3.03 — Research Laboratory | 3 | 2026-11-04 | Wednesday | 15:00 | 16:00 | 60 | laboratory session | Completed |
| TS-1231 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-11-04 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1232 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-11-04 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Completed |
| TS-1233 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-11-04 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-1234 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-11-05 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Completed |
| TS-1235 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-11-05 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-1236 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-11-05 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-1237 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-11-05 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-1238 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-11-05 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Completed |
| TS-1239 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-11-05 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-1240 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-11-05 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1241 | Applied Computer Science | Room 3.58 — Research Laboratory | 3 | 2026-11-05 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1242 | Applied Computer Science | Room 4.05 — Computer Laboratory | 4 | 2026-11-05 | Thursday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-1243 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-11-05 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-1244 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-11-05 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-1245 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-11-05 | Thursday | 13:00 | 14:00 | 60 | small-group session | Completed |
| TS-1246 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-11-05 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-1247 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-11-05 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Completed |
| TS-1248 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-11-05 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-1249 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-11-05 | Thursday | 14:00 | 15:00 | 60 | small-group session | Completed |
| TS-1250 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-11-05 | Thursday | 14:00 | 16:00 | 120 | seminar | Completed |
| TS-1251 | Introduction to Computer Science | Room 4.01 — Research Laboratory | 4 | 2026-11-05 | Thursday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1252 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-11-05 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-1253 | Applied Cyber Security | Room 5.53 — Research Laboratory | 5 | 2026-11-05 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-1254 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-11-06 | Friday | 09:00 | 11:00 | 120 | laboratory session | Completed |
| TS-1255 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-11-06 | Friday | 10:00 | 11:00 | 60 | laboratory session | Completed |
| TS-1256 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-11-06 | Friday | 10:00 | 12:00 | 120 | laboratory session | Completed |
| TS-1257 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-11-06 | Friday | 11:00 | 13:00 | 120 | computer lab session | Completed |
| TS-1258 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-11-06 | Friday | 11:00 | 12:00 | 60 | laboratory session | Completed |
| TS-1259 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-11-06 | Friday | 11:00 | 13:00 | 120 | laboratory session | Completed |
| TS-1260 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-11-06 | Friday | 13:00 | 15:00 | 120 | seminar | Completed |
| TS-1261 | Research Methods in Cyber Security | Room 2.17 — Research Laboratory | 2 | 2026-11-06 | Friday | 13:00 | 14:00 | 60 | laboratory session | Completed |
| TS-1262 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-11-06 | Friday | 14:00 | 16:00 | 120 | laboratory session | Completed |
| TS-1263 | Research Methods in Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-11-06 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1264 | Introduction to Computer Science | Room 3.57 — Research Laboratory | 3 | 2026-11-06 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1265 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-11-06 | Friday | 15:00 | 17:00 | 120 | laboratory session | Completed |
| TS-1266 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-11-06 | Friday | 15:00 | 17:00 | 120 | small-group session | Completed |
| TS-1267 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-11-06 | Friday | 16:00 | 18:00 | 120 | computer lab session | Completed |
| TS-1268 | Research Methods in Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-11-06 | Friday | 16:00 | 18:00 | 120 | laboratory session | Completed |
| TS-1269 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-11-06 | Friday | 16:00 | 18:00 | 120 | small-group session | Completed |
| TS-1270 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-11-06 | Friday | 16:00 | 17:00 | 60 | laboratory session | Completed |
| TS-1271 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-11-09 | Monday | 09:00 | 11:00 | 120 | seminar | Scheduled |
| TS-1272 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-11-09 | Monday | 09:00 | 10:00 | 60 | laboratory session | Scheduled |
| TS-1273 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-11-09 | Monday | 10:00 | 12:00 | 120 | seminar | Scheduled |
| TS-1274 | Foundations of Data Analysis | Room 3.16 — Meeting Room | 3 | 2026-11-09 | Monday | 10:00 | 12:00 | 120 | small-group session | Scheduled |
| TS-1275 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-11-09 | Monday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1276 | Applied Software Engineering | Room 5.03 — Research Laboratory | 5 | 2026-11-09 | Monday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1277 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-11-09 | Monday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1278 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-11-09 | Monday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1279 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-11-09 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1280 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-11-09 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1281 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-11-09 | Monday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1282 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-11-09 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1283 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-11-09 | Monday | 13:00 | 15:00 | 120 | seminar | Scheduled |
| TS-1284 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-11-09 | Monday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1285 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-11-09 | Monday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-1286 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-11-09 | Monday | 14:00 | 15:00 | 60 | small-group session | Scheduled |
| TS-1287 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-11-09 | Monday | 14:00 | 15:00 | 60 | laboratory session | Scheduled |
| TS-1288 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-11-09 | Monday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1289 | Applied Software Engineering | Room 3.04 — Research Laboratory | 3 | 2026-11-09 | Monday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-1290 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-11-09 | Monday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-1291 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-11-09 | Monday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1292 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-11-10 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1293 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-11-10 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1294 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-11-10 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Scheduled |
| TS-1295 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-11-10 | Tuesday | 10:00 | 12:00 | 120 | seminar | Scheduled |
| TS-1296 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-11-10 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1297 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-11-10 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1298 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-11-10 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1299 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-11-10 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1300 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-11-10 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1301 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-11-10 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-1302 | Advanced Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-11-10 | Tuesday | 14:00 | 15:00 | 60 | laboratory session | Scheduled |
| TS-1303 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-11-10 | Tuesday | 15:00 | 17:00 | 120 | seminar | Scheduled |
| TS-1304 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-11-10 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1305 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-11-10 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-1306 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-11-10 | Tuesday | 16:00 | 18:00 | 120 | seminar | Scheduled |
| TS-1307 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-11-10 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1308 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-11-11 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Scheduled |
| TS-1309 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-11-11 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Scheduled |
| TS-1310 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-11-11 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Scheduled |
| TS-1311 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-11-11 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1312 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-11-11 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Scheduled |
| TS-1313 | Introduction to Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-11-11 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1314 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-11-11 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Scheduled |
| TS-1315 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-11-11 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-1316 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-11-11 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1317 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-11-11 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Scheduled |
| TS-1318 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-11-11 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Scheduled |
| TS-1319 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-11-12 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Scheduled |
| TS-1320 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-11-12 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Scheduled |
| TS-1321 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-11-12 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1322 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-11-12 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Scheduled |
| TS-1323 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-11-12 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1324 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-11-12 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1325 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-11-12 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-1326 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-11-12 | Thursday | 13:00 | 14:00 | 60 | small-group session | Scheduled |
| TS-1327 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-11-12 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1328 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-11-12 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1329 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-11-12 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-1330 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-11-12 | Thursday | 14:00 | 15:00 | 60 | small-group session | Scheduled |
| TS-1331 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-11-12 | Thursday | 14:00 | 16:00 | 120 | seminar | Scheduled |
| TS-1332 | Introduction to Computer Science | Room 4.01 — Research Laboratory | 4 | 2026-11-12 | Thursday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1333 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-11-12 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1334 | Applied Cyber Security | Room 5.53 — Research Laboratory | 5 | 2026-11-12 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1335 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-11-13 | Friday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1336 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-11-13 | Friday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1337 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-11-13 | Friday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1338 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-11-13 | Friday | 11:00 | 13:00 | 120 | computer lab session | Scheduled |
| TS-1339 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-11-13 | Friday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1340 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-11-13 | Friday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1341 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-11-13 | Friday | 13:00 | 15:00 | 120 | seminar | Scheduled |
| TS-1342 | Research Methods in Cyber Security | Room 2.17 — Research Laboratory | 2 | 2026-11-13 | Friday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-1343 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-11-13 | Friday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-1344 | Research Methods in Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-11-13 | Friday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1345 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-11-13 | Friday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1346 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-11-13 | Friday | 15:00 | 17:00 | 120 | small-group session | Scheduled |
| TS-1347 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-11-13 | Friday | 16:00 | 18:00 | 120 | computer lab session | Scheduled |
| TS-1348 | Research Methods in Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-11-13 | Friday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1349 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-11-13 | Friday | 16:00 | 18:00 | 120 | small-group session | Scheduled |
| TS-1350 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-11-13 | Friday | 16:00 | 17:00 | 60 | laboratory session | Scheduled |
| TS-1351 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-11-16 | Monday | 09:00 | 11:00 | 120 | seminar | Scheduled |
| TS-1352 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-11-16 | Monday | 09:00 | 10:00 | 60 | laboratory session | Scheduled |
| TS-1353 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-11-16 | Monday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1354 | Applied Software Engineering | Room 5.03 — Research Laboratory | 5 | 2026-11-16 | Monday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1355 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-11-16 | Monday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1356 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-11-16 | Monday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1357 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-11-16 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1358 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-11-16 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1359 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-11-16 | Monday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1360 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-11-16 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1361 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-11-16 | Monday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1362 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-11-16 | Monday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-1363 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-11-16 | Monday | 14:00 | 15:00 | 60 | small-group session | Scheduled |
| TS-1364 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-11-16 | Monday | 14:00 | 15:00 | 60 | laboratory session | Scheduled |
| TS-1365 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-11-16 | Monday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1366 | Applied Software Engineering | Room 3.04 — Research Laboratory | 3 | 2026-11-16 | Monday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-1367 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-11-16 | Monday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-1368 | Introduction to Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-11-16 | Monday | 16:00 | 17:00 | 60 | laboratory session | Scheduled |
| TS-1369 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-11-16 | Monday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1370 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-11-17 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1371 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-11-17 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1372 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-11-17 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Scheduled |
| TS-1373 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-11-17 | Tuesday | 10:00 | 12:00 | 120 | seminar | Scheduled |
| TS-1374 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-11-17 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1375 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-11-17 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1376 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-11-17 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1377 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-11-17 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1378 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-11-17 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1379 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-11-17 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-1380 | Advanced Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-11-17 | Tuesday | 14:00 | 15:00 | 60 | laboratory session | Scheduled |
| TS-1381 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-11-17 | Tuesday | 15:00 | 17:00 | 120 | seminar | Scheduled |
| TS-1382 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-11-17 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-1383 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-11-17 | Tuesday | 16:00 | 18:00 | 120 | seminar | Scheduled |
| TS-1384 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-11-17 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1385 | Applied Cyber Security | Room 5.17 — Meeting Room | 5 | 2026-11-17 | Tuesday | 16:00 | 18:00 | 120 | small-group session | Scheduled |
| TS-1386 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-11-18 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Scheduled |
| TS-1387 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-11-18 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Scheduled |
| TS-1388 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-11-18 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Scheduled |
| TS-1389 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-11-18 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1390 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-11-18 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Scheduled |
| TS-1391 | Foundations of Machine Learning | Room 4.56 — Research Laboratory | 4 | 2026-11-18 | Wednesday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-1392 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-11-18 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-1393 | Research Methods in Cyber Security | Room 2.53 — Research Laboratory | 2 | 2026-11-18 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1394 | Introduction to Cyber Security | Room 3.03 — Research Laboratory | 3 | 2026-11-18 | Wednesday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-1395 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-11-18 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1396 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-11-18 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Scheduled |
| TS-1397 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-11-18 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Scheduled |
| TS-1398 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-11-19 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Scheduled |
| TS-1399 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-11-19 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1400 | Advanced Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-11-19 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1401 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-11-19 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Scheduled |
| TS-1402 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-11-19 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1403 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-11-19 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1404 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-11-19 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Scheduled |
| TS-1405 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-11-19 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1406 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-11-19 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1407 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-11-19 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1408 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-11-19 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-1409 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-11-19 | Thursday | 13:00 | 14:00 | 60 | small-group session | Scheduled |
| TS-1410 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-11-19 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1411 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-11-19 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1412 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-11-19 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-1413 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-11-19 | Thursday | 14:00 | 15:00 | 60 | small-group session | Scheduled |
| TS-1414 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-11-19 | Thursday | 14:00 | 16:00 | 120 | seminar | Scheduled |
| TS-1415 | Introduction to Computer Science | Room 4.01 — Research Laboratory | 4 | 2026-11-19 | Thursday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1416 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-11-19 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1417 | Applied Cyber Security | Room 5.53 — Research Laboratory | 5 | 2026-11-19 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1418 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-11-20 | Friday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1419 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-11-20 | Friday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1420 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-11-20 | Friday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1421 | Foundations of Human-Computer Interaction | Room 4.19 — Research Laboratory | 4 | 2026-11-20 | Friday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1422 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-11-20 | Friday | 11:00 | 13:00 | 120 | computer lab session | Scheduled |
| TS-1423 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-11-20 | Friday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1424 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-11-20 | Friday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1425 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-11-20 | Friday | 13:00 | 15:00 | 120 | seminar | Scheduled |
| TS-1426 | Research Methods in Cyber Security | Room 2.17 — Research Laboratory | 2 | 2026-11-20 | Friday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-1427 | Research Methods in Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-11-20 | Friday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1428 | Introduction to Computer Science | Room 3.57 — Research Laboratory | 3 | 2026-11-20 | Friday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1429 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-11-20 | Friday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1430 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-11-20 | Friday | 15:00 | 17:00 | 120 | small-group session | Scheduled |
| TS-1431 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-11-20 | Friday | 16:00 | 18:00 | 120 | computer lab session | Scheduled |
| TS-1432 | Research Methods in Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-11-20 | Friday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1433 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-11-20 | Friday | 16:00 | 17:00 | 60 | laboratory session | Scheduled |
| TS-1434 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-11-23 | Monday | 09:00 | 11:00 | 120 | seminar | Scheduled |
| TS-1435 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-11-23 | Monday | 10:00 | 12:00 | 120 | seminar | Scheduled |
| TS-1436 | Foundations of Data Analysis | Room 3.16 — Meeting Room | 3 | 2026-11-23 | Monday | 10:00 | 12:00 | 120 | small-group session | Scheduled |
| TS-1437 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-11-23 | Monday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1438 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-11-23 | Monday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1439 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-11-23 | Monday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1440 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-11-23 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1441 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-11-23 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1442 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-11-23 | Monday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1443 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-11-23 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1444 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-11-23 | Monday | 13:00 | 15:00 | 120 | seminar | Scheduled |
| TS-1445 | Introduction to Software Engineering | Room 4.13 — Seminar Room | 4 | 2026-11-23 | Monday | 13:00 | 14:00 | 60 | seminar | Scheduled |
| TS-1446 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-11-23 | Monday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1447 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-11-23 | Monday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-1448 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-11-23 | Monday | 14:00 | 15:00 | 60 | small-group session | Scheduled |
| TS-1449 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-11-23 | Monday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1450 | Applied Software Engineering | Room 3.04 — Research Laboratory | 3 | 2026-11-23 | Monday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-1451 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-11-23 | Monday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-1452 | Introduction to Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-11-23 | Monday | 16:00 | 17:00 | 60 | laboratory session | Scheduled |
| TS-1453 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-11-23 | Monday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1454 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-11-24 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1455 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-11-24 | Tuesday | 10:00 | 12:00 | 120 | seminar | Scheduled |
| TS-1456 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-11-24 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1457 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-11-24 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1458 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-11-24 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1459 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-11-24 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1460 | Advanced Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-11-24 | Tuesday | 14:00 | 15:00 | 60 | laboratory session | Scheduled |
| TS-1461 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-11-24 | Tuesday | 15:00 | 17:00 | 120 | seminar | Scheduled |
| TS-1462 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-11-24 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1463 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-11-24 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-1464 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-11-24 | Tuesday | 16:00 | 18:00 | 120 | seminar | Scheduled |
| TS-1465 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-11-24 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1466 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-11-25 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Scheduled |
| TS-1467 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-11-25 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Scheduled |
| TS-1468 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-11-25 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Scheduled |
| TS-1469 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-11-25 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1470 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-11-25 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Scheduled |
| TS-1471 | Introduction to Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-11-25 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1472 | Foundations of Machine Learning | Room 4.56 — Research Laboratory | 4 | 2026-11-25 | Wednesday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-1473 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-11-25 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Scheduled |
| TS-1474 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-11-25 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-1475 | Research Methods in Cyber Security | Room 2.53 — Research Laboratory | 2 | 2026-11-25 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1476 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-11-25 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1477 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-11-25 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Scheduled |
| TS-1478 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-11-26 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Scheduled |
| TS-1479 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-11-26 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1480 | Advanced Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-11-26 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1481 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-11-26 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Scheduled |
| TS-1482 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-11-26 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1483 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-11-26 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1484 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-11-26 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Scheduled |
| TS-1485 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-11-26 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1486 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-11-26 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1487 | Applied Computer Science | Room 4.05 — Computer Laboratory | 4 | 2026-11-26 | Thursday | 11:00 | 13:00 | 120 | computer lab session | Scheduled |
| TS-1488 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-11-26 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1489 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-11-26 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1490 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-11-26 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-1491 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-11-26 | Thursday | 13:00 | 14:00 | 60 | small-group session | Scheduled |
| TS-1492 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-11-26 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1493 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-11-26 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1494 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-11-26 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-1495 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-11-26 | Thursday | 14:00 | 15:00 | 60 | small-group session | Scheduled |
| TS-1496 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-11-26 | Thursday | 14:00 | 16:00 | 120 | seminar | Scheduled |
| TS-1497 | Introduction to Computer Science | Room 4.01 — Research Laboratory | 4 | 2026-11-26 | Thursday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1498 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-11-26 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1499 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-11-27 | Friday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1500 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-11-27 | Friday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1501 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-11-27 | Friday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1502 | Foundations of Human-Computer Interaction | Room 4.19 — Research Laboratory | 4 | 2026-11-27 | Friday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1503 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-11-27 | Friday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1504 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-11-27 | Friday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1505 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-11-27 | Friday | 13:00 | 15:00 | 120 | seminar | Scheduled |
| TS-1506 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-11-27 | Friday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-1507 | Research Methods in Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-11-27 | Friday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1508 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-11-27 | Friday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1509 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-11-27 | Friday | 15:00 | 17:00 | 120 | small-group session | Scheduled |
| TS-1510 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-11-27 | Friday | 16:00 | 18:00 | 120 | computer lab session | Scheduled |
| TS-1511 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-11-27 | Friday | 16:00 | 18:00 | 120 | small-group session | Scheduled |
| TS-1512 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-11-27 | Friday | 16:00 | 17:00 | 60 | laboratory session | Scheduled |
| TS-1513 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-11-30 | Monday | 09:00 | 11:00 | 120 | seminar | Scheduled |
| TS-1514 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-11-30 | Monday | 09:00 | 10:00 | 60 | laboratory session | Scheduled |
| TS-1515 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-11-30 | Monday | 10:00 | 12:00 | 120 | seminar | Scheduled |
| TS-1516 | Foundations of Data Analysis | Room 3.16 — Meeting Room | 3 | 2026-11-30 | Monday | 10:00 | 12:00 | 120 | small-group session | Scheduled |
| TS-1517 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-11-30 | Monday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1518 | Applied Software Engineering | Room 5.03 — Research Laboratory | 5 | 2026-11-30 | Monday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1519 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-11-30 | Monday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1520 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-11-30 | Monday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1521 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-11-30 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1522 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-11-30 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1523 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-11-30 | Monday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1524 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-11-30 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1525 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-11-30 | Monday | 13:00 | 15:00 | 120 | seminar | Scheduled |
| TS-1526 | Introduction to Software Engineering | Room 4.13 — Seminar Room | 4 | 2026-11-30 | Monday | 13:00 | 14:00 | 60 | seminar | Scheduled |
| TS-1527 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-11-30 | Monday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1528 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-11-30 | Monday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-1529 | Advanced Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-11-30 | Monday | 14:00 | 15:00 | 60 | small-group session | Scheduled |
| TS-1530 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-11-30 | Monday | 14:00 | 15:00 | 60 | laboratory session | Scheduled |
| TS-1531 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-11-30 | Monday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1532 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-11-30 | Monday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-1533 | Introduction to Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-11-30 | Monday | 16:00 | 17:00 | 60 | laboratory session | Scheduled |
| TS-1534 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-11-30 | Monday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1535 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-12-01 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1536 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-12-01 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1537 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-12-01 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Scheduled |
| TS-1538 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-12-01 | Tuesday | 10:00 | 12:00 | 120 | seminar | Scheduled |
| TS-1539 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-12-01 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1540 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-12-01 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1541 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-12-01 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1542 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-12-01 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1543 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-12-01 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-1544 | Advanced Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-12-01 | Tuesday | 14:00 | 15:00 | 60 | laboratory session | Scheduled |
| TS-1545 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-12-01 | Tuesday | 15:00 | 17:00 | 120 | seminar | Scheduled |
| TS-1546 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-12-01 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1547 | Introduction to Cyber Security | Room 5.05 — Research Laboratory | 5 | 2026-12-01 | Tuesday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-1548 | Introduction to Human-Computer Interaction | Room 4.13 — Seminar Room | 4 | 2026-12-01 | Tuesday | 16:00 | 18:00 | 120 | seminar | Scheduled |
| TS-1549 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-12-01 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1550 | Applied Cyber Security | Room 5.17 — Meeting Room | 5 | 2026-12-01 | Tuesday | 16:00 | 18:00 | 120 | small-group session | Scheduled |
| TS-1551 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-12-02 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Scheduled |
| TS-1552 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-12-02 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Scheduled |
| TS-1553 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-12-02 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1554 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-12-02 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Scheduled |
| TS-1555 | Introduction to Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-12-02 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1556 | Foundations of Machine Learning | Room 4.56 — Research Laboratory | 4 | 2026-12-02 | Wednesday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-1557 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-12-02 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Scheduled |
| TS-1558 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-12-02 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-1559 | Research Methods in Cyber Security | Room 2.53 — Research Laboratory | 2 | 2026-12-02 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1560 | Introduction to Cyber Security | Room 3.03 — Research Laboratory | 3 | 2026-12-02 | Wednesday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-1561 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-12-02 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1562 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-12-02 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Scheduled |
| TS-1563 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-12-02 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Scheduled |
| TS-1564 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-12-03 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Scheduled |
| TS-1565 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-12-03 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1566 | Advanced Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-12-03 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1567 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-12-03 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Scheduled |
| TS-1568 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-12-03 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1569 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-12-03 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1570 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-12-03 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Scheduled |
| TS-1571 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-12-03 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1572 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-12-03 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1573 | Applied Computer Science | Room 3.58 — Research Laboratory | 3 | 2026-12-03 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1574 | Applied Computer Science | Room 4.05 — Computer Laboratory | 4 | 2026-12-03 | Thursday | 11:00 | 13:00 | 120 | computer lab session | Scheduled |
| TS-1575 | Foundations of Software Engineering | Room 5.06 — Research Laboratory | 5 | 2026-12-03 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1576 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-12-03 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1577 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-12-03 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-1578 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-12-03 | Thursday | 13:00 | 14:00 | 60 | small-group session | Scheduled |
| TS-1579 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-12-03 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1580 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-12-03 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1581 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-12-03 | Thursday | 14:00 | 15:00 | 60 | small-group session | Scheduled |
| TS-1582 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-12-03 | Thursday | 14:00 | 16:00 | 120 | seminar | Scheduled |
| TS-1583 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-12-03 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1584 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-12-04 | Friday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1585 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-12-04 | Friday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1586 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-12-04 | Friday | 11:00 | 13:00 | 120 | computer lab session | Scheduled |
| TS-1587 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-12-04 | Friday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1588 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-12-04 | Friday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1589 | Research Methods in Cyber Security | Room 2.17 — Research Laboratory | 2 | 2026-12-04 | Friday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-1590 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-12-04 | Friday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-1591 | Research Methods in Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-12-04 | Friday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1592 | Introduction to Computer Science | Room 3.57 — Research Laboratory | 3 | 2026-12-04 | Friday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1593 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-12-04 | Friday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1594 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-12-04 | Friday | 15:00 | 17:00 | 120 | small-group session | Scheduled |
| TS-1595 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-12-04 | Friday | 16:00 | 18:00 | 120 | computer lab session | Scheduled |
| TS-1596 | Research Methods in Data Analysis | Room 2.20 — Research Laboratory | 2 | 2026-12-04 | Friday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1597 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-12-04 | Friday | 16:00 | 18:00 | 120 | small-group session | Scheduled |
| TS-1598 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-12-04 | Friday | 16:00 | 17:00 | 60 | laboratory session | Scheduled |
| TS-1599 | Applied Software Engineering | Room 2.15 — Seminar Room | 2 | 2026-12-07 | Monday | 09:00 | 11:00 | 120 | seminar | Scheduled |
| TS-1600 | Research Methods in Data Analysis | Room 5.61 — Research Laboratory | 5 | 2026-12-07 | Monday | 09:00 | 10:00 | 60 | laboratory session | Scheduled |
| TS-1601 | Advanced Computer Science | Room 1.26 — Conference/Seminar Room | 1 | 2026-12-07 | Monday | 10:00 | 12:00 | 120 | seminar | Scheduled |
| TS-1602 | Advanced Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-12-07 | Monday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1603 | Applied Software Engineering | Room 5.03 — Research Laboratory | 5 | 2026-12-07 | Monday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1604 | Applied Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-12-07 | Monday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1605 | Introduction to Human-Computer Interaction | Room 3.01 — Research Laboratory | 3 | 2026-12-07 | Monday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1606 | Applied Software Engineering | Room 3.57 — Research Laboratory | 3 | 2026-12-07 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1607 | Advanced Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-12-07 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1608 | Introduction to Computer Science | Room 5.52 — Research Laboratory | 5 | 2026-12-07 | Monday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1609 | Introduction to Data Analysis | Room 1.26 — Conference/Seminar Room | 1 | 2026-12-07 | Monday | 13:00 | 15:00 | 120 | seminar | Scheduled |
| TS-1610 | Introduction to Software Engineering | Room 4.13 — Seminar Room | 4 | 2026-12-07 | Monday | 13:00 | 14:00 | 60 | seminar | Scheduled |
| TS-1611 | Applied Cyber Security | Room 4.18 — Research Laboratory | 4 | 2026-12-07 | Monday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1612 | Advanced Systems Architecture | Room 5.06 — Research Laboratory | 5 | 2026-12-07 | Monday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-1613 | Advanced Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-12-07 | Monday | 14:00 | 15:00 | 60 | laboratory session | Scheduled |
| TS-1614 | Applied Systems Architecture | Room 2.54 — Research Laboratory | 2 | 2026-12-07 | Monday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1615 | Applied Software Engineering | Room 3.04 — Research Laboratory | 3 | 2026-12-07 | Monday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-1616 | Advanced Human-Computer Interaction | Room 4.01 — Research Laboratory | 4 | 2026-12-07 | Monday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-1617 | Introduction to Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-12-07 | Monday | 16:00 | 17:00 | 60 | laboratory session | Scheduled |
| TS-1618 | Advanced Machine Learning | Room 3.04 — Research Laboratory | 3 | 2026-12-07 | Monday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1619 | Applied Systems Architecture | Room 3.53 — Research Laboratory | 3 | 2026-12-08 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1620 | Research Methods in Cyber Security | Room 4.55 — Research Laboratory | 4 | 2026-12-08 | Tuesday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1621 | Applied Human-Computer Interaction | Room 4.58 — Research Laboratory | 4 | 2026-12-08 | Tuesday | 09:00 | 10:00 | 60 | laboratory session | Scheduled |
| TS-1622 | Foundations of Machine Learning | Room 2.15 — Seminar Room | 2 | 2026-12-08 | Tuesday | 10:00 | 12:00 | 120 | seminar | Scheduled |
| TS-1623 | Introduction to Data Analysis | Room 2.17 — Research Laboratory | 2 | 2026-12-08 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1624 | Applied Cyber Security | Room 3.04 — Research Laboratory | 3 | 2026-12-08 | Tuesday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1625 | Applied Computer Science | Room 3.54 — Research Laboratory | 3 | 2026-12-08 | Tuesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1626 | Advanced Systems Architecture | Room 4.58 — Research Laboratory | 4 | 2026-12-08 | Tuesday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1627 | Introduction to Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-12-08 | Tuesday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1628 | Advanced Machine Learning | Room 2.05 — Research Laboratory | 2 | 2026-12-08 | Tuesday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-1629 | Applied Cyber Security | Room 2.15 — Seminar Room | 2 | 2026-12-08 | Tuesday | 15:00 | 17:00 | 120 | seminar | Scheduled |
| TS-1630 | Research Methods in Data Analysis | Room 2.21 — Research Laboratory | 2 | 2026-12-08 | Tuesday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1631 | Applied Computer Science | Room 5.03 — Research Laboratory | 5 | 2026-12-08 | Tuesday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1632 | Introduction to Software Engineering | Room 3.05 — Computer Laboratory | 3 | 2026-12-09 | Wednesday | 09:00 | 11:00 | 120 | computer lab session | Scheduled |
| TS-1633 | Foundations of Machine Learning | Room 3.26 — Meeting Room | 3 | 2026-12-09 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Scheduled |
| TS-1634 | Research Methods in Software Engineering | Room 5.17 — Meeting Room | 5 | 2026-12-09 | Wednesday | 09:00 | 10:00 | 60 | small-group session | Scheduled |
| TS-1635 | Foundations of Data Analysis | Room 3.01 — Research Laboratory | 3 | 2026-12-09 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1636 | Applied Human-Computer Interaction | Room 3.16 — Meeting Room | 3 | 2026-12-09 | Wednesday | 10:00 | 12:00 | 120 | small-group session | Scheduled |
| TS-1637 | Introduction to Computer Science | Room 5.61 — Research Laboratory | 5 | 2026-12-09 | Wednesday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1638 | Research Methods in Cyber Security | Room 1.06 — Computer Laboratory | 1 | 2026-12-09 | Wednesday | 14:00 | 16:00 | 120 | computer lab session | Scheduled |
| TS-1639 | Advanced Software Engineering | Room 5.05 — Research Laboratory | 5 | 2026-12-09 | Wednesday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-1640 | Research Methods in Cyber Security | Room 2.53 — Research Laboratory | 2 | 2026-12-09 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1641 | Introduction to Cyber Security | Room 3.03 — Research Laboratory | 3 | 2026-12-09 | Wednesday | 15:00 | 16:00 | 60 | laboratory session | Scheduled |
| TS-1642 | Foundations of Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-12-09 | Wednesday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1643 | Research Methods in Systems Architecture | Room 2.08 — Computer Laboratory | 2 | 2026-12-09 | Wednesday | 16:00 | 17:00 | 60 | computer lab session | Scheduled |
| TS-1644 | Introduction to Machine Learning | Room 3.51 — Research Laboratory | 3 | 2026-12-09 | Wednesday | 16:00 | 17:00 | 60 | laboratory session | Scheduled |
| TS-1645 | Foundations of Human-Computer Interaction | Room 1.06 — Computer Laboratory | 1 | 2026-12-10 | Thursday | 09:00 | 10:00 | 60 | computer lab session | Scheduled |
| TS-1646 | Research Methods in Human-Computer Interaction | Room 2.52 — Research Laboratory | 2 | 2026-12-10 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1647 | Advanced Machine Learning | Room 3.58 — Research Laboratory | 3 | 2026-12-10 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1648 | Introduction to Human-Computer Interaction | Room 4.22 — Research Laboratory | 4 | 2026-12-10 | Thursday | 09:00 | 10:00 | 60 | laboratory session | Scheduled |
| TS-1649 | Research Methods in Data Analysis | Room 4.58 — Research Laboratory | 4 | 2026-12-10 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1650 | Advanced Data Analysis | Room 5.52 — Research Laboratory | 5 | 2026-12-10 | Thursday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1651 | Introduction to Data Analysis | Room 1.07 — Computer Laboratory | 1 | 2026-12-10 | Thursday | 10:00 | 11:00 | 60 | computer lab session | Scheduled |
| TS-1652 | Introduction to Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-12-10 | Thursday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1653 | Advanced Human-Computer Interaction | Room 2.21 — Research Laboratory | 2 | 2026-12-10 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1654 | Applied Computer Science | Room 3.58 — Research Laboratory | 3 | 2026-12-10 | Thursday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1655 | Applied Computer Science | Room 4.05 — Computer Laboratory | 4 | 2026-12-10 | Thursday | 11:00 | 13:00 | 120 | computer lab session | Scheduled |
| TS-1656 | Introduction to Machine Learning | Room 2.17 — Research Laboratory | 2 | 2026-12-10 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1657 | Applied Software Engineering | Room 2.22 — Research Laboratory | 2 | 2026-12-10 | Thursday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-1658 | Foundations of Human-Computer Interaction | Room 3.27 — Meeting Room | 3 | 2026-12-10 | Thursday | 13:00 | 14:00 | 60 | small-group session | Scheduled |
| TS-1659 | Research Methods in Data Analysis | Room 3.51 — Research Laboratory | 3 | 2026-12-10 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1660 | Advanced Data Analysis | Room 4.21 — Research Laboratory | 4 | 2026-12-10 | Thursday | 13:00 | 15:00 | 120 | laboratory session | Scheduled |
| TS-1661 | Advanced Data Analysis | Room 2.54 — Research Laboratory | 2 | 2026-12-10 | Thursday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-1662 | Introduction to Computer Science | Room 3.27 — Meeting Room | 3 | 2026-12-10 | Thursday | 14:00 | 15:00 | 60 | small-group session | Scheduled |
| TS-1663 | Research Methods in Data Analysis | Room 5.16 — Seminar / Conference Room | 5 | 2026-12-10 | Thursday | 14:00 | 16:00 | 120 | seminar | Scheduled |
| TS-1664 | Introduction to Computer Science | Room 4.01 — Research Laboratory | 4 | 2026-12-10 | Thursday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1665 | Applied Data Analysis | Room 3.03 — Research Laboratory | 3 | 2026-12-10 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1666 | Applied Cyber Security | Room 5.53 — Research Laboratory | 5 | 2026-12-10 | Thursday | 16:00 | 18:00 | 120 | laboratory session | Scheduled |
| TS-1667 | Applied Machine Learning | Room 5.52 — Research Laboratory | 5 | 2026-12-11 | Friday | 09:00 | 11:00 | 120 | laboratory session | Scheduled |
| TS-1668 | Applied Cyber Security | Room 2.20 — Research Laboratory | 2 | 2026-12-11 | Friday | 10:00 | 11:00 | 60 | laboratory session | Scheduled |
| TS-1669 | Advanced Human-Computer Interaction | Room 2.54 — Research Laboratory | 2 | 2026-12-11 | Friday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1670 | Foundations of Human-Computer Interaction | Room 4.19 — Research Laboratory | 4 | 2026-12-11 | Friday | 10:00 | 12:00 | 120 | laboratory session | Scheduled |
| TS-1671 | Foundations of Machine Learning | Room 1.07 — Computer Laboratory | 1 | 2026-12-11 | Friday | 11:00 | 13:00 | 120 | computer lab session | Scheduled |
| TS-1672 | Applied Computer Science | Room 4.21 — Research Laboratory | 4 | 2026-12-11 | Friday | 11:00 | 12:00 | 60 | laboratory session | Scheduled |
| TS-1673 | Applied Computer Science | Room 4.56 — Research Laboratory | 4 | 2026-12-11 | Friday | 11:00 | 13:00 | 120 | laboratory session | Scheduled |
| TS-1674 | Applied Human-Computer Interaction | Room 1.26 — Conference/Seminar Room | 1 | 2026-12-11 | Friday | 13:00 | 15:00 | 120 | seminar | Scheduled |
| TS-1675 | Research Methods in Cyber Security | Room 2.17 — Research Laboratory | 2 | 2026-12-11 | Friday | 13:00 | 14:00 | 60 | laboratory session | Scheduled |
| TS-1676 | Research Methods in Computer Science | Room 2.22 — Research Laboratory | 2 | 2026-12-11 | Friday | 14:00 | 16:00 | 120 | laboratory session | Scheduled |
| TS-1677 | Introduction to Computer Science | Room 3.57 — Research Laboratory | 3 | 2026-12-11 | Friday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1678 | Advanced Computer Science | Room 4.55 — Research Laboratory | 4 | 2026-12-11 | Friday | 15:00 | 17:00 | 120 | laboratory session | Scheduled |
| TS-1679 | Research Methods in Systems Architecture | Room 5.17 — Meeting Room | 5 | 2026-12-11 | Friday | 15:00 | 17:00 | 120 | small-group session | Scheduled |
| TS-1680 | Foundations of Machine Learning | Room 1.06 — Computer Laboratory | 1 | 2026-12-11 | Friday | 16:00 | 18:00 | 120 | computer lab session | Scheduled |
| TS-1681 | Introduction to Machine Learning | Room 3.16 — Meeting Room | 3 | 2026-12-11 | Friday | 16:00 | 18:00 | 120 | small-group session | Scheduled |
| TS-1682 | Foundations of Computer Science | Room 4.59 — Research Laboratory | 4 | 2026-12-11 | Friday | 16:00 | 17:00 | 60 | laboratory session | Scheduled |

**1682 sessions across 44 rooms. 412 are still to come and 1270 have already run. The register covers 2026-07-27 to 2026-12-11.**
