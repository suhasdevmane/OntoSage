# -*- coding: utf-8 -*-
"""A non-admin reader is never shown the ontology's own machinery.

MEASURED, tail N (2026-09-30, `docs/phase0/tail_N_2026-09-30_read.md`), 5 of 60 real survey
questions: asking whether there is a mailroom returned the honest decline followed by

    You can add it — no code changes needed:
    1. …
    2. **Point it at its readings** — give each sensor a `ref:hasExternalReference` →
       `ref:hasTimeseriesId` (the column/uuid) plus `ref:storedAt` (a key from
       `database_registry.yaml`).

Design contract 6 is *zero-knowledge → expert coverage*: a user needs no SQL, SPARQL or
schema knowledge. `ref:storedAt` and a config filename are not an answer about a mailroom;
they are an instruction only someone with the deployment in front of them can follow, and
`enablement_hint` is written for exactly that reader and withheld from every other.

WHY THESE TESTS ARE WRITTEN AS CONDITIONS, NOT AS SENTENCES
-----------------------------------------------------------
A test asserting one exact wording rots the first time the wording changes, and then it is
updated to match whatever the code now says — which is how a test stops testing (lessons
#151). So:

* the roles are derived from ``ROLE_PERMISSIONS``, so a role added tomorrow is covered
  tomorrow, and a role granted ``system:admin`` moves sides without editing this file;
* the producers are CALLED and their output is checked against a vocabulary predicate, so
  any rewording of a decline is still checked;
* the call sites are read out of the source with ``ast``, so a NEW call to
  ``enablement_hint`` that forgets the role gate fails here rather than in a measurement.

The contrast cases matter as much: an admin must keep the instructions, and an ordinary
answer about a room must survive untouched. A guard that detects correctly and acts too
widely has destroyed three correct answers in this project already (lessons #135).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Tuple

import pytest

from orchestrator.middleware.rbac import ROLE_PERMISSIONS
from orchestrator.services import building_profile as bp
from orchestrator.services import grounding_guard as gg
from orchestrator.services import referent_resolver as rr

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent

#: Roles that do NOT hold the permission the remediation is gated on, derived rather than
#: listed. Plus the three ways a role can be absent, each of which must also fail closed.
NON_ADMIN_ROLES = sorted(
    r for r in ROLE_PERMISSIONS if gg.REMEDIATION_PERMISSION not in ROLE_PERMISSIONS[r]
)
ADMIN_ROLES = sorted(
    r for r in ROLE_PERMISSIONS if gg.REMEDIATION_PERMISSION in ROLE_PERMISSIONS[r]
)
ABSENT_ROLES = [None, "", "   ", "nonsense", 7]

SUBJECT_KINDS = (
    gg.SUBJECT_SENSOR,
    gg.SUBJECT_SPACE,
    gg.SUBJECT_EQUIPMENT,
    gg.SUBJECT_DOCUMENT,
    "a kind nothing declares",
)


def _dirt(text: str):
    """What in ``text`` names machinery the reader cannot see, or None."""
    return gg.names_internal_schema(text) or gg.names_internal_vocabulary(text)


# ── 1. who the gate lets through ────────────────────────────────────────────────


def test_the_gate_is_a_permission_not_a_role_name():
    """`reader_is_admin` is True for exactly the roles holding the permission, and nothing
    else. Derived from the catalogue, so granting a role `system:admin` moves it here."""
    assert ADMIN_ROLES, "no role holds the remediation permission — the catalogue is broken"
    for role in ADMIN_ROLES:
        assert gg.reader_is_admin(role) is True, role
    for role in NON_ADMIN_ROLES:
        assert gg.reader_is_admin(role) is False, role


@pytest.mark.parametrize("role", ABSENT_ROLES)
def test_a_missing_or_malformed_role_fails_closed(role):
    """No role, a blank one, an unknown one and a non-string all get the plain decline."""
    assert gg.reader_is_admin(role) is False


def test_a_turn_with_no_user_role_on_the_bus_fails_closed():
    """`reader_is_admin_in` reads `intermediate_results["user_role"]`. An entry point that
    forgot to write it must produce the plain decline, never the admin one."""

    class _State:
        def __init__(self, results):
            self.intermediate_results = results

    assert gg.reader_is_admin_in(_State({})) is False
    assert gg.reader_is_admin_in(_State({"user_role": "facility_manager"})) is False
    assert gg.reader_is_admin_in(_State(None)) is False
    assert gg.reader_is_admin_in(object()) is False


# ── 2. the condition: no producer hands a non-admin internal vocabulary ─────────


@pytest.mark.parametrize("role", NON_ADMIN_ROLES + ABSENT_ROLES)
@pytest.mark.parametrize("kind", SUBJECT_KINDS)
def test_the_enablement_hint_names_no_machinery_to_a_non_admin(role, kind):
    text = gg.enablement_hint(kind, "the mailroom", for_admin=gg.reader_is_admin(role))
    found = _dirt(text)
    assert found is None, f"role={role!r} kind={kind!r} was shown {found!r}: {text!r}"


@pytest.mark.parametrize("role", NON_ADMIN_ROLES + ABSENT_ROLES)
def test_the_building_profile_decline_names_no_machinery_to_a_non_admin(role):
    text = bp.enablement_hint("Abacws Building", for_admin=gg.reader_is_admin(role))
    found = _dirt(text)
    assert found is None, f"role={role!r} was shown {found!r}: {text!r}"


@pytest.mark.parametrize(
    "kind", (rr.KIND_FLOOR, rr.KIND_SPACE, rr.KIND_EQUIPMENT, rr.KIND_MEASURAND)
)
def test_the_referent_clarification_names_no_machinery_to_a_non_admin(kind):
    typed = rr.TypedReferent(kind=kind, token="mailroom", phrase="the mailroom", head="mailroom")
    text = rr.ReferentResolver._typed_clarification(
        typed, ["Room 5.01", "Room 5.02"], "Abacws Building", for_admin=False
    )
    found = _dirt(text)
    assert found is None, f"kind={kind!r} was shown {found!r}: {text!r}"


def test_the_default_is_the_plain_decline():
    """`for_admin` defaults to False on every producer, so a caller that does not know who
    is reading fails toward the message everyone may see."""
    for kind in SUBJECT_KINDS:
        assert _dirt(gg.enablement_hint(kind, "the mailroom")) is None
    assert _dirt(bp.enablement_hint("Abacws Building")) is None


# ── 3. the contrast: an admin keeps what an admin can act on ───────────────────


def test_an_admin_still_gets_the_onboarding_instructions():
    """If this passes for a non-admin too, the gate is gone; if it fails, the guard has
    widened past the defect and taken the admin's next step with it."""
    text = gg.enablement_hint(gg.SUBJECT_SENSOR, "the mailroom", for_admin=True)
    assert gg.names_internal_schema(text) is not None
    assert "no code changes needed" in text


