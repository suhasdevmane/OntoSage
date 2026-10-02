# -*- coding: utf-8 -*-
"""Round 4 of 2026-10-01: three places where the fix landed and the live re-ask said "not yet".

1. "How does it ensure that the most important systems keep running?" reached the
   ContinuityProvision register THROUGH its lay terms ("important systems", "keep running") --
   and the out-of-scope decline then refused it with "nothing about ensure, important and
   running": the words that had selected the register counted as beyond it. `resolve` already
   discounts those words when told the terms; `out_of_scope_decline` was the one caller that
   did not pass them.

2. "'cafeteria' does not exist in this building" -- the referent gate consulted the ontology's
   lay terms only when the head word already existed textually in some field, which no lay
   term can satisfy (that is what a lay term is for). `ontosage:Cafe` declares "cafeteria".

3. "What is the function of your building?" -- a building-identity question forced to the
   metadata lane, whose SPARQL path answered it from air-quality sensors, while the profile
   answerer (brick:buildingPrimaryFunction) runs first in the capability lane. Only the
   type/purpose facets are re-routed: measured over the 4,060 bank, those match 0 questions,
   while whole-profile/owner match 9 compound ones the register lane may own.
"""

import inspect

import pytest

from orchestrator.services import building_profile as bp
from orchestrator.services import register_projection as rp
from orchestrator.services import routing_contract as rc

pytestmark = pytest.mark.unit


def _rows(n=12):
    out = []
    for i in range(1, n + 1):
        out.append(
            {
                "recordId": {"value": f"CP-{i:03d}"},
                "label": {"value": f"Continuity provision {i}"},
                "servesService": {"value": "Lab freezers"},
                "criticality": {"value": "high"},
                "alternativeLocation": {"value": "Room 2.01"},
                "rideThroughMinutes": {"value": "30"},
                "recordStatus": {"value": "current"},
            }
        )
    return out


class TestTheDeclineHonoursTheRegistersOwnWords:
    Q = "How does it ensure that the most important systems keep running?"
    TERMS = ["continuity", "keep running", "important systems", "critical systems"]

    def test_without_the_terms_it_declines(self):
        text = rp.out_of_scope_decline(_rows(), self.Q, "Service continuity provision")
        assert "cannot answer this" in text

    def test_with_the_terms_it_lets_the_narration_run(self):
        text = rp.out_of_scope_decline(
            _rows(), self.Q, "Service continuity provision", register_terms=self.TERMS
        )
        assert text == ""

    def test_the_lane_passes_the_terms(self):
        src = inspect.getsource(rp.answer_before_narration)
        assert "out_of_scope_decline(" in src
        i = src.index("out_of_scope_decline(")
        assert "register_terms=register_terms" in src[i : i + 200]

    def test_a_question_truly_beyond_the_register_still_declines(self):
        q = "Which dependency-aware recovery order should incident leaders adopt?"
        text = rp.out_of_scope_decline(
            _rows(), q, "Service continuity provision", register_terms=self.TERMS
        )
        assert "cannot answer this" in text, "an order the register does not hold is declined"


class TestTheReferentGateReadsLayTermsWithoutATextualHead:
    def test_the_amenity_check_no_longer_requires_head_exists(self):
        from orchestrator.services.referent_resolver import ReferentResolver

        src = inspect.getsource(ReferentResolver._resolve_typed)
        i = src.index("_holds_amenity_kind(typed.head, namespace)")
        guard = src[max(0, i - 400) : i]
        assert "if not exists and not numbered and typed.kind != KIND_MEASURAND:" in guard
        assert "if head_exists and not exists and not numbered:" not in guard


class TestABuildingIdentityQuestionReachesTheProfile:
    @pytest.mark.parametrize(
        "q, facet",
        [
            ("What is the function of your building?", "type"),
            ("What is this building used for?", "purpose"),
            ("What is the purpose of this building?", "purpose"),
            ("What kind of building is this?", "type"),
        ],
    )
    def test_the_facet_is_detected(self, q, facet):
        assert bp.detect_facet(q) == facet

    @pytest.mark.parametrize(
        "q", ["What is the function of your building?", "What is the purpose of this building?"]
    )
    def test_the_contract_sends_it_to_the_capability_lane(self, q):
        ctx = rc._Ctx(query=q, ql=q.lower(), normalized={"intent": "capability"}, sr=None)
        assert rc._r_countable_metadata(ctx) == "capability"

    def test_the_classifiers_own_metadata_guess_is_overridden_too(self):
        """Live, the classifier called 'What is the function of your building?' metadata, and
        the override's intent gate let that stand; the sensors answered it again."""
        q = "What is the function of your building?"
        ctx = rc._Ctx(query=q, ql=q.lower(), normalized={"intent": "metadata"}, sr=None)
        assert rc._r_countable_metadata(ctx) == "capability"

    def test_a_metadata_census_question_is_left_alone(self):
        q = "How many sensors are in the building?"
        ctx = rc._Ctx(query=q, ql=q.lower(), normalized={"intent": "metadata"}, sr=None)
        assert rc._r_countable_metadata(ctx) == "metadata"

    def test_a_whole_profile_question_keeps_its_old_route(self):
        q = "Tell me about this building"
        ctx = rc._Ctx(query=q, ql=q.lower(), normalized={"intent": "capability"}, sr=None)
        assert rc._r_countable_metadata(ctx) == "metadata"

    def test_a_count_question_keeps_its_old_route(self):
        q = "How many sensors are in the building?"
        ctx = rc._Ctx(query=q, ql=q.lower(), normalized={"intent": "capability"}, sr=None)
        assert rc._r_countable_metadata(ctx) == "metadata"
