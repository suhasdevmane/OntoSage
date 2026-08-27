# -*- coding: utf-8 -*-
"""Two health claims about the same tap (2026-08-27, found live).

Authoring bldg1's real potability statement put it into a graph that already held
**five simulated ones** from the synthetic provisioner -- two of them
``not_potable`` for floors 3 and 4, attributed to a plausible-sounding "Estates
Water Safety Group" that never said any such thing.

So the live building simultaneously asserted that its drinking water is potable
(the owner's statement, since 2020-01-01) and that two of its outlets are not.
That is the exact harm Module P was written to prevent, and nothing checked for
it.

The generator's own defence -- "deliberately imperfect, a building where
everything works would make the hard filter untestable" -- is sound for a broken
lift: somebody walks to it, finds it working, nothing is lost. It does not reach
a health claim. The schema that introduced the vocabulary says why in its own
words: *a sensor reading does not support a health statement*, and *being wrong
about drinkability harms someone*.

Potability is no longer generated. It is authored by the owner or it is absent,
and absent renders as "nobody has assessed this outlet", which the schema names
as a legitimate answer.
"""

from pathlib import Path

import pytest

from orchestrator.services.input_validators import (
    validate_building_input,
    validate_potability_agreement,
)

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]
_ONTO = "@prefix ontosage: <http://ontosage.org/capabilities#> .\n"


def _building_dir() -> Path:
    """bldg1's files, whether it is ACTIVE (input/) or parked (bldg1/).

    A test that only knows one layout does not fail when the other is in use — it
    SKIPS, which reads as "checked and fine". Both states are normal here: the
    committed tree has every building parked, and a live session has one active.
    """
    active = _REPO / "input"
    if (active / "building.yaml").is_file():
        return active
    return _REPO / "bldg1"


def _input_root() -> Path:
    """The root to hand validate_building_input, for whichever layout is in use."""
    return _REPO / "input" if (_REPO / "input" / "building.yaml").is_file() else _REPO


def _write(d: Path, name: str, body: str) -> None:
    (d / name).write_text(_ONTO + body, encoding="utf-8")


# ── the contradiction that was live ──────────────────────────────────────────
def test_two_verdicts_on_one_outlet_are_refused(tmp_path):
    _write(
        tmp_path,
        "owner.ttl",
        "bldg:Real a ontosage:PotabilityStatement ;\n"
        "    ontosage:appliesToOutlet bldg:Tap1 ;\n"
        '    ontosage:potabilityValue "potable" .\n',
    )
    _write(
        tmp_path,
        "synth.ttl",
        "bldg:Sim a ontosage:PotabilityStatement ;\n"
        "    ontosage:appliesToOutlet bldg:Tap1 ;\n"
        '    ontosage:potabilityValue "not_potable" ;\n'
        "    ontosage:isSimulated true .\n",
    )
    ok, issues = validate_potability_agreement(tmp_path)
    assert not ok
    assert any("contradictory" in i for i in issues), issues


def test_a_simulated_claim_beside_a_real_one_is_refused_even_when_they_agree(tmp_path):
    """Agreeing today is not a defence: the generator re-rolls, and a health claim
    about a real building must not be simulated alongside the owner's own."""
    _write(
        tmp_path,
        "owner.ttl",
        "bldg:Real a ontosage:PotabilityStatement ;\n"
        "    ontosage:appliesToOutlet bldg:Tap1 ;\n"
        '    ontosage:potabilityValue "potable" .\n',
    )
    _write(
        tmp_path,
        "synth.ttl",
        "bldg:Sim a ontosage:PotabilityStatement ;\n"
        "    ontosage:appliesToOutlet bldg:Tap1 ;\n"
        '    ontosage:potabilityValue "potable" ;\n'
        "    ontosage:isSimulated true .\n",
    )
    ok, issues = validate_potability_agreement(tmp_path)
    assert not ok
    assert any("SIMULATED" in i for i in issues), issues


def test_one_statement_per_outlet_is_fine(tmp_path):
    _write(
        tmp_path,
        "owner.ttl",
        "bldg:Real a ontosage:PotabilityStatement ;\n"
        "    ontosage:appliesToOutlet bldg:Tap1 , bldg:Tap2 ;\n"
        '    ontosage:potabilityValue "potable" .\n',
    )
    assert validate_potability_agreement(tmp_path) == (True, [])


def test_statements_about_different_outlets_do_not_clash(tmp_path):
    """A building may legitimately have one tap potable and another not."""
    _write(
        tmp_path,
        "a.ttl",
        "bldg:A a ontosage:PotabilityStatement ;\n"
        "    ontosage:appliesToOutlet bldg:Tap1 ;\n"
        '    ontosage:potabilityValue "potable" .\n'
        "bldg:B a ontosage:PotabilityStatement ;\n"
        "    ontosage:appliesToOutlet bldg:Tap2 ;\n"
        '    ontosage:potabilityValue "not_potable" .\n',
    )
    assert validate_potability_agreement(tmp_path) == (True, [])


def test_no_statements_at_all_is_fine(tmp_path):
    _write(tmp_path, "a.ttl", "bldg:Room1 a bldg:Room .\n")
    assert validate_potability_agreement(tmp_path) == (True, [])


# ── the generator no longer produces them ────────────────────────────────────
def test_the_synthetic_provisioner_does_not_mint_potability():
    """It minted five for this building, two of them not_potable, under an invented
    authority. A simulated broken lift is a demo; a simulated health claim is not."""
    import importlib.util
    import inspect

    path = _REPO / "scripts" / "provision_synthetic_sources.py"
    spec = importlib.util.spec_from_file_location("_prov_pot", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    src = inspect.getsource(mod)
    assert (
        "a ontosage:PotabilityStatement" not in src
    ), "the provisioner is minting potability statements again"


# ── and the active building is consistent ────────────────────────────────────
def test_the_active_building_has_no_contradictory_claims():
    d = _building_dir()
    if not d.is_dir():
        pytest.skip("bldg1 is neither active nor parked in this checkout")
    ok, issues = validate_potability_agreement(d)
    assert ok, "\n".join(issues)


def test_the_check_runs_as_part_of_building_validation():
    ok, report = validate_building_input("bldg1", _input_root())
    assert "potability agreement" in report["files"], sorted(report["files"])