# ── 4. the source condition: no call site may forget the gate ──────────────────


def _enablement_calls() -> List[Tuple[str, int, ast.Call]]:
    out: List[Tuple[str, int, ast.Call]] = []
    for path in sorted((REPO / "orchestrator").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        if "enablement_hint" not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:  # pragma: no cover - the product must parse
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name == "enablement_hint":
                out.append((str(path.relative_to(REPO)), node.lineno, node))
    return out


def test_there_is_at_least_one_call_site_to_check():
    """A source scan that silently matches nothing is a test that passes for the wrong
    reason (lessons #145)."""
    assert len(_enablement_calls()) >= 4


def test_no_call_site_hands_the_remediation_out_unconditionally():
    """THE CONDITION, pinned in the source rather than in a sentence.

    A call to `enablement_hint` may leave `for_admin` defaulted (False — the plain decline)
    or pass a value computed from the reader's role. It may NEVER pass a literal True, and
    it may never pass the admin flag positionally where a reader of the call cannot see what
    it is. Either would put the onboarding instructions in front of whoever asked.
    """
    offenders = []
    for rel, lineno, node in _enablement_calls():
        for kw in node.keywords:
            if kw.arg != "for_admin":
                continue
            if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                offenders.append(f"{rel}:{lineno} passes for_admin=True unconditionally")
        # grounding_guard.enablement_hint(kind, subject, for_admin) — a third positional is
        # the flag, and a literal there is the same defect wearing different clothes.
        if len(node.args) >= 3 and isinstance(node.args[2], ast.Constant):
            if node.args[2].value is True:
                offenders.append(f"{rel}:{lineno} passes the admin flag positionally as True")
    assert not offenders, (
        "the remediation block is admin-only (design contract 6/7); these hand it to every "
        f"reader: {offenders}"
    )


# ── 5. the safety net, for text a model wrote rather than text we composed ─────


REFLOWED = (
    "I don't have that specific information on record for **Abacws Building**. "
    "You can add it — no code changes needed: "
    "1. **Describe it in the ontology** — upload a TTL naming the entity. "
    "2. **Point it at its readings** — give each sensor a `ref:hasExternalReference` "
    "plus `ref:storedAt` (a key from `database_registry.yaml`). "
    "3. **Register the database** holding those rows."
)


def test_a_removed_step_does_not_leave_an_empty_numbered_item():
    """The rendered defect: "1." with nothing after it, because the removal is clause-level
    and the clause was the whole step. No marker may survive with nothing behind it."""
    out = gg.strip_schema_remediation(REFLOWED)
    orphans = [
        m.group(0)
        for m in gg._ORDINAL_MARK_RE.finditer(out)
        if not out[m.end() :].split("\n")[0].strip()[:1]
    ]
    assert not orphans, f"orphan step number(s) {orphans} in: {out!r}"
    assert " 1. 2." not in out and "1.\n2." not in out.replace("1. ", "1. ")


def test_a_list_a_reader_sees_still_counts_from_one():
    """Dropping step 1 of three must leave a two-step list, not steps 2 and 3."""
    listed = (
        "You can add it:\n"
        "1. Upload a TTL naming the entity.\n"
        "2. Point it at its readings.\n"
        "3. Register the database.\n"
    )
    out = gg.strip_schema_remediation(listed)
    numbers = [int(line.split(".", 1)[0]) for line in out.split("\n") if line[:1].isdigit()]
    assert numbers == list(range(1, len(numbers) + 1)), out


def test_the_net_removes_the_vocabulary_not_only_the_instruction():
    """`strip_schema_remediation` catches "upload a TTL"; it does not catch a sentence that
    merely USES the schema. A model narrating the TBox writes the second kind."""
    written_by_a_model = (
        "Abacws Building holds no mailroom record. Each sensor carries a "
        "`ref:hasTimeseriesId` pointing at a key in `database_registry.yaml`."
    )
    assert gg.schema_remediation_reason(written_by_a_model) is None
    out = gg.strip_internal_schema(written_by_a_model)
    assert gg.names_internal_schema(out) is None, out
    assert "Abacws Building holds no mailroom record." in out


@pytest.mark.parametrize(
    "text",
    [
        "Room 5.01 averaged 21.4 °C over the last 24 hours, from 1 sensor.",
        "Floor 3. Floor 4. Both are warmer than the building mean.",
        "1. Open a window. 2. Wait ten minutes. 3. Ask again.",
        "This building has no lifts recorded in its model.",
        "The cleaning task register holds 120 records, 3 of them overdue.",
    ],
)
def test_an_ordinary_answer_is_returned_byte_for_byte(text):
    """The guard that acts wider than the defect is the one that destroys a correct answer
    (lessons #135). Nothing here names machinery, so nothing here may change."""
    assert gg.names_internal_schema(text) is None
    assert gg.strip_schema_remediation(text) == text
    assert gg.strip_internal_schema(text) == text
    assert gg._tidy_ordinals(text) == text


def test_a_brick_class_name_on_its_own_is_not_treated_as_machinery():
    """Design contract 6 serves experts too: an analyst asking which class a point carries
    is entitled to the answer. Only the NAMESPACED form is withheld."""
    assert gg.names_internal_schema("The point is typed Air_Temperature_Sensor.") is None
    assert gg.names_internal_schema("Room 5.01 has a CO2 sensor and a humidity sensor.") is None
