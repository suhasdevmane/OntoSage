# -*- coding: utf-8 -*-
"""An order the register does not record is never rendered as one (BUG-1391).

MEASURED 2026-10-01. "Which dependency-aware recovery order should incident leaders adopt?"
over 20 Department records answered **DEP-07 -> DEP-05 -> DEP-06 -> DEP-16 -> DEP-03** on one
ask and **DEP-05 -> DEP-06 -> DEP-03 -> DEP-07 -> DEP-16** on the next, each cited to the same
register and each presented as THE order. The records carry no ordering field; the arrows were
the model's, and they disagreed with each other, which is the proof.

The guard is keyed on RECORD IDS, not on arrows: measured over 2,554 de-duplicated stored
answers, a chain of record ids joined by arrows occurs in NONE, while 44% of the corpus's
arrows are routes between rooms, which the floor plan does order. And it is keyed on the ROWS:
a register that carries a priority, a sequence or a link between its own records lifts the
guard by itself.
"""

import pytest

from orchestrator.services.register_facts import rows_record_an_order, unsequence

pytestmark = pytest.mark.unit


def _rows(ids, **extra):
    out = []
    for i in ids:
        row = {"recordId": {"value": i}, "label": {"value": f"Record {i}"}}
        for k, v in extra.items():
            row[k] = {"value": v}
        out.append(row)
    return out


DEP = _rows(["DEP-03", "DEP-05", "DEP-06", "DEP-07", "DEP-16"], escalatesTo="Head of Estates")


class TestTheRowsDecide:
    def test_department_rows_record_no_order(self):
        """``escalatesTo`` names a role, not a record: that is not an ordering of the rows."""
        assert rows_record_an_order(DEP) is False

    @pytest.mark.parametrize(
        "field", ["priority", "sequence", "criticality", "dependsOnService", "stepNumber", "rank"]
    )
    def test_a_field_named_for_an_order_stands_the_guard_down(self, field):
        assert rows_record_an_order(_rows(["DEP-01"], **{field: "1"})) is True

    def test_rows_that_link_to_each_other_stand_the_guard_down(self):
        rows = _rows(["DEP-01", "DEP-02"])
        rows[0]["restoresAfter"] = {"value": "DEP-02"}
        assert rows_record_an_order(rows) is True

    def test_empty_rows_record_nothing(self):
        assert rows_record_an_order([]) is False


class TestTheChainBecomesAList:
    def test_the_live_answer_is_unsequenced_and_says_so(self):
        text = (
            "Adopt the following order: **DEP-07 -> DEP-05 -> DEP-06 -> DEP-16 -> DEP-03**.\n\n"
            "*From the building's documents: Stakeholder Group Register*"
        )
        out = unsequence(text, DEP, "Department")
        assert "->" not in out
        assert "DEP-07, DEP-05, DEP-06, DEP-16, DEP-03" in out
        assert "records no order, priority or dependency" in out
        assert "Stakeholder Group Register" in out, "nothing else in the answer is touched"

    @pytest.mark.parametrize("arrow", ["->", "→", "=>", "-->", "⟶"])
    def test_every_arrow_spelling(self, arrow):
        out = unsequence(f"DEP-07 {arrow} DEP-05 {arrow} DEP-06", DEP, "Department")
        assert "DEP-07, DEP-05, DEP-06" in out

    def test_a_route_between_rooms_is_left_alone(self):
        """A route IS an order the floor plan holds; only this register's ids are touched."""
        text = "Take Room 1.06 -> Stair B -> Room 2.01, then see DEP-07 -> DEP-05."
        out = unsequence(text, DEP, "Department")
        assert "Room 1.06 -> Stair B -> Room 2.01" in out
        assert "DEP-07, DEP-05" in out

    def test_ids_of_another_register_are_left_alone(self):
        """A chain of ids the rows do not hold is not this register's claim to flatten."""
        text = "WO-001 -> WO-002 -> WO-003"
        assert unsequence(text, DEP, "Department") == text

    def test_a_register_that_records_an_order_keeps_its_arrows(self):
        rows = _rows(["DEP-01", "DEP-02"], priority="1")
        text = "DEP-01 -> DEP-02"
        assert unsequence(text, rows, "Department") == text

    def test_no_chain_means_no_change(self):
        text = "DEP-07 handles estates; DEP-05 handles security."
        assert unsequence(text, DEP, "Department") == text

    def test_never_raises(self):
        assert unsequence("DEP-07 -> DEP-05", [object()], "x") == "DEP-07 -> DEP-05"


class TestItIsWired:
    def test_the_register_lane_calls_it(self):
        import inspect

        from orchestrator.agents import sparql_agent

        src = inspect.getsource(sparql_agent)
        assert "unsequence(" in src, (
            "the whole-register narration no longer passes through `unsequence`; an order the "
            "rows do not hold can reach a reader as arrows again"
        )
