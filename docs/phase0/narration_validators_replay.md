# Narration validators, replayed over the stored answers (2D-09)

Replayed **1377** stored answers (17 answer files under `docs/phase0/`, each
paired with its hand-read labels). **52** change; the rest are byte-identical.
The SEALED held-out set (`tail_C_2026-09-19`) is not among them and is never read here;
`dev_tail_C_*` is the development copy the lead released for this measurement.
Regenerate with `python scripts/replay_narration_validators.py`.

| validator | answers changed |
|---|---|
| check_counts_against_lists | 2 |
| drop_unasked_advice | 42 |
| fix_advice_direction | 1 |
| fix_total_called_daily_average | 1 |
| no_range_as_delta | 1 |
| state_method_of_computed_total | 1 |
| strip_uncited_norms | 7 |

| hand label | answers changed |
|---|---|
| GOOD_ANSWER | 37 |
| WEIRD | 15 |

`orphans` = numbers that were in a removed sentence and appear nowhere else in the answer.

| file#row | label | validator | action | removed (or replaced) | orphans |
|---|---|---|---|---|---|
| phase0_baseline.md#101 | WEIRD | drop_unasked_advice | drop_sentence | If CO₂ remains above 1000 ppm, consider increasing ventilation to reduce concentration. | 1000 |
| phase0_baseline.md#120 | GOOD_ANSWER | drop_unasked_advice | drop_sentence | To keep the system balanced, continue to monitor the delta‑T on both boilers and adjust the flow rate if the difference widens beyond a few degrees. |  |
| phase0_baseline.md#132 | WEIRD | drop_unasked_advice | drop_sentence | **Monitor floor‑by‑floor flow** to catch leaks early. |  |
| phase0_rerun.md#120 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | **Recommendation:** Verify that the flow rate through each boiler remains steady to preserve this ΔT range. |  |
| phase0_run3.md#120 | WEIRD | strip_uncited_norms | drop_sentence | These ΔT values are comfortably within the typical 10–15 °C range that indicates efficient heat transfer, so the heating circuit is healthy. | 10 15 |
| phase0_run3.md#132 | WEIRD | drop_unasked_advice | drop_sentence | Monitor for leaks (Floor 4 peak 292 m³/s). |  |
| phase0_run4.md#2 | WEIRD | drop_unasked_advice | drop_paragraph | **Recommendation:** Perform a continuous 24‑hour monitoring session to confirm whether the elevated noise persists or fluctuates. | 24 |
| phase0_run5.md#120 | GOOD_ANSWER | strip_uncited_norms | drop_sentence | A ΔT of 9–11 °C is typical for efficient heating circuits, so the current values are healthy and within normal operating range. | 9 |
| phase0_run5.md#120 | GOOD_ANSWER | strip_uncited_norms | drop_empty_heading | **Health check** | 9 |
| phase0_run5.md#132 | WEIRD | drop_unasked_advice | drop_sentence | If not, consider installing one or providing bottled water. |  |
| phase0_run5.md#132 | WEIRD | drop_unasked_advice | drop_sentence | If the meter shows low usage, consider encouraging tap use or providing bottled water. |  |
| phase0_run6.md#120 | GOOD_ANSWER | strip_uncited_norms | drop_sentence | A delta‑T of 10–12 degC is typical for a healthy heating circuit, giving good heat transfer without over‑loading the boiler. | 10 12 |
| fresh_tail_run1#1 | WEIRD | drop_unasked_advice | drop_paragraph | **Recommendation:** Continue monitoring the pm25 level and consider increasing ventilation if the concentration remains above 20 µg/m³ for extended periods. | 20 |
| fresh_tail_run1#2 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | *Recommendation:* Adjust the HVAC setpoint on Floor 5 to bring its mean temperature closer to the other floors. |  |
| fresh_tail_run1#5 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | **Recommendation:** investigate any operational or maintenance changes that occurred between the two weeks to maintain the lower consumption trend. |  |
| fresh_tail_run1#6 | GOOD_ANSWER | drop_unasked_advice | drop_sentence | Review the equipment and usage patterns on Floor 3 to identify opportunities for energy savings. |  |
| fresh_tail_run1#40 | GOOD_ANSWER | drop_unasked_advice | drop_sentence | Continue monitoring to detect any future divergence in temperature readings. |  |
| fresh_tail_B_run1#1 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | **Actionable recommendation:** investigate the 52 % reading in Room 4.67 and adjust HVAC settings if needed to achieve more uniform humidity. |  |
| fresh_tail_B_run1#4 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | Recommendation: Conduct a focused energy audit on Floor 3 to identify opportunities for reducing its higher consumption. |  |
| fresh_tail_B_run1#8 | WEIRD | check_counts_against_lists | drop_sentence | Across the six floors the average occupancy during the last 60 minutes (from 18 Sep 19:55 to 18 Sep 21:09) is about 14 people per floor. | 14 19 55 60 |
| fresh_tail_B_run2#1 | GOOD_ANSWER | drop_unasked_advice | drop_sentence | To promote a more uniform environment, consider fine‑tuning the HVAC setpoints or adding localized dehumidification in the areas with the highest readings. |  |
| fresh_tail_B_run2#4 | WEIRD | drop_unasked_advice | drop_paragraph | **Recommendation:** aggregate daily totals over the month to obtain an accurate monthly energy consumption figure. |  |
| guardrail_run1#6 | WEIRD | drop_unasked_advice | drop_paragraph | **Recommendation:** Extend monitoring to include the missing hour (17 Sep 22:00 – 18 Sep 22:00) to obtain a complete daily consumption profile. | 18 |
| demo_rehearsal_2026-09-18_run1#12 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | **Recommendation:** Conduct a targeted audit of the equipment and usage patterns on Floor 3 to identify opportunities for reducing its energy draw. |  |
| demo_rehearsal_2026-09-18_run1#19 | GOOD_ANSWER | drop_unasked_advice | drop_section | **Recommendations** / 1. Verify ventilation system performance in room 5.01 to ensure CO₂ levels remain below 1,000 ppm. / 2. Schedule a maintenance check of the CO₂ sensor to confirm continued accuracy. / 3. Review occupant acti… | 1 1,000 2 3 |
| demo_rehearsal_2026-09-18_run1#26 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | Recommendation: consider adjusting the HVAC setpoint on floor 5 to maintain a more uniform temperature across the building. |  |
| demo_rehearsal_2026-09-18_run1#27 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | Recommendation: increase ventilation or monitor CO₂ on Floor 5 more frequently to maintain consistent indoor air quality. |  |
| demo_rehearsal_2026-09-18_run1#28 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | Recommendation: consider adjusting the HVAC setpoint or increasing ventilation on floor 0 to maintain consistent humidity levels throughout the building. |  |
| demo_rehearsal_2026-09-18_run1#32 | GOOD_ANSWER | drop_unasked_advice | trim_sentence | Overall, the circuit is healthy, but monitoring the ΔT trend will help catch any future drops that might signal a problem. => Overall, the circuit is healthy. | 8 9 |
| demo_rehearsal_2026-09-18_run1#32 | GOOD_ANSWER | strip_uncited_norms | drop_sentence | A ΔT of 8–9 °C is typical for a heating circuit and indicates that heat is being transferred efficiently. | 8 9 |
| demo_rehearsal_2026-09-18_run1#36 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | **Recommendation:** review the HVAC setpoint for floor 3 to ensure it remains aligned with the observed temperature trend.** |  |
| demo_rehearsal_2026-09-18_run1#37 | WEIRD | drop_unasked_advice | drop_paragraph | **Recommendation:** Investigate the factors that caused the 35.7 % reduction in week 38 and evaluate whether the lower consumption can be sustained through targeted energy‑saving actions. | 38 |
| demo_rehearsal_2026-09-18_run1#38 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | Recommendation: Verify that both sensors are calibrated to the same reference to ensure consistency in future measurements. |  |
| demo_rehearsal_2026-09-18_run2#9 | WEIRD | check_counts_against_lists | drop_enumeration | 2 (the continuous regimes on Floors 2 and 5 and the parking ventilation) => 2 |  |
| demo_rehearsal_2026-09-18_run2#12 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | Recommendation: Conduct a detailed audit of equipment and occupancy on Floor 3 to identify opportunities for reducing energy consumption. |  |
| demo_rehearsal_2026-09-18_run2#19 | GOOD_ANSWER | drop_unasked_advice | drop_section | **Recommendations** / 1. **Maintain ventilation** – Ensure that the HVAC system is operating at the required airflow rates to keep CO₂ levels below the observed maximum. / 2. **Schedule sensor calibration** – Perform a calibratio… | 1 2 3 |
| demo_rehearsal_2026-09-18_run2#26 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | **Recommendation:** Conduct a quick audit of the HVAC airflow on floors 0, 3, and 4 to ensure even distribution and rule out any blockage that could be causing the slight elevation. |  |
| demo_rehearsal_2026-09-18_run2#27 | GOOD_ANSWER | fix_advice_direction | drop_sentence | **Recommendation:** Increase ventilation or monitor occupancy on Floor 5 to bring its CO₂ level closer to the other floors. |  |
| demo_rehearsal_2026-09-18_run2#28 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | **Recommendation:** Increase ventilation or adjust the HVAC setpoint on Floor 5 to maintain a more uniform humidity profile across all floors. |  |
| demo_rehearsal_2026-09-18_run2#32 | GOOD_ANSWER | strip_uncited_norms | drop_sentence | A ΔT of around 10–12 °C is typical for efficient heating circuits. | 10 12 |
| demo_rehearsal_2026-09-18_run2#32 | GOOD_ANSWER | strip_uncited_norms | trim_sentence | The latest readings show ΔT values of 10.5–11.1 °C, which fall comfortably within the healthy operating range. => The latest readings show ΔT values of 10.5–11.1 °C. | 10 12 |
| demo_rehearsal_2026-09-18_run2#32 | GOOD_ANSWER | strip_uncited_norms | drop_sentence | The heating circuit is operating well; the temperature rise from inlet to outlet is within the expected healthy range. | 10 12 |
| demo_rehearsal_2026-09-18_run2#32 | GOOD_ANSWER | strip_uncited_norms | drop_empty_heading | **Key take‑away** | 10 12 |
| demo_rehearsal_2026-09-18_run2#36 | GOOD_ANSWER | drop_unasked_advice | drop_sentence | Maintain current HVAC settings but schedule a review if temperatures exceed 24.0 °C for more than two consecutive days. | 24.0 |
| demo_rehearsal_2026-09-18_run2#37 | WEIRD | drop_unasked_advice | drop_paragraph | **Recommendation:** Conduct a detailed review of operational activities and equipment usage during week 2026‑W38 to identify the drivers of the drop and assess whether the lower consumption reflects a cost‑saving opportunity or a… |  |
| demo_rehearsal_2026-09-18_run2#38 | GOOD_ANSWER | drop_unasked_advice | drop_sentence | To ensure continued accuracy, schedule a calibration check for both sensors. |  |
| demo_rehearsal_2026-09-18_run3_combined#12 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | Recommendation: review the HVAC and lighting schedules on Floor 3 to identify potential energy‑saving adjustments. |  |
| demo_rehearsal_2026-09-18_run3_combined#13 | GOOD_ANSWER | strip_uncited_norms | drop_sentence | *Expected benefit:* A 1 °C rise in set‑point can cut HVAC energy by roughly 5 %–10 % for that floor, saving about 0.18–0.36 kWh per hour during peak. | 0.18 0.36 10 20 |
| demo_rehearsal_2026-09-18_run3_combined#13 | GOOD_ANSWER | strip_uncited_norms | drop_sentence | *Expected benefit:* Typical buildings see 10 %–20 % lighting savings with this rule, translating to several kWh per month. | 0.18 0.36 10 20 |
| demo_rehearsal_2026-09-18_run3_combined#19 | GOOD_ANSWER | drop_unasked_advice | drop_section | **Recommendations** / 1. Continue routine monitoring of the CO₂ Level Sensor installed‑node 5.01 to track trends. / 2. Verify that the sensor remains calibrated and free of obstructions. / 3. Review the ventilation system’s perfo… | 1 2 3 |
| demo_rehearsal_2026-09-18_run3_combined#26 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | **Recommendation:** Adjust the HVAC setpoint on Floors 0 and 3 to reduce the slight temperature imbalance and improve energy efficiency. |  |
| demo_rehearsal_2026-09-18_run3_combined#27 | WEIRD | drop_unasked_advice | drop_sentence | To balance indoor air quality, consider increasing ventilation on Floor 5 so its average CO₂ level moves toward the 800‑ppm range observed on the other floors. | 5 800 |
| demo_rehearsal_2026-09-18_run3_combined#28 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | **Recommendation:** Adjust the HVAC setpoint or increase ventilation on Floor 5 to bring its humidity closer to the other floors and reduce potential moisture‑related issues. |  |
| demo_rehearsal_2026-09-18_run3_combined#32 | WEIRD | no_range_as_delta | drop_sentence | Across all 7934 records (from 14 Sep 15:47 to 18 Sep 22:19), the ΔT ranged from roughly **0 °C** (when the boiler is idle) up to **≈ 53 °C** (maximum leaving 74.4 °C minus minimum entering 21.7 °C). | 0 14 15 21.7 47 53 |
| demo_rehearsal_2026-09-18_run3_combined#32 | WEIRD | drop_unasked_advice | trim_sentence | The system is functioning, though you might want to check whether the boilers are running at full capacity during peak demand. => The system is functioning. | 0 14 15 21.7 47 53 |
| demo_rehearsal_2026-09-18_run3_combined#32 | WEIRD | strip_uncited_norms | drop_sentence | A ΔT of 8–9 °C is slightly below the typical 10–15 °C target for efficient heating, but it is still within a healthy operating range. | 0 14 15 21.7 47 53 |
| demo_rehearsal_2026-09-18_run3_combined#36 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | **Recommendation:** Continue to monitor floor 3 temperatures closely; if the upward trend persists, evaluate HVAC setpoints to maintain consistent conditions. |  |
| demo_rehearsal_2026-09-18_run3_combined#37 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | **Recommendation:** Continue collecting data for the remainder of 2026‑W38 to confirm whether the downward trend persists and investigate any operational changes that may have driven the reduction. |  |
| demo_rehearsal_2026-09-18_run3_combined#38 | GOOD_ANSWER | drop_unasked_advice | drop_paragraph | Recommendation: cross‑check the two sensors’ readings to confirm consistency and investigate any persistent discrepancy. |  |
| demo_wave1#37 | GOOD_ANSWER | fix_total_called_daily_average | trim_sentence | The 2026‑W37 total of 12,077 kWh (3462 readings, 1.93–4.94 kWh) represents the highest daily average, while the 2026‑W38 total of 8,863 kWh (2538 readings, 0.26–6.21 kWh) represents the lowest. => The 2026‑W37 total was 12,077 kW… |  |
| wave1_verification#24 | GOOD_ANSWER | state_method_of_computed_total | add_method | used 2,058,048 L => **Method:** computed as the average flow rate (23.82 L/s) × 24 h, so it is only as good as that average. |  |
