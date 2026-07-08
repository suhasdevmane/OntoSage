"""Unit tests for Phase 12B TTL validator.

Each test stages a synthetic `input/<bldg>/` directory under tmp_path so we
can independently exercise: matching TTL, prefix mismatch, missing prefix,
unparseable TTL, no-TTL-files, and the empty-namespace warning.

SHACL is exercised only when brickschema is importable; the test is skipped
otherwise so CI without optional deps still passes.
"""

from __future__ import annotations

import pytest

from orchestrator.services.ttl_validator import (
    TTLValidationError,
    assert_ttl_validation_or_die,
    validate_building_ttls,
)


GOOD_TTL = """\
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix bldg:  <http://example.com/test-building#> .

bldg:Sensor_A a brick:Temperature_Sensor .
bldg:Sensor_B a brick:CO2_Sensor .
"""

MISMATCH_TTL = """\
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix bldg:  <http://WRONG.example.com/different-building#> .

bldg:Sensor_A a brick:Temperature_Sensor .
"""

NO_PREFIX_TTL = """\
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .

<http://example.com/no-prefix#X> a brick:Sensor .
"""

UNPARSEABLE_TTL = """\
this is not turtle at all { malformed garbage <<<<>>>>
"""

EMPTY_NAMESPACE_TTL = """\
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix bldg:  <http://example.com/test-building#> .

# Prefix declared but never used.
brick:Temperature_Sensor a rdf:Resource .
"""


@pytest.fixture
def staged(tmp_path):
    """Build an `input/bldg_test/` skeleton; the test fills it with TTLs."""
    bldg = tmp_path / "input" / "bldg_test"
    bldg.mkdir(parents=True)
    return tmp_path, bldg


def test_matching_ttl_passes(staged):
    tmp_path, bldg = staged
    (bldg / "good.ttl").write_text(GOOD_TTL, encoding="utf-8")

    report = validate_building_ttls(
        building_id="bldg_test",
        declared_namespace="http://example.com/test-building#",
        building_prefix="bldg",
        input_root=tmp_path / "input",
    )
    assert report.ok, f"Expected no hard failures; got {report.hard_failures}"
    assert report.ttl_files_checked == 1
    assert report.warnings == []


def test_prefix_namespace_mismatch_hard_fails(staged):
    tmp_path, bldg = staged
    (bldg / "mismatch.ttl").write_text(MISMATCH_TTL, encoding="utf-8")

    report = validate_building_ttls(
        building_id="bldg_test",
        declared_namespace="http://example.com/test-building#",
        building_prefix="bldg",
        input_root=tmp_path / "input",
    )
    assert not report.ok
    assert len(report.hard_failures) == 1
    msg = report.hard_failures[0].message
    assert "mismatch" in msg.lower()
    assert "http://wrong.example.com" in msg.lower()


def test_missing_prefix_hard_fails(staged):
    tmp_path, bldg = staged
    (bldg / "no_prefix.ttl").write_text(NO_PREFIX_TTL, encoding="utf-8")

    report = validate_building_ttls(
        building_id="bldg_test",
        declared_namespace="http://example.com/test-building#",
        building_prefix="bldg",
        input_root=tmp_path / "input",
    )
    assert not report.ok
    assert "MISSING" in report.hard_failures[0].message


def test_unparseable_ttl_hard_fails(staged):
    tmp_path, bldg = staged
    (bldg / "broken.ttl").write_text(UNPARSEABLE_TTL, encoding="utf-8")

    report = validate_building_ttls(
        building_id="bldg_test",
        declared_namespace="http://example.com/test-building#",
        building_prefix="bldg",
        input_root=tmp_path / "input",
    )
    assert not report.ok
    assert "parse" in report.hard_failures[0].message.lower()


def test_no_ttl_files_warns_not_fails(staged):
    tmp_path, _bldg = staged
    report = validate_building_ttls(
        building_id="bldg_test",
        declared_namespace="http://example.com/test-building#",
        building_prefix="bldg",
        input_root=tmp_path / "input",
    )
    assert report.ok, "Missing TTLs should be a warning, not a hard failure"
    assert len(report.warnings) == 1
    assert "No *.ttl" in report.warnings[0].message


