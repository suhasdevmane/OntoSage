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
