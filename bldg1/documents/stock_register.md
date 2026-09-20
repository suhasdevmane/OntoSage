---
record_type: stock_item
owner: "Estates Operations Manager"
authority: "Cardiff University Estates - Stores and Supplies"
source_system: "Stores and Stock Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
simulated: true
tables:
  - name: "Stock register"
    maps_to: stock_items
---

# Stores and Stock Register - Abacws Building

## What this register records, and what it does not

The asset register says what plant the building has. The service schedule says when it is
serviced. Neither says whether the **filter, belt, cartridge or adapter** needed for the next
visit is actually on the shelf, where the shelf is, or who to ask - which is what a
contractor about to mobilise, a caretaker planning a round and a lecturer wanting to borrow an
adapter all need to know.

This register records **stock lines**: one line per kind of item, held in one store, with the
quantity on hand, the level below which it is reordered, and who is accountable for it. Four
kinds are kept apart because they answer different questions:

- **consumable** - used up in service: soap, liners, filters, batteries, toner.
- **spare** - a replacement part held against a named asset or system: a belt set, a seal
  kit, a spare access point.
- **loan** - equipment that is lent and comes back: presenter adapters, clickers, assistive
  listening receivers. Quantity on hand is what is in the store now; anything out on loan is
  stated in the note, never counted as stock.
- **surplus** - withdrawn from service and available for reuse before disposal. Its minimum
  is always nought.

Five points about how to read it:

- **Status follows the numbers.** A line is *In stock* only when the quantity on hand is at
  or above its minimum. *Low* and *On order* are below it, and *On order* names the delivery
  date. A shortage is therefore a comparison the reader can check, not an adjective.
- **Quantities are as counted, on the date counted.** `last_counted` is when somebody
  counted the shelf. Stock that has not been counted this month is a claim, not a count.
- **Nothing safety-critical is held here.** Fire extinguishers, emergency lighting parts,
  first-aid supplies and hazardous chemicals sit under their own controls and are deliberately
  not recorded as ordinary stock. A question about them is not answered from this register.
- **Stores, not people.** A loan line says how many are out, never who has them.
- **`next_due` means what the status says it means.** For a line *On order* it is the
  delivery date; for a line *Low* it is the reorder date; for stock held for a scheduled task,
  such as the air handling unit filter set, it is the date that task next uses it.

## Stock register

