"""BUG-590: a CO2 figure in ppm is not an impossible temperature."""

import pytest

from orchestrator.services.plausibility import implausibility_note, implausible_values

pytestmark = pytest.mark.unit


def test_ppm_figures_in_a_temperature_and_co2_report_are_not_temperatures():
    q = "Give me a report on the temperature and CO2 on floor 2 yesterday."
    draft = (
        "Temperature remained within 21.5 °C–24.65 °C and CO₂ ranged from 669 ppm to 943 ppm; "
        "a few values are high."
    )
    assert implausibility_note(q, draft) is None


def test_an_impossible_temperature_written_in_degrees_is_still_caught():
    assert implausible_values("The temperature is 669 °C, very high.", "temperature") == [669.0]


def test_an_unlabelled_impossible_figure_is_still_caught():
    assert implausible_values("The wind is very strong at 8308.", "wind") == [8308.0]
