"""A point the graph declares is fed by the publisher, without anyone remembering (2026-09-16).

Adding sensors is three steps: write the TTL, upload it, tell the publisher which points to
feed. The third was a script somebody had to run. 498 points were provisioned and uploaded,
and every question about them answered "no recent reading" — the graph knew them, the
publisher did not, and to a stakeholder a point that never reports is indistinguishable from
a broken sensor.

The map is now rebuilt at boot whenever the uploader actually ingested something, so
`docker compose up -d` is genuinely all you need (core contract #11) — for this building and
for the next one.
"""

import inspect
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_the_boot_sequence_refreshes_the_map_after_an_upload():
    """The service is worthless if nothing calls it — the shape of the original defect."""
    source = Path("orchestrator/main.py").read_text(encoding="utf-8")
    assert "refresh_publish_map" in source
    upload_at = source.index("run_idempotent_uploads")
    refresh_at = source.index("refresh_publish_map")
    assert refresh_at > upload_at, "the map must be rebuilt AFTER the TTLs are ingested"


def test_the_refresh_is_guarded_so_a_boot_never_fails_on_it():
    """The dev publisher is a convenience; a building must still boot without it."""
    source = Path("orchestrator/main.py").read_text(encoding="utf-8")
    block = source[source.index("refresh_publish_map") - 600 : source.index("refresh_publish_map") + 600]
    assert "try:" in block and "except Exception" in block


def test_the_derivation_has_one_implementation():
    """The rule that picks a point's table and value column lives in the generator. Copying
    it into the service would give one decision two owners that can disagree."""
    from orchestrator.services import publisher_map

    source = inspect.getsource(publisher_map)
    assert "from generate_publisher_map import build_map, narrow_tables" in source
    # The heuristics themselves must NOT be reimplemented here.
    assert "value_col" not in source.replace("value column", "")


def test_the_map_is_written_atomically():
    """A truncated map feeds nothing, and the publisher would report it as silence."""
    from orchestrator.services import publisher_map

    source = inspect.getsource(publisher_map)
    assert "os.replace" in source
    assert "mkstemp" in source


def test_nothing_here_names_a_building():
    from orchestrator.services import publisher_map

    source = inspect.getsource(publisher_map)
    assert "bldg1" not in source and "abacws" not in source.lower()


@pytest.mark.skipif(
    not Path("input/bldg1_narrow_publish_map.json").exists(),
    reason="no active building mounted",
)
def test_the_active_map_covers_the_tables_it_claims():
    """Every entry needs the three fields the publisher reads, or it silently skips one."""
    data = json.loads(Path("input/bldg1_narrow_publish_map.json").read_text(encoding="utf-8"))
    assert data, "an empty map feeds nothing"
    missing = [
        uuid
        for uuid, row in data.items()
        if not (row.get("table") and row.get("value_col") and row.get("uuid"))
    ]
    assert not missing, missing[:5]


def test_the_most_specific_declaring_class_sets_the_band():
    """A boiler's flow is a Temperature_Sensor (a ROOM's 18-28) and a Leaving_Water_
    Temperature_Sensor. Taking the shallow one published a 69 degC heating flow at 22.5
    degC — BUG-609's mistake in a new place."""
    import inspect

    from orchestrator.services import publisher_map

    source = inspect.getsource(publisher_map)
    assert "DESC(?depth)" in source, "the band query must rank by class depth"
    assert "COUNT(DISTINCT ?anc)" in source


def test_a_correlated_series_is_left_to_its_own_generator():
    """Flow and return come from ONE seed, so their difference is a real delta-T. A
    per-point publisher draws them independently and the delta becomes noise: measured
    2026-09-16, the heating circuit's delta-T fell from 11.08 degC to 0.12 degC."""
    import inspect

    from orchestrator.services import publisher_map

    source = inspect.getsource(publisher_map)
    assert "_CORRELATED_TABLES" in source
    assert "plant_data" in source


def test_the_publisher_prefers_the_point_band_over_the_column_default():
    """The column names a family; only the uuid names the quantity."""
    from pathlib import Path

    source = Path("mysql-dummy-publish-dev/mysql_dummy_publisher.py").read_text(encoding="utf-8")
    assert 's.get("lo") is not None' in source
    assert "_NARROW_RANGES.get" in source  # the default survives for unbanded points