| code | item | kind | category | store | on_hand | minimum | unit | used_for | supplier | lead_time_days | last_counted | next_due | status | accountable_role | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| STK-01 | Hand soap refill cartridges, 1 L | consumable | Cleaning | Level 0 caretaker store | 84 | 60 | cartridges | Washroom soap dispensers, all floors | Clearview Facilities | 5 | 2026-09-15 | 2026-09-29 | In stock | Caretaking Supervisor | Use has run ahead of forecast since the 2026-09-11 open day (see cost line CL-2026-011). |
| STK-02 | Toilet tissue, 2-ply, case of 36 rolls | consumable | Cleaning | Level 0 caretaker store | 22 | 30 | cases | Washrooms, all floors | Clearview Facilities | 5 | 2026-09-15 | 2026-09-21 | On order | Caretaking Supervisor | Below the minimum; delivery expected 2026-09-21. |
| STK-03 | Paper hand towels, case of 20 packs | consumable | Cleaning | Level 0 caretaker store | 35 | 24 | cases | Washrooms, all floors | Clearview Facilities | 5 | 2026-09-15 | | In stock | Caretaking Supervisor | |
| STK-04 | Fragrance-free floor cleaner concentrate, 5 L | consumable | Cleaning | Level 0 caretaker store | 14 | 10 | containers | Hard floors, all floors; the scent-aware policy applies | Clearview Facilities | 5 | 2026-09-15 | | In stock | Caretaking Supervisor | |
| STK-05 | Fragrance-free washroom sanitiser, 750 ml | consumable | Cleaning | Level 0 caretaker store | 40 | 36 | bottles | Washrooms, all floors | Clearview Facilities | 5 | 2026-09-15 | | In stock | Caretaking Supervisor | |
| STK-06 | Microfibre cloths, colour-coded pack of 10 | consumable | Cleaning | Level 0 caretaker store | 18 | 12 | packs | Washrooms and general cleaning | Clearview Facilities | 5 | 2026-09-15 | | In stock | Caretaking Supervisor | |
| STK-07 | Bin liners, general waste, roll of 25 | consumable | Waste | External bin store | 120 | 80 | rolls | General waste and mixed recycling bins | Clearview Facilities | 5 | 2026-09-15 | | In stock | Waste and Recycling Officer | |
| STK-08 | Compostable liners for food waste caddies, 60 L, pack of 50 | consumable | Waste | External bin store | 18 | 40 | packs | Food waste caddies at each station | Regional Waste Partners | 7 | 2026-09-15 | 2026-09-23 | Low | Waste and Recycling Officer | Below the minimum after the 2026-09-11 open day; the atrium food caddy is already over its fill threshold in the collection point register. |
| STK-09 | Tamper-evident sacks for confidential paper | consumable | Waste | External bin store | 30 | 20 | sacks | Confidential paper shredding console | Regional Waste Partners | 7 | 2026-09-15 | | In stock | Waste and Recycling Officer | |
| STK-10 | AHU panel filter set, one change of all six units | consumable | HVAC | Level 0 plant room stores | 1 | 1 | sets | All six air handling units, quarterly change (SVC-11) | Caldicot Plant Services | 14 | 2026-09-08 | 2026-11-17 | In stock | M and E Maintenance Supervisor | One set is held. The next change is due 2026-11-17, so a replacement set must be ordered as soon as this one is used. |
| STK-11 | AHU fan drive belt set | spare | HVAC | Level 0 plant room stores | 1 | 2 | sets | AHU supply and extract fan drives | Caldicot Plant Services | 10 | 2026-09-08 | 2026-09-25 | On order | M and E Maintenance Supervisor | One set was used on the AHU-02 belt change under permit PTW-2026-0417 (2026-08-30); a replacement is on order for 2026-09-25. |
| STK-12 | Chilled water pump mechanical seal kit | spare | HVAC | Level 0 plant room stores | 1 | 1 | kits | Chiller Pump 1 and Chilled Water Pump 1 (AEP-008, AEP-009) | Meridian Mechanical Ltd | 21 | 2026-09-08 | | In stock | M and E Maintenance Supervisor | |
| STK-13 | Building management controller I/O module | spare | Controls | Level 0 plant room stores | 2 | 1 | modules | Building management system field controllers | Meridian Controls | 28 | 2026-09-08 | | In stock | M and E Maintenance Supervisor | Supplied under the BMS support contract CON-2024-002, which ends 2026-10-25. |
| STK-14 | LED batten lamp, 1200 mm | consumable | Lighting | Level 0 plant room stores | 26 | 20 | lamps | Corridor and open-plan luminaires | Tredegar Electrical | 7 | 2026-09-08 | | In stock | M and E Maintenance Supervisor | |
| STK-15 | Assistive listening receivers, portable, with headsets | loan | Audio-visual | Level 1 AV workshop | 8 | 10 | receivers | Lent for teaching sessions and events where a hearing loop is untested or unavailable | | | 2026-09-11 | | Low | AV Support Team Leader | Twelve receivers are held and four are out on loan. Below the number needed to cover every timetabled teaching room. |
| STK-16 | HDMI to USB-C adapters for presenters | loan | Audio-visual | Level 1 AV workshop | 15 | 12 | adapters | Presenter laptops | | | 2026-09-11 | | In stock | AV Support Team Leader | |
| STK-17 | DisplayPort to HDMI adapters for presenters | loan | Audio-visual | Level 1 AV workshop | 6 | 6 | adapters | Presenter laptops | | | 2026-09-11 | | In stock | AV Support Team Leader | |
| STK-18 | Wireless presentation clickers | loan | Audio-visual | Level 1 AV workshop | 9 | 6 | clickers | Lecture and seminar presenters | | | 2026-09-11 | | In stock | AV Support Team Leader | |
| STK-19 | Radio microphone batteries, AA, pack of 4 | consumable | Audio-visual | Level 1 AV workshop | 24 | 30 | packs | Radio and lapel microphones | | 3 | 2026-09-11 | 2026-09-22 | Low | AV Support Team Leader | Below the minimum; reorder due 2026-09-22. |
| STK-20 | HDMI cable, 5 m | spare | Audio-visual | Level 1 AV workshop | 30 | 20 | cables | Lectern and room inputs | | | 2026-09-11 | | In stock | AV Support Team Leader | |
| STK-21 | Patch leads, Cat6A, 1 m and 2 m | spare | IT | Level 2 comms room | 60 | 40 | leads | Structured cabling in all communications rooms | | | 2026-09-10 | | In stock | Network Infrastructure Lead | |
| STK-22 | Wi-Fi access point, spare unit | spare | IT | Level 2 comms room | 2 | 2 | units | Managed Wi-Fi, eduroam and CU_Guest | | 14 | 2026-09-10 | | In stock | Network Infrastructure Lead | |
| STK-23 | Access switch, 24-port PoE, spare unit | spare | IT | Level 2 comms room | 1 | 1 | units | Floor access switches | | 21 | 2026-09-10 | | In stock | Network Infrastructure Lead | |
| STK-24 | Toner cartridges for the multi-function devices | consumable | IT | Level 2 comms room | 12 | 8 | cartridges | Printing and scanning devices | | 5 | 2026-09-10 | | In stock | Network Infrastructure Lead | |
| STK-25 | Visitor pass cards and lanyards | consumable | Reception | Main entrance reception | 150 | 100 | sets | Visitor sign-in at the main reception | | 7 | 2026-09-16 | | In stock | Reception Supervisor | Visitors are issued a badge at sign-in. |
| STK-26 | Height-adjustable desks, surplus | surplus | Furniture | Ground floor goods store | 6 | 0 | desks | Available for redeployment across the university before disposal | | | 2026-09-04 | | Available for reuse | Estates Operations Manager | Withdrawn from a reconfigured office area. |
| STK-27 | Office chairs, surplus | surplus | Furniture | Ground floor goods store | 14 | 0 | chairs | Available for redeployment across the university before disposal | | | 2026-09-04 | | Available for reuse | Estates Operations Manager | |
| STK-28 | Mobile whiteboards, surplus | surplus | Furniture | Ground floor goods store | 4 | 0 | whiteboards | Available for redeployment across the university before disposal | | | 2026-09-04 | | Available for reuse | Estates Operations Manager | |
| STK-29 | Monitors, 24 inch, data-checked and withdrawn | surplus | IT | Ground floor goods store | 9 | 0 | monitors | Held for redeployment; anything unclaimed after 2026-10-31 goes to the WEEE stream (waste point WCP-017) | | | 2026-09-04 | | Available for reuse | Estates Operations Manager | |

**29 entries across 4 kinds - 14 consumables, 7 spares, 4 loan lines and 4 surplus lines - held in 7 stores. Five lines are below their minimum: three consumables (toilet tissue, food waste liners and radio microphone batteries), one spare (AHU fan drive belts) and one loan line (assistive listening receivers). Toilet tissue and the fan drive belts are on order with a delivery date; the receivers have no replenishment date at all.**
