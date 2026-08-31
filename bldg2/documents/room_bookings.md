---
record_type: booking
owner: "Room Booking Team"
authority: "BuildSys Estates"
source_system: "Room Booking System"
effective_from: 2025-08-31
version: "2026.34"
review_due: 2027-08-31
simulated: true
tables:
  - name: "Booking register"
    maps_to: bookings
---

# Room Booking Register — BuildSys Building

_**Synthetic demonstration record** — fictional history, not a real compliance document._

## What this register decides

The booking register is the AUTHORITATIVE source for whether a room is available. A room
with nobody in it is not an available room, and an occupancy sensor cannot tell the
difference — where the two disagree, both are reported and the room owner resolves it.

Organisers are recorded as roles or teams. This register holds no personal data, and a
question about who is in a room is answered by neither this register nor the sensors.

## Booking register

| reference | room | start | end | booked_by_role | expected_attendees | status |
|---|---|---|---|---|---|---|
| BK-2026-0001 | RM001A | 2026-08-24T09:00:00 | 2026-08-24T11:00:00 | Graduate School | 12 | Confirmed |
| BK-2026-0002 | RM001B | 2026-08-24T14:00:00 | 2026-08-24T16:00:00 | Teaching Team | 8 | Confirmed |
| BK-2026-0003 | RM002A | 2026-08-28T09:00:00 | 2026-08-28T11:00:00 | Industry Liaison | 30 | Provisional |
| BK-2026-0004 | RM002B | 2026-08-28T14:00:00 | 2026-08-28T16:00:00 | Estates Compliance | 6 | Confirmed |
| BK-2026-0005 | RM003 | 2026-08-30T09:00:00 | 2026-08-30T11:00:00 | School Office | 24 | Cancelled |
| BK-2026-0006 | RM004 | 2026-08-30T14:00:00 | 2026-08-30T16:00:00 | Research group (Smart Buildings) | 18 | Confirmed |
| BK-2026-0007 | RM001A | 2026-08-31T09:00:00 | 2026-08-31T11:00:00 | Graduate School | 12 | Confirmed |
| BK-2026-0008 | RM001B | 2026-08-31T14:00:00 | 2026-08-31T16:00:00 | Teaching Team | 8 | Confirmed |
| BK-2026-0009 | RM002A | 2026-09-01T09:00:00 | 2026-09-01T11:00:00 | Industry Liaison | 30 | Provisional |
| BK-2026-0010 | RM002B | 2026-09-01T14:00:00 | 2026-09-01T16:00:00 | Estates Compliance | 6 | Confirmed |
| BK-2026-0011 | RM003 | 2026-09-02T09:00:00 | 2026-09-02T11:00:00 | School Office | 24 | Cancelled |
| BK-2026-0012 | RM004 | 2026-09-02T14:00:00 | 2026-09-02T16:00:00 | Research group (Smart Buildings) | 18 | Confirmed |
| BK-2026-0013 | RM001A | 2026-09-05T09:00:00 | 2026-09-05T11:00:00 | Graduate School | 12 | Confirmed |
| BK-2026-0014 | RM001B | 2026-09-05T14:00:00 | 2026-09-05T16:00:00 | Teaching Team | 8 | Confirmed |
| BK-2026-0015 | RM002A | 2026-09-09T09:00:00 | 2026-09-09T11:00:00 | Industry Liaison | 30 | Provisional |
| BK-2026-0016 | RM002B | 2026-09-09T14:00:00 | 2026-09-09T16:00:00 | Estates Compliance | 6 | Confirmed |

## Changes

Bookings are created and cancelled in the booking system. This service reports them; it
cannot create, change or cancel one, and a cancelled booking is kept rather than deleted
so that a no-show can be told from a room that was never booked.
