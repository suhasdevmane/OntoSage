"""A model's error statistics are not readings of the building; its predictions still are.

Live: a CO2 forecast published its model-selection table -- Linear Trend R2 -0.065, SeasonalNaive
R2 0.946 -- and the guard opened three otherwise correct forecasts with "the recorded co2 value
(-0.065) is outside the range this quantity can take in ppm". An RMSE expressed in ppm is not a
reading in ppm, so the unit cannot tell them apart.

The first attempt at this fix exempted the whole `forecast` operation. That was too broad and an
existing test caught it: a forecast's PREDICTED value is a reading, and an impossible prediction is
exactly what the guard exists to catch. Only the metrics block is exempt, and a number is treated as
a metric only when a metric label sits above it AND it occupies a table cell.
"""

import pytest

from orchestrator.services.plausibility import implausibility_note, implausible_values

pytestmark = pytest.mark.unit

# Exactly as the page renders it: the table is tab-and-newline separated, which is why the "R2"
# header sits more than a hundred characters from the value it labels. An earlier version of this
# fix looked back only 90 characters and therefore never saw the header at all.
FORECAST = (
    "Forecast: CO2 Level Sensor installed-node 5.01\n"
    "Horizon: next 24 hours | History used: 192 data points\n\n"
    "Model Selection\nMODEL\n\t\nRMSE\n\t\nMAE\n\t\nMAPE\n\t\nR²\n\t\nSELECTED\n\n\n"
    "Linear Trend (sklearn)\n\t\n188.162ppm\n\t\n168.408ppm\n\t\n21.5%\n\t\n-0.065\n\t\n\n\n"
    "SeasonalNaive\n\t\n42.219ppm\n\t\n31.083ppm\n\t\n4.1%\n\t\n0.946\n\t\nWinner\n\n"
    "The CO2 is predicted to stay near 520 ppm and is unlikely to exceed 1000 ppm.\n"
)


def test_a_model_metric_is_not_read_as_a_reading():
    assert implausible_values(FORECAST, "co2") == []


def test_the_forecast_carries_no_implausibility_caveat():
    note = implausibility_note("Will the CO2 in room 5.01 exceed 1000 ppm tomorrow?", FORECAST)
    assert note is None


def test_a_forecasts_predicted_value_is_still_checked():
    """Only the METRICS are exempt. A prediction is a reading and must still be guarded."""
    draft = FORECAST.replace("stay near 520 ppm", "stay near 48000000 ppm")
    assert implausible_values(draft, "co2") == [48000000.0]


def test_a_genuinely_impossible_reading_is_still_caught():
    draft = "The CO2 in Room 2.01 is 48000000 ppm, which is far above the comfort range."
    assert implausible_values(draft, "co2") == [48000000.0]


def test_a_negative_reading_outside_a_metric_table_is_still_caught():
    draft = "The recorded CO2 level is -412 ppm, which is below the comfort band."
    assert implausible_values(draft, "co2") == [-412.0]


def test_a_metric_word_in_prose_does_not_suppress_a_reading():
    """The metric label must sit above a table cell, not merely somewhere nearby in prose."""
    draft = (
        "There was a sensor error last night. The recorded CO2 in Room 2.01 is -412 ppm, "
        "which is below the comfort band."
    )
    assert implausible_values(draft, "co2") == [-412.0]


# ── BUG-872: the real forecast, not a hand-built approximation of one ─────────────────
#
# Every test above passed while this shipped. They were written against a shortened stand-in
# whose R-squared sat close to its header; in the answer the system actually renders, the
# header is ~130 characters back, and the caller was slicing 90. The constant said 320, the
# comment explained why it said 320, and the call site handed it a third of that.
#
# Captured verbatim from /v1/chat/completions, 2026-09-23. The stored series for this sensor
# is a clean 30-70 %RH with not one impossible value; the forecast's own predictions are
# 52.66 %RH. The two numbers the guard objected to are a ROW COUNT and an R-SQUARED.

REAL_HUMIDITY_FORECAST = """## Forecast: Zone Air Humidity Sensor installed-node 2.01

**Horizon:** next 24 hours  |  **As of:** 2026-09-23 01:43 (building time)  |  \
**History used:** 193 data points

### Model Selection

| Model | RMSE | MAE | MAPE | R\u00b2 | Selected |
|-------|------|-----|------|----|----------|
| Linear Trend (sklearn) | 2.923%RH | 2.643%RH | 5.4% | -0.029 |  |
| SeasonalNaive | 0.839%RH | 0.648%RH | 1.3% | 0.915 |  |
| Holt-Winters (seasonal=24) | 0.642%RH | 0.475%RH | 1.0% | 0.950 | \u2705 **Winner** |
| SARIMA(1, 0, 0)\u00d7(1, 0, 1)[24] | 0.821%RH | 0.662%RH | 1.4% | 0.919 |  |

### Predictions \u2014 next 24 hours

| Time | Predicted | 80% CI | 95% CI |
|------|-----------|--------|--------|
| 2026-09-21 11:00 | **52.66%RH** | [51.34, 53.99]%RH | [50.37, 54.95]%RH |
| 2026-09-21 12:00 | **52.89%RH** | [51.02, 54.77]%RH | [49.65, 56.13]%RH |
"""


def test_bug_872_a_real_forecast_raises_no_false_alarm():
    """The whole answer, as rendered. -0.029 is an R-squared and 193 is a row count."""
    found = implausible_values(REAL_HUMIDITY_FORECAST, "humidity")
    assert found == [], f"false alarm on a correct forecast: {found}"


def test_bug_872_a_row_count_is_not_a_reading():
    """ "193 data points" -- the count noun is qualified, and only the bare noun was allowed."""
    assert implausible_values("**History used:** 193 data points of humidity", "humidity") == []


def test_bug_872_the_metric_lookback_constant_is_actually_in_force():
    """A constant is not in force until its caller lets it be.

    Pinned by DISTANCE, not by the sample text: put an R-squared far enough behind its header
    to exceed the old 90-character slice and well inside the documented 320.
    """
    from orchestrator.services.plausibility import _METRIC_LOOKBACK

    assert _METRIC_LOOKBACK >= 300
    filler = " | ".join(f"{i}.000%RH" for i in range(12))  # > 90 chars of table cells
    text = f"| Model | RMSE | MAE | R\u00b2 |\n| Linear Trend | {filler} | -0.029 |\n"
    assert len(filler) > 90
    assert implausible_values(text, "humidity") == []


def test_a_predicted_value_outside_the_possible_range_is_still_caught():
    """The guard must not be turned off by the presence of a metrics table."""
    broken = REAL_HUMIDITY_FORECAST.replace("**52.66%RH**", "**193.4%RH**")
    assert implausible_values(broken, "humidity"), "a real impossible prediction must still fire"
