---
record_type: waste_return
owner: "Waste and Recycling Officer"
authority: "Cardiff University Estates - Waste and Recycling"
source_system: "Waste Contractor Monthly Returns"
effective_from: 2026-03-01
version: "2026.9"
review_due: 2027-03-01
simulated: true
tables:
  - name: "Waste returns register"
    maps_to: waste_returns
---

# Waste and Recycling Monthly Returns - Abacws Building

## What this register records, and what it does not

The waste collection point register records **bins**: where each one is, what stream it is for, how full it is and when it is next emptied. It cannot say how much waste the building produced, because a bin's fill is a percentage of a container and not a weight.

This register records **tonnes**. It holds the monthly return the waste contractor issues under contract CON-2024-027 (Regional Waste Partners, which ends 2026-09-28): one line per stream per month, with the weight, how it was weighed, how it was treated and what share was diverted from landfill.

Four points about how to read it:

- **A month is not a figure until its return is issued.** The contractor issues each return after month end, so the latest complete month is always the one before the current month. September 2026 is shown as *Pending* with no weight; a question about *this month* has no issued answer, and the honest reply is the latest complete month with its date.
- **How a weight was obtained matters.** A bin-lift scale weight is measured per lift and summed; a weighbridge ticket and a delivery note are single measured weights; a weight *estimated from container volume* is an estimate and must be reported as one. One general-waste line in June is of that kind, because the vehicle scale was out of calibration.
- **Diverted share is per stream, and the building's share is weighted by tonnage.** It is not the average of the stream percentages. The weighted figure is the one to set beside the sustainability target for waste diverted from landfill (SUS-WASTE-2027).
- **A query is a status, not a figure to hide.** July's mixed recycling return differs from the contractor's invoice; both numbers are recorded in the note and the return weight is the one used.

Clinical sharps from the laboratories are collected under the clinical waste contract and do not appear here. Weights are for the whole building, not for a floor, a room or a day.

## Waste returns register

