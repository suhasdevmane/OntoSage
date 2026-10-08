"""BUG-1460: a one-row register answer was announced as "The building name is: <row label>".

DEV D024 (v1, 2026-10-08): "Which luminaire layout, distribution, colour quality, flicker
performance and control zoning best supports each task and user group?" was answered
"The building name is: **Fire service liaison**" -- a stakeholder-group record named as the
building. BUG-421 had already narrowed that template's trigger to the whole words "building" and
"name|named|called" plus exactly one row; this question contains neither word. The register lane
passes its GUIDANCE text in ``_format_results``' ``user_query`` position (so the narration prompt
embeds it), and the guidance always says "this building holds" while the counted facts appended
to it say "named". Every special-case template now reads the user's question, passed separately.
"""

import ast
import inspect
import textwrap

import pytest

from orchestrator.agents import sparql_agent as sa
from orchestrator.agents.sparql_agent import SPARQLAgent

pytestmark = pytest.mark.unit

QUESTION = (
    "Which luminaire layout, distribution, colour quality, flicker performance and control "
    "zoning best supports each task and user group?"
)
# The shape the register lane hands over: the question, then its own instructions and facts.
# As D024's was: "this building holds" + "named", which fires the building-name template.
GUIDANCE = (
    f"{QUESTION}\n\n(These are all 82 Stakeholder Group records this building holds. "
    "Answer only from these records.)\n\nRECORDED FACTS -- every group named in the group is in it."
)
# Counted facts can also carry an IRI, and a '#' anywhere fires the label/definition template
# ("**Fire service liaison**\n\nDefinition: N/A", measured on the unfixed code).
GUIDANCE_WITH_IRI = GUIDANCE + " Source: bldg:StakeholderGroup#fire."
ONE_ROW = {
    "results": {"bindings": [{"label": {"type": "literal", "value": "Fire service liaison"}}]}
}


@pytest.fixture
def agent(monkeypatch):
    a = SPARQLAgent.__new__(SPARQLAgent)

    async def same_rows(bindings):
        return bindings

    monkeypatch.setattr(a, "_label_bare_subjects", same_rows)

    async def narrate(prompt, task_type=None, **_):
        return "NARRATED FROM THE ROWS"

    monkeypatch.setattr(sa.llm_manager, "generate", narrate)
    return a


@pytest.mark.parametrize("guidance", [GUIDANCE, GUIDANCE_WITH_IRI], ids=["named", "iri"])
async def test_a_one_row_register_answer_is_narrated_not_named_as_the_building(agent, guidance):
    out = await agent._format_results(
        ONE_ROW, guidance, "SELECT ?label WHERE {}", True, row_limit=40, question=QUESTION
    )
    assert "building name is" not in out.lower()
    assert "Definition:" not in out  # the label/definition template reads the same text
    assert out == "NARRATED FROM THE ROWS"


async def test_the_question_that_asks_for_the_building_name_still_gets_it(agent):
    rows = {"results": {"bindings": [{"label": {"type": "literal", "value": "Abacws Building"}}]}}
    out = await agent._format_results(
        rows, "What is the name of this building?", "SELECT ?label WHERE {}", True
    )
    assert out == "The building name is: **Abacws Building**"


async def test_the_template_is_decided_by_the_question_when_one_is_passed(agent):
    """The guidance may say anything; the question decides."""
    rows = {"results": {"bindings": [{"label": {"type": "literal", "value": "Abacws Building"}}]}}
    out = await agent._format_results(
        rows,
        "(instructions that mention neither word)",
        "SELECT ?label WHERE {}",
        True,
        question="What is this building called?",
    )
    assert out == "The building name is: **Abacws Building**"


def _guidance_calls():
    """Every call of self._format_results whose text argument is a name other than user_query."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(sa)))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_format_results"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Name)
            and node.args[1].id != "user_query"
        ):
            yield node


def test_every_call_that_hands_over_instructions_also_passes_the_question():
    calls = list(_guidance_calls())
    # The register handover and the metrology answer both pass their guidance (2026-10-08).
    assert len(calls) >= 2, "expected the register and metrology call sites"
    for call in calls:
        kw = {k.arg: k.value for k in call.keywords}
        assert "question" in kw, f"line {call.lineno}: guidance passed without question="
        assert isinstance(kw["question"], ast.Name) and kw["question"].id == "user_query"
