# -*- coding: utf-8 -*-
"""bldg4 — the wholly fictional building for GUI onboarding testing (2026-08-27).

TODO-072's thesis is that a building can be onboarded end to end **through the
Admin Console** — identity, ontology, datasource, documents, floor plans — with
nothing hand-placed in `input/`. Proving that needs a building whose files exist
but are NOT already installed.

Two things this file guards, and both have already gone wrong once in this repo:

* **It must stay fictional.** bldg1 is a real building, and this project has
  already had to remove a simulated health claim made about one. bldg4's
  namespace is under example.org, its provenance is `synthetic`, and no room,
  sensor or reading corresponds to anything real.
* **The identity delta must match the env it describes.** The first .env4 kept
  bldg1's BUILDING_NAME, so the test building would have reported itself as
  "Abacws Building" — a fixture that lies about which building it is makes every
  onboarding observation worthless.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]
_B4 = _REPO / "bldg4"


def _kv(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _skip_if_absent():
    if not _B4.is_dir():
        pytest.skip("bldg4 is not present in this checkout")


# ── it exists and is well formed ─────────────────────────────────────────────
def test_the_fixture_carries_what_a_building_needs():
    _skip_if_absent()
    for name in (
        "building.yaml",
        "bldg4.ttl",
        "bldg4_capabilities.ttl",
        "database_registry.yaml",
        "env.building",
        "README.md",
    ):
        assert (_B4 / name).is_file(), name
    assert (_B4 / "documents").is_dir()


def test_the_ttls_parse():
    _skip_if_absent()
    rdflib = pytest.importorskip("rdflib")
    for ttl in sorted(_B4.glob("*.ttl")):
        g = rdflib.Graph()
        g.parse(str(ttl), format="turtle")
        assert len(g) > 0, ttl.name


def test_the_namespace_matches_what_building_yaml_declares():
    """The startup validator hard-fails a mismatch, which is the right behaviour and
    a miserable way to discover a typo mid-demo."""
    _skip_if_absent()
    import yaml

    declared = yaml.safe_load((_B4 / "building.yaml").read_text(encoding="utf-8"))[
        "ontology_namespace"
    ]
    ttl = (_B4 / "bldg4.ttl").read_text(encoding="utf-8")
    assert f"@prefix bldg:  <{declared}>" in ttl or f"@prefix bldg: <{declared}>" in ttl


# ── it must stay fictional ───────────────────────────────────────────────────
def test_the_building_declares_itself_synthetic():
    _skip_if_absent()
    import yaml

    cfg = yaml.safe_load((_B4 / "building.yaml").read_text(encoding="utf-8"))
    assert cfg["provenance"]["nature"] == "synthetic"


def test_the_namespace_cannot_collide_with_a_real_estate():
    _skip_if_absent()
    import yaml

    ns = yaml.safe_load((_B4 / "building.yaml").read_text(encoding="utf-8"))["ontology_namespace"]
    assert "example.org" in ns, ns


def test_no_real_building_is_named_anywhere_in_the_fixture():
    """A fixture that borrows a real building's name or namespace stops being a
    fixture and starts being a claim about that building."""
    _skip_if_absent()
    banned = ("abacws", "cardiff.ac.uk", "buildsys.org")
    for f in sorted(_B4.rglob("*")):
        if not f.is_file() or f.suffix in (".png", ".pdf", ".dxf", ".dwg"):
            continue
        low = f.read_text(encoding="utf-8", errors="replace").lower()
        for word in banned:
            assert word not in low, f"{f.name} names {word}"


# ── the identity delta must not lie ──────────────────────────────────────────
def test_the_tracked_delta_matches_the_env_it_describes():
    """.env4 is gitignored, so env.building is the only record of bldg4's identity
    that survives a clone. A first pass left BUILDING_NAME as "Abacws Building" and
    the test building would have reported itself as bldg1."""
    _skip_if_absent()
    if not (_REPO / ".env4").is_file():
        pytest.skip(".env4 is not present (gitignored; created locally)")
    delta = _kv(_B4 / "env.building")
    env4 = _kv(_REPO / ".env4")
    mismatched = {k: (v, env4.get(k)) for k, v in delta.items() if env4.get(k) != v}
    assert not mismatched, mismatched


def test_the_delta_names_bldg4_throughout():
    _skip_if_absent()
    delta = _kv(_B4 / "env.building")
    assert delta["BUILDING_ID"] == "bldg4"
    assert delta["COMPOSE_PROJECT_NAME"] == "ontosage_bldgtest"
    assert delta["MYSQL_DATABASE"] != "sensordb", "must not share bldg1's database"


# ── and it must not be installed ─────────────────────────────────────────────
def test_no_building_is_committed_as_installed():
    """Copying a building into input/ would test the file loader — which already works
    — instead of the console, which is the claim under test.

    Asked of GIT, not of the working tree. The first version read input/building.yaml
    and failed the moment bldg4 was activated to VERIFY it boots, which is a thing that
    has to happen; and in the parked state it skipped, which reads as "checked and
    fine". Neither told anyone whether the repository is clean. What is tracked is the
    durable property, it is true in every working state, and it is exactly Workflow
    rule 8: a fresh clone has input/, .env and docker-compose.yml ABSENT.
    """
    import subprocess

    for path in ("input/", "docker-compose.yml"):
        out = subprocess.run(  # nosec B603 B607 - fixed argv, repo-local
            ["git", "ls-files", path],
            cwd=_REPO,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.strip()
        assert not out, f"{path} is tracked in git; the committed tree must have no active building"


def test_the_fixture_survives_as_something_to_onboard():
    """Parked at bldg4/, or momentarily active while being verified — but present."""
    active = _REPO / "input" / "building.yaml"
    if active.is_file():
        import yaml

        if yaml.safe_load(active.read_text(encoding="utf-8")).get("building_id") == "bldg4":
            return  # active for verification; the git check above governs what ships
    assert (_B4 / "building.yaml").is_file(), "the bldg4 fixture is gone"


def test_the_generator_is_deterministic():
    """Same inputs, same UUIDs. A fixture whose ids move cannot be used to check
    that an upload landed."""
    import importlib.util

    path = _REPO / "scripts" / "generate_bldg4_fixture.py"
    spec = importlib.util.spec_from_file_location("_gen_b4", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.point_uuid("bldg4", "temperature", "Room_1_03") == mod.point_uuid(
        "bldg4", "temperature", "Room_1_03"
    )
    assert mod.point_uuid("bldg4", "temperature", "Room_1_03") != mod.point_uuid(
        "bldg4", "humidity", "Room_1_03"
    )