| code | name | month | period_start | period_end | stream | tonnes | diverted_pct | treatment | weighing | contractor | status | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WR-2026-03-GEN | General waste, March 2026 | 2026-03 | 2026-03-01 | 2026-03-31 | General waste | 3.10 | 84 | Energy from waste; residual to landfill | Bin-lift scale | Regional Waste Partners | Confirmed | Highest general waste of the six months. |
| WR-2026-03-MIX | Mixed recycling, March 2026 | 2026-03 | 2026-03-01 | 2026-03-31 | Mixed recycling | 1.50 | 96 | Materials recovery facility | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-03-PAP | Paper and card, March 2026 | 2026-03 | 2026-03-01 | 2026-03-31 | Paper and card | 0.58 | 100 | Paper mill | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-03-FOD | Food waste, March 2026 | 2026-03 | 2026-03-01 | 2026-03-31 | Food waste | 0.46 | 100 | Anaerobic digestion | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-03-CON | Confidential paper, March 2026 | 2026-03 | 2026-03-01 | 2026-03-31 | Confidential paper | 0.31 | 100 | Secure shred, then paper mill | Weighbridge ticket | Regional Waste Partners | Confirmed |  |
| WR-2026-03-WEE | WEEE, March 2026 | 2026-03 | 2026-03-01 | 2026-03-31 | WEEE | 0.08 | 100 | Licensed WEEE recycler | Delivery note | Regional Waste Partners | Confirmed |  |
| WR-2026-04-GEN | General waste, April 2026 | 2026-04 | 2026-04-01 | 2026-04-30 | General waste | 2.90 | 86 | Energy from waste; residual to landfill | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-04-MIX | Mixed recycling, April 2026 | 2026-04 | 2026-04-01 | 2026-04-30 | Mixed recycling | 1.40 | 97 | Materials recovery facility | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-04-PAP | Paper and card, April 2026 | 2026-04 | 2026-04-01 | 2026-04-30 | Paper and card | 0.52 | 100 | Paper mill | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-04-FOD | Food waste, April 2026 | 2026-04 | 2026-04-01 | 2026-04-30 | Food waste | 0.44 | 100 | Anaerobic digestion | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-04-CON | Confidential paper, April 2026 | 2026-04 | 2026-04-01 | 2026-04-30 | Confidential paper | 0.29 | 100 | Secure shred, then paper mill | Weighbridge ticket | Regional Waste Partners | Confirmed |  |
| WR-2026-04-WEE | WEEE, April 2026 | 2026-04 | 2026-04-01 | 2026-04-30 | WEEE | 0.06 | 100 | Licensed WEEE recycler | Delivery note | Regional Waste Partners | Confirmed |  |
| WR-2026-05-GEN | General waste, May 2026 | 2026-05 | 2026-05-01 | 2026-05-31 | General waste | 3.00 | 85 | Energy from waste; residual to landfill | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-05-MIX | Mixed recycling, May 2026 | 2026-05 | 2026-05-01 | 2026-05-31 | Mixed recycling | 1.55 | 96 | Materials recovery facility | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-05-PAP | Paper and card, May 2026 | 2026-05 | 2026-05-01 | 2026-05-31 | Paper and card | 0.60 | 100 | Paper mill | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-05-FOD | Food waste, May 2026 | 2026-05 | 2026-05-01 | 2026-05-31 | Food waste | 0.47 | 100 | Anaerobic digestion | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-05-CON | Confidential paper, May 2026 | 2026-05 | 2026-05-01 | 2026-05-31 | Confidential paper | 0.33 | 100 | Secure shred, then paper mill | Weighbridge ticket | Regional Waste Partners | Confirmed |  |
| WR-2026-05-WEE | WEEE, May 2026 | 2026-05 | 2026-05-01 | 2026-05-31 | WEEE | 0.11 | 100 | Licensed WEEE recycler | Delivery note | Regional Waste Partners | Confirmed |  |
| WR-2026-06-GEN | General waste, June 2026 | 2026-06 | 2026-06-01 | 2026-06-30 | General waste | 2.70 | 87 | Energy from waste; residual to landfill | Estimated from container volume | Regional Waste Partners | Confirmed | Vehicle scale was out of calibration for the month, so the weight is estimated from container volume; the contractor has not reissued it. |
| WR-2026-06-MIX | Mixed recycling, June 2026 | 2026-06 | 2026-06-01 | 2026-06-30 | Mixed recycling | 1.45 | 97 | Materials recovery facility | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-06-PAP | Paper and card, June 2026 | 2026-06 | 2026-06-01 | 2026-06-30 | Paper and card | 0.55 | 100 | Paper mill | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-06-FOD | Food waste, June 2026 | 2026-06 | 2026-06-01 | 2026-06-30 | Food waste | 0.41 | 100 | Anaerobic digestion | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-06-CON | Confidential paper, June 2026 | 2026-06 | 2026-06-01 | 2026-06-30 | Confidential paper | 0.35 | 100 | Secure shred, then paper mill | Weighbridge ticket | Regional Waste Partners | Confirmed | Highest of the six months; the June assessment period. |
| WR-2026-06-WEE | WEEE, June 2026 | 2026-06 | 2026-06-01 | 2026-06-30 | WEEE | 0.09 | 100 | Licensed WEEE recycler | Delivery note | Regional Waste Partners | Confirmed |  |
| WR-2026-07-GEN | General waste, July 2026 | 2026-07 | 2026-07-01 | 2026-07-31 | General waste | 1.90 | 88 | Energy from waste; residual to landfill | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-07-MIX | Mixed recycling, July 2026 | 2026-07 | 2026-07-01 | 2026-07-31 | Mixed recycling | 1.02 | 97 | Materials recovery facility | Bin-lift scale | Regional Waste Partners | Query | Return weight 1.02 t against 0.96 t on the invoice; the contractor has been asked to reconcile. The return weight is the one used here. |
| WR-2026-07-PAP | Paper and card, July 2026 | 2026-07 | 2026-07-01 | 2026-07-31 | Paper and card | 0.36 | 100 | Paper mill | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-07-FOD | Food waste, July 2026 | 2026-07 | 2026-07-01 | 2026-07-31 | Food waste | 0.30 | 100 | Anaerobic digestion | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-07-CON | Confidential paper, July 2026 | 2026-07 | 2026-07-01 | 2026-07-31 | Confidential paper | 0.22 | 100 | Secure shred, then paper mill | Weighbridge ticket | Regional Waste Partners | Confirmed |  |
| WR-2026-07-WEE | WEEE, July 2026 | 2026-07 | 2026-07-01 | 2026-07-31 | WEEE | 0.07 | 100 | Licensed WEEE recycler | Delivery note | Regional Waste Partners | Confirmed |  |
| WR-2026-08-GEN | General waste, August 2026 | 2026-08 | 2026-08-01 | 2026-08-31 | General waste | 1.70 | 88 | Energy from waste; residual to landfill | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-08-MIX | Mixed recycling, August 2026 | 2026-08 | 2026-08-01 | 2026-08-31 | Mixed recycling | 0.95 | 97 | Materials recovery facility | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-08-PAP | Paper and card, August 2026 | 2026-08 | 2026-08-01 | 2026-08-31 | Paper and card | 0.31 | 100 | Paper mill | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-08-FOD | Food waste, August 2026 | 2026-08 | 2026-08-01 | 2026-08-31 | Food waste | 0.27 | 100 | Anaerobic digestion | Bin-lift scale | Regional Waste Partners | Confirmed |  |
| WR-2026-08-CON | Confidential paper, August 2026 | 2026-08 | 2026-08-01 | 2026-08-31 | Confidential paper | 0.18 | 100 | Secure shred, then paper mill | Weighbridge ticket | Regional Waste Partners | Confirmed |  |
| WR-2026-08-WEE | WEEE, August 2026 | 2026-08 | 2026-08-01 | 2026-08-31 | WEEE | 0.12 | 100 | Licensed WEEE recycler | Delivery note | Regional Waste Partners | Confirmed | Includes a batch of small electrical items from an office clear-out. |
| WR-2026-09-GEN | General waste, September 2026 | 2026-09 | 2026-09-01 | 2026-09-30 | General waste |  |  | Energy from waste; residual to landfill | Bin-lift scale | Regional Waste Partners | Pending | The contractor issues the return after month end; no figure exists yet. |
| WR-2026-09-MIX | Mixed recycling, September 2026 | 2026-09 | 2026-09-01 | 2026-09-30 | Mixed recycling |  |  | Materials recovery facility | Bin-lift scale | Regional Waste Partners | Pending |  |
| WR-2026-09-PAP | Paper and card, September 2026 | 2026-09 | 2026-09-01 | 2026-09-30 | Paper and card |  |  | Paper mill | Bin-lift scale | Regional Waste Partners | Pending |  |
| WR-2026-09-FOD | Food waste, September 2026 | 2026-09 | 2026-09-01 | 2026-09-30 | Food waste |  |  | Anaerobic digestion | Bin-lift scale | Regional Waste Partners | Pending |  |
| WR-2026-09-CON | Confidential paper, September 2026 | 2026-09 | 2026-09-01 | 2026-09-30 | Confidential paper |  |  | Secure shred, then paper mill | Weighbridge ticket | Regional Waste Partners | Pending |  |
| WR-2026-09-WEE | WEEE, September 2026 | 2026-09 | 2026-09-01 | 2026-09-30 | WEEE |  |  | Licensed WEEE recycler | Delivery note | Regional Waste Partners | Pending |  |

**42 entries: 36 monthly weights (six streams over March to August 2026) and 6 pending lines for September 2026. The six issued months total 30.65 tonnes, of which 28.25 tonnes (92.2%) were diverted from landfill. August 2026, the latest complete month, was 3.53 tonnes with 93.4% diverted; the heaviest month was May 2026 at 6.06 tonnes. One weight is an estimate and one return is under query.**