def test_empty_namespace_warns(staged):
    tmp_path, bldg = staged
    (bldg / "empty_ns.ttl").write_text(EMPTY_NAMESPACE_TTL, encoding="utf-8")

    report = validate_building_ttls(
        building_id="bldg_test",
        declared_namespace="http://example.com/test-building#",
        building_prefix="bldg",
        input_root=tmp_path / "input",
    )
    assert report.ok
    assert any(
        "zero triples" in w.message for w in report.warnings
    ), f"Expected zero-triples warning; got {report.warnings}"


def test_assert_or_die_raises_on_mismatch(staged):
    tmp_path, bldg = staged
    (bldg / "mismatch.ttl").write_text(MISMATCH_TTL, encoding="utf-8")

    with pytest.raises(TTLValidationError) as excinfo:
        assert_ttl_validation_or_die(
            building_id="bldg_test",
            declared_namespace="http://example.com/test-building#",
            building_prefix="bldg",
            input_root=tmp_path / "input",
        )
    err_msg = str(excinfo.value)
    assert "bldg_test" in err_msg
    assert "mismatch" in err_msg.lower()


def test_assert_or_die_returns_report_on_success(staged):
    tmp_path, bldg = staged
    (bldg / "good.ttl").write_text(GOOD_TTL, encoding="utf-8")

    report = assert_ttl_validation_or_die(
        building_id="bldg_test",
        declared_namespace="http://example.com/test-building#",
        building_prefix="bldg",
        input_root=tmp_path / "input",
    )
    assert report.ok
    assert report.ttl_files_checked == 1


def test_legacy_root_layout_ttl_picked_up(tmp_path):
    """Phase 3 layout: TTLs at input/<bldg>_*.ttl directly under input/."""
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / "bldg_test").mkdir()
    legacy_file = input_root / "bldg_test_abacws_metadata.ttl"
    legacy_file.write_text(GOOD_TTL, encoding="utf-8")

    report = validate_building_ttls(
        building_id="bldg_test",
        declared_namespace="http://example.com/test-building#",
        building_prefix="bldg",
        input_root=input_root,
    )
    assert report.ok
    assert report.ttl_files_checked == 1


def test_multiple_ttls_aggregate(staged):
    """When several TTLs share the building, all must validate; one bad
    file in the pack triggers a hard fail."""
    tmp_path, bldg = staged
    (bldg / "good.ttl").write_text(GOOD_TTL, encoding="utf-8")
    (bldg / "mismatch.ttl").write_text(MISMATCH_TTL, encoding="utf-8")

    report = validate_building_ttls(
        building_id="bldg_test",
        declared_namespace="http://example.com/test-building#",
        building_prefix="bldg",
        input_root=tmp_path / "input",
    )
    assert report.ttl_files_checked == 2
    assert not report.ok
    assert len(report.hard_failures) == 1
    assert "mismatch.ttl" in report.hard_failures[0].ttl_path


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("brickschema"),
    reason="brickschema package not installed",
)
def test_shacl_run_when_brickschema_available(staged):
    """When brickschema is available and run_shacl=True, the validator
    can call into pyshacl.  We only assert it doesn't crash and that the
    overall report is still ok (Brick SHACL is informational, not blocking)."""
    tmp_path, bldg = staged
    (bldg / "good.ttl").write_text(GOOD_TTL, encoding="utf-8")

    report = validate_building_ttls(
        building_id="bldg_test",
        declared_namespace="http://example.com/test-building#",
        building_prefix="bldg",
        input_root=tmp_path / "input",
        run_shacl=True,
    )
    assert report.ok, "SHACL findings are WARN, not HARD_FAIL"


# ── @base consistency (2026-06-13) ─────────────────────────────────────────────

BASE_MATCHING_TTL = """\
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix bldg:  <http://example.com/test-building#> .
@base <http://example.com/test-building#> .

bldg:Sensor_A a brick:Temperature_Sensor .
"""

BASE_MISMATCH_TTL = """\
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix bldg:  <http://example.com/test-building#> .
@base <http://somewhere-else.example.org/other#> .

bldg:Sensor_A a brick:Temperature_Sensor .
"""

BASE_SPARQL_STYLE_TTL = """\
BASE <http://somewhere-else.example.org/other#>
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix bldg:  <http://example.com/test-building#> .

bldg:Sensor_A a brick:Temperature_Sensor .
"""


def _run(tmp_path):
    return validate_building_ttls(
        building_id="bldg_test",
        declared_namespace="http://example.com/test-building#",
        building_prefix="bldg",
        input_root=tmp_path / "input",
    )


