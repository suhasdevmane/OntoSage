# -*- coding: utf-8 -*-
"""One query's empty result is not a fact about the building (BUG-1319).

THE DEFECT, live, occupant01 on /v1, both caches flushed:

    Q  "Which workplace peaks and troughs are stable enough to plan for ...?"
    A  "The building's records do not contain any data on workplace occupancy ...
        - **Sensor type missing**: *This building does not have workplace occupancy sensors.*"
       ... and it then advised the reader to INSTALL occupancy sensors.

Measured against the graph, distinct points carrying a timeseries reference:
Occupancy_Count_Sensor 257, Occupancy_Status 243, Parking_Occupancy_Sensor 1 -- **501 occupancy
series**. The sentence is a statement about the world and it is false, and it told a reader to
buy hardware the building already has.

The sentence was not invented. `sparql_agent`'s reasoning prompt INSTRUCTED it, verbatim:

    3. If the user asks for a sensor type that is NOT in the ontology, clearly state:
       "This building does not have [sensor type] sensors." Then suggest what IS available.

`context_text` is what ONE generated query returned. A binding failure -- "workplace peaks and
troughs" names occupancy only by implication -- therefore rendered as a graph-absence, which the
"four kinds of nothing" lesson says is the one wording that needs the graph to settle it.

MEASURED BLAST RADIUS before the change, over 2,861 de-duplicated stored answers: **11 answers
(0.38%)** claim the building lacks something, and **3 of the 11 are demonstrably false** -- all
occupancy, including "Is there anyone in the lobby?" answered "This building does not have
occupancy sensors". The other eight are barometric pressure, free-cooling and FCUs, which this
building genuinely lacks; for those the new wording is weaker and still true.

These tests assert the PROMPT, because that is what was changed and what caused it. Whether a
given turn obeys it is measured by asking the running system, not here.
"""

import inspect
import re

import pytest

pytestmark = pytest.mark.unit


def _prompt_source() -> str:
    from orchestrator.agents import sparql_agent

    return inspect.getsource(sparql_agent)


class TestThePromptDoesNotLicenseAClaimAboutTheBuilding:
    def test_the_old_instruction_is_gone(self):
        src = _prompt_source()
        assert "This building does not have [sensor type] sensors" not in src, (
            "the prompt instructs a claim about the BUILDING from a context that shows only "
            "what one query returned; that is what produced a false absence over 501 series"
        )

    @pytest.mark.parametrize(
        "forbidden",
        [
            r"clearly state:\s*\n?\s*\"This building does not have",
            r"state that the building does not have",
            r"say the building has no",
        ],
    )
    def test_no_variant_of_the_instruction_returns(self, forbidden):
        assert not re.search(forbidden, _prompt_source(), re.IGNORECASE)

    def test_the_replacement_scopes_the_claim_to_the_search(self):
        src = _prompt_source()
        assert "WHAT ONE QUERY RETURNED" in src
        assert (
            "in the records I searched" in src
        ), "the honest form of an empty result is about the SEARCH, not the building"

    def test_the_prompt_forbids_recommending_hardware(self):
        """The live answer told a reader to install sensors the building already had."""
        src = _prompt_source()
        assert re.search(
            r"never advise anyone to install", src, re.IGNORECASE
        ), "a failed search must not become a purchasing recommendation"


class TestTheOtherInstructionsStillStand:
    """A guard on the guard: the edit must not have loosened the existence rule beside it."""

    def test_a_sensor_may_still_only_be_claimed_from_the_data_shown(self):
        src = _prompt_source()
        assert "Only claim a sensor or sensor type exists if it appears" in src

    def test_the_records_are_still_called_the_buildings_own(self):
        src = _prompt_source()
        assert 'never call it data the user "provided"' in src
