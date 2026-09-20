# -*- coding: utf-8 -*-
"""BUG-838: the units-sanity warning judged a number against a quantity nobody quoted it as.

Live, wave 1: *"can you provide energy saving suggestion?"* OPENED with "⚠️ The recorded
temperature value (600) is outside the range this quantity can take in °C or °F, so it is most
likely raw or unscaled sensor output." Nothing in that answer measured 600 °C. The 600 is the
first number of **"Keep CO₂ between 600–800 ppm"** in the model's own advice:

* the other three 600/800 figures were skipped correctly, because ` ppm` follows them;
* the first number of a RANGE carries no unit — "–800 ppm" follows it — so it read as unitless;
* the guard had inferred one measurand for the WHOLE answer from the word "temperature"
  appearing elsewhere in it, and judged the unitless number against that.

Two fixes, each of which alone kills this case: a range's unit governs both its ends, and a bare
number belongs to the quantity named nearest before it. The guard must still fire on what it was
built for (CAVEAT-053), so that case is pinned here too.
"""

import pytest

from orchestrator.services import plausibility as p

pytestmark = pytest.mark.unit

# The advice paragraph of the live answer, verbatim apart from the narrow no-break spaces.
ENERGY_ADVICE = (
    "Tighten the HVAC temperature set-point by 1 °C during peak hours. "
    "If CO₂ > 800 ppm, increase ventilation; if CO₂ < 600 ppm, reduce ventilation. "
    "Keep CO₂ between 600–800 ppm to balance air quality and energy use. "
    "Lower the illuminance setpoint by 20 % (e.g., from 500 lux to 400 lux). "
    "This is a good way to cut consumption."
)


def test_the_energy_answer_no_longer_opens_with_a_warning_about_a_temperature_nobody_quoted():
    assert p.implausibility_note("can you provide energy saving suggestion?", ENERGY_ADVICE) is None


def test_the_first_number_of_a_range_inherits_the_units_written_after_the_range():
    assert p.implausible_values("Keep CO₂ between 600–800 ppm.", "temperature") == []
    assert p._unit_kind("–800 ppm to balance") == "co2"
    assert p._unit_kind(" to 800 ppm") == "co2"
    assert p._unit_kind(" and 800 ppm") == "co2"
    assert p._unit_kind(" ppm") == "co2", "the plain case still works"


def test_a_bare_number_is_judged_against_the_quantity_named_nearest_before_it():
    assert p._nearest_measurand("the CO₂ rose and the reading was") == "co2"
    assert p._nearest_measurand("temperature fell, then CO₂ rose to") == "co2"
    assert p._nearest_measurand("CO₂ rose, then the temperature reached") == "temperature"
    assert p._nearest_measurand("nothing named here") is None


def test_a_co2_figure_is_not_judged_as_a_temperature_even_with_no_unit_written():
    text = "The temperature is 22 °C. The CO₂ averaged 943 and peaked at 1,101."
    assert p.implausible_values(text, "temperature") == []


# ── the guard must still do its job (CAVEAT-053) ─────────────────────────────


def test_the_wind_case_the_guard_was_built_for_still_fires():
    draft = (
        "Yes - the wind is very strong right now. The most recent reading shows a value of "
        "approximately 8308 (the unit used in your data)."
    )
    note = p.implausibility_note("is the wind strong?", draft)
    assert note is not None and "8308" in note and "raw or unscaled" in note


def test_an_impossible_value_quoted_in_its_own_unit_is_still_caught():
    draft = "The supply air temperature is very high at 1,098.4 °C right now."
    # 1098, not 1098.4: _NUMBER_RE's thousands-separator branch stops at the comma group and
    # drops the decimal. Pre-existing, cosmetic (it only changes the figure the warning shows),
    # and it does not change the verdict — pinned here so it is a known quirk, not a surprise.
    assert p.implausible_values(draft, "temperature") == [1098.0]
    assert p.implausibility_note("what is the supply air temperature?", draft) is not None


def test_an_impossible_bare_value_next_to_its_own_measurand_is_still_caught():
    draft = "The temperature reading is 964.8, which is very high."
    assert p.implausible_values(draft, "temperature") == [964.8]


def test_a_plausible_value_is_never_flagged():
    draft = "The temperature is 23.4 °C, which is comfortable."
    assert p.implausibility_note("is it warm?", draft) is None
