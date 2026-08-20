# -*- coding: utf-8 -*-
"""TODO-181: instances typed with brick: terms Brick never defined.

`brick:` is not a free-form prefix — putting a term there asserts Brick defines
it. An earlier minting path wrote four terms Brick does not have. Nothing failed,
because matching is on the LOCAL name, which is exactly why it survived: a
non-conformant graph that answers every query looks identical to a correct one.
"""

from __future__ import annotations

import re

import pytest
import rdflib

from scripts.retype_legacy_brick_classes import RETYPE, retype_text

pytestmark = pytest.mark.unit

HEADER = (
    "@prefix bldg: <http://example.org/b#> .\n"
    "@prefix brick: <https://brickschema.org/schema/Brick#> .\n"
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n\n"
)


class TestTheRetypeItself:
    @pytest.mark.parametrize("old,new", sorted(RETYPE.items()))
    def test_every_mapped_term_is_rewritten(self, old, new):
        out, counts = retype_text(f"{HEADER}bldg:x a {old} .\n")
        assert new in out
        # Boundary-aware, because one mapping's TARGET contains its SOURCE
        # (brick:Vibration_Sensor -> brick:Vibration_Sensor_Equipment). A plain
        # substring check reports that correct rewrite as a failure.
        assert not re.search(rf"(?<![\w:]){re.escape(old)}(?![\w-])", out)
        assert counts[old] == 1

    def test_the_result_is_valid_turtle(self):
        out, _ = retype_text(f"{HEADER}bldg:x a brick:Sound_Level_Sensor .\n")
        g = rdflib.Graph()
        g.parse(data=out, format="turtle")
        assert len(g) == 1

    def test_repeated_instances_are_all_caught(self):
        body = HEADER + "".join(f"bldg:s{i} a brick:Sound_Level_Sensor .\n" for i in range(52))
        out, counts = retype_text(body)
        assert counts["brick:Sound_Level_Sensor"] == 52
        assert "brick:Sound_Level_Sensor" not in out


class TestThePrefixMustBindBeforeUse:
    def test_the_declaration_is_added_when_missing(self):
        out, counts = retype_text(f"{HEADER}bldg:x a brick:Sound_Level_Sensor .\n")
        assert "@prefix ontosage:" in out
        assert counts["+@prefix ontosage:"] == 1

    def test_it_lands_in_the_header_not_after_the_usage(self):
        """These TTLs are concatenations: a SECOND prefix block appears far down
        the file. Appending there puts the declaration after the triple it must
        bind, and Turtle rejects that — the failure this test exists to prevent."""
        body = (
            HEADER
            + "bldg:early a brick:Sound_Level_Sensor .\n\n"
            + "@prefix later: <http://example.org/later#> .\n"
            + "bldg:late a brick:Sound_Level_Sensor .\n"
        )
        out, _ = retype_text(body)
        rdflib.Graph().parse(data=out, format="turtle")  # would raise if misplaced
        decl = out.index("@prefix ontosage:")
        assert decl < out.index("bldg:early"), "declaration landed after its first use"

    def test_an_existing_declaration_is_not_duplicated(self):
        body = (
            HEADER + "@prefix ontosage: <http://ontosage.org/capabilities#> .\n"
            "bldg:x a brick:Sound_Level_Sensor .\n"
        )
        out, counts = retype_text(body)
        assert out.count("@prefix ontosage:") == 1
        assert "+@prefix ontosage:" not in counts


class TestWhatMustNotBeTouched:
    def test_a_file_with_nothing_stale_is_left_byte_identical(self):
        body = f"{HEADER}bldg:x a brick:Temperature_Sensor .\n"
        out, counts = retype_text(body)
        assert out == body and counts == {}

    def test_a_longer_class_name_is_not_partially_rewritten(self):
        body = f"{HEADER}bldg:x a brick:Electric_Meter_Panel .\n"
        out, counts = retype_text(body)
        assert "brick:Electric_Meter_Panel" in out
        assert counts == {}

    def test_a_correctly_spelled_class_is_untouched(self):
        body = f"{HEADER}bldg:x a brick:Electrical_Meter .\n"
        out, counts = retype_text(body)
        assert out == body and counts == {}


class TestTheTargetsActuallyExist:
    def test_every_replacement_is_a_declared_class(self):
        """A retype that swaps one undefined term for another fixes nothing."""
        brick = rdflib.Graph()
        onto = rdflib.Graph()
        onto.parse("ontology/ontosage_schema.ttl", format="turtle")
        from rdflib import OWL, RDF, URIRef

        NS = {
            "ontosage": "http://ontosage.org/capabilities#",
            "brick": "https://brickschema.org/schema/Brick#",
        }
        for target in set(RETYPE.values()):
            pfx, local = target.split(":", 1)
            if pfx != "ontosage":
                continue  # brick targets are verified against the live graph
            uri = URIRef(NS[pfx] + local)
            assert (uri, RDF.type, OWL.Class) in onto, f"{target} is not declared"