def test_base_matching_namespace_no_warning(staged):
    tmp_path, bldg = staged
    (bldg / "base_ok.ttl").write_text(BASE_MATCHING_TTL, encoding="utf-8")
    report = _run(tmp_path)
    assert report.ok
    assert report.warnings == []


def test_base_mismatch_warns_but_does_not_fail(staged):
    """A foreign @base is a WARN: relative IRIs would resolve into another
    namespace, but prefixed-name-only files still work."""
    tmp_path, bldg = staged
    (bldg / "base_bad.ttl").write_text(BASE_MISMATCH_TTL, encoding="utf-8")
    report = _run(tmp_path)
    assert report.ok, "base mismatch must not hard-fail"
    assert len(report.warnings) == 1
    assert "@base" in report.warnings[0].message
    assert "somewhere-else" in report.warnings[0].message


def test_sparql_style_base_also_detected(staged):
    tmp_path, bldg = staged
    (bldg / "base_sparql.ttl").write_text(BASE_SPARQL_STYLE_TTL, encoding="utf-8")
    report = _run(tmp_path)
    assert report.ok
    assert any("@base" in w.message for w in report.warnings)


def test_absent_base_is_fine(staged):
    """Files without @base (the common case) must not warn."""
    tmp_path, bldg = staged
    (bldg / "good.ttl").write_text(GOOD_TTL, encoding="utf-8")
    report = _run(tmp_path)
    assert report.ok
    assert report.warnings == []


# ── Scaffolding exclusion (2026-06-13 — restart crash-loop fix) ──────────────


def test_templates_scaffolding_ttl_excluded_flat_layout(tmp_path):
    """Flat layout: a bad TTL under input/_templates/ must NOT gate startup.

    Reproduces the restart crash-loop where input/_templates/concepts_overlay.ttl
    (missing @prefix bldg:) hard-failed validation of the active building and
    crash-looped the orchestrator on every restart.
    """
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / "building.yaml").write_text("building_id: bldg_test\n", encoding="utf-8")
    (input_root / "good.ttl").write_text(GOOD_TTL, encoding="utf-8")
    templates = input_root / "_templates"
    templates.mkdir()
    (templates / "concepts_overlay.ttl").write_text(NO_PREFIX_TTL, encoding="utf-8")

    report = validate_building_ttls(
        building_id="bldg_test",
        declared_namespace="http://example.com/test-building#",
        building_prefix="bldg",
        input_root=input_root,
    )
    assert report.ok, f"_templates TTL should be excluded; got {report.hard_failures}"
    assert report.ttl_files_checked == 1  # only good.ttl, never the template


def test_non_ontology_subdirs_excluded(staged):
    """documents/, data/, personas/ and any underscore-prefixed dir hold
    scaffolding/examples, not the building ontology — never validated."""
    tmp_path, bldg = staged
    (bldg / "good.ttl").write_text(GOOD_TTL, encoding="utf-8")
    for sub in ("documents", "data", "personas", "_scratch"):
        d = bldg / sub
        d.mkdir()
        (d / "example.ttl").write_text(NO_PREFIX_TTL, encoding="utf-8")

    report = validate_building_ttls(
        building_id="bldg_test",
        declared_namespace="http://example.com/test-building#",
        building_prefix="bldg",
        input_root=tmp_path / "input",
    )
    assert report.ok, f"scaffolding subdir TTLs should be excluded; got {report.hard_failures}"
    assert report.ttl_files_checked == 1


def test_real_nested_ontology_still_validated(staged):
    """A genuine bad ontology TTL in a NON-scaffolding nested dir must still
    hard-fail (we only skip scaffolding, not all subdirectories)."""
    tmp_path, bldg = staged
    (bldg / "good.ttl").write_text(GOOD_TTL, encoding="utf-8")
    nested = bldg / "ontology"
    nested.mkdir()
    (nested / "bad.ttl").write_text(MISMATCH_TTL, encoding="utf-8")

    report = validate_building_ttls(
        building_id="bldg_test",
        declared_namespace="http://example.com/test-building#",
        building_prefix="bldg",
        input_root=tmp_path / "input",
    )
    assert not report.ok
    assert report.ttl_files_checked == 2
    assert "bad.ttl" in report.hard_failures[0].ttl_path
