# -*- coding: utf-8 -*-
"""The words tail O used that reached NO register, now declared on the class (BUG-1406).

Six of eleven false declines in tail O (2026-10-01) had the data in a register the question's
words did not reach. TTL-first (design contract #2): the words are declared as ``layTerms`` on
the CLASS in the shared TBox, so any building holding the class gains them, and the register
selector picks them up with no code change. Each addition was measured over the 4,060-question
bank before landing: the first draft of the continuity terms carried "resilience" and
"redundancy" and moved 25 primary registers, 20 of them compound stakeholder questions those
two words hijacked (three from CostLine, one from Contract); without them, 6 moves, five of
them plainly right.

Also here: the whole-building identity words ("What is the function of your building?" was
answered from air-quality sensors; the building declares brick:buildingPrimaryFunction), and
the referent gate reading a class's lay terms ("'cafeteria' does not exist in this building"
while ontosage:Cafe declares "cafeteria" and the building holds a Cafe).
"""

from pathlib import Path

import pytest
import rdflib

from orchestrator.services.routing_contract import BUILDING_INFO_KWS

pytestmark = pytest.mark.unit

TBOX = Path(__file__).resolve().parents[1] / "ontology" / "ontosage_schema.ttl"
O = rdflib.Namespace("http://ontosage.org/capabilities#")


@pytest.fixture(scope="module")
def lay_terms():
    g = rdflib.Graph()
    g.parse(TBOX, format="turtle")
    out = {}
    for cls, term in g.subject_objects(O.layTerms):
        out.setdefault(str(cls).split("#")[-1], set()).add(str(term).lower())
    return out


class TestTheClassesCarryTheWords:
    @pytest.mark.parametrize(
        "cls, words",
        [
            (
                "ContinuityProvision",
                [
                    "keep running",
                    "important systems",
                    "critical systems",
                    "if the power fails",
                    "ride through",
                ],
            ),
            (
                "ServiceSchedule",
                [
                    "filter change",
                    "service frequency",
                    "maintenance frequency",
                    "how often are they serviced",
                ],
            ),
            ("AccessibilityFeature", ["handicapped parking", "disabled bays", "accessible bays"]),
            ("ClosurePeriod", ["maintenance restrictions", "under maintenance", "out of action"]),
        ],
    )
    def test_declared(self, lay_terms, cls, words):
        for w in words:
            assert w in lay_terms[cls], f"{cls} no longer declares {w!r}"

    @pytest.mark.parametrize("word", ["resilience", "redundancy"])
    def test_the_two_words_measured_and_rejected_stay_out(self, lay_terms, word):
        """Each moved ~10 compound stakeholder questions onto the wrong register."""
        assert word not in lay_terms["ContinuityProvision"]

    def test_cafeteria_is_a_declared_word_for_a_cafe(self, lay_terms):
        """The referent gate reads this; the building need not spell it in a class name."""
        assert "cafeteria" in lay_terms["Cafe"]


class TestWholeBuildingIdentity:
    @pytest.mark.parametrize(
        "q",
        [
            "What is the function of your building?",
            "What is the purpose of this building?",
            "What is this building used for?",
            "What kind of building is this?",
        ],
    )
    def test_the_question_names_the_building_itself(self, q):
        assert any(k in q.lower() for k in BUILDING_INFO_KWS), q

    @pytest.mark.parametrize(
        "q",
        [
            "What is the function of the AHU on floor 3?",
            "What is the purpose of the damper?",
            "What type of sensor is in room 2.01?",
        ],
    )
    def test_a_part_of_the_building_is_not_the_building(self, q):
        assert not any(k in q.lower() for k in BUILDING_INFO_KWS), q


class TestTheReferentGateReadsLayTerms:
    def test_the_amenity_kind_query_matches_class_and_instance_lay_terms(self):
        import inspect

        from orchestrator.services.referent_resolver import ReferentResolver

        src = inspect.getsource(ReferentResolver._holds_amenity_kind)
        assert "?cls o:layTerms ?lay" in src
        assert "?s o:layTerms ?lay" in src
        assert "UNION" in src
