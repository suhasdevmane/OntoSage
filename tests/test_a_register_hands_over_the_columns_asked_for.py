"""A wide register hands over the columns the question names (BUG-618).

The continuity register carries 23 columns, eight of them provenance stamps that say where the
record came from and nothing about what it says. Handing all 23 to the narrator makes a prompt
that reads as a wall rather than a table. What is dropped is NAMED, so the answer can say the
register holds more than it showed instead of implying those fields do not exist.
"""

import pytest

from orchestrator.agents.sparql_agent import SPARQLAgent

pytestmark = pytest.mark.unit

_CONTINUITY_COLUMNS = [
    "record",
    "recordId",
    "label",
    "servesService",
    "dependsOnSpace",
    "criticality",
    "alternativeLocation",
    "alternativePath",
    "alternativeCapacity",
    "rideThroughMinutes",
    "lastProvedOn",
    "nextTestDue",
    "evidenceReference",
    "recordStatus",
    "retrievedAt",
    "liftedByMapping",
    "derivedFromDocument",
    "recordVersion",
    "owningAuthority",
    "isSimulated",
    "effectiveFrom",
    "recordOwner",
    "comment",
]


def _agent():
    return SPARQLAgent.__new__(SPARQLAgent)


def _results(columns):
    return {"results": {"bindings": [{c: {"value": f"v-{c}"} for c in columns}]}}


def test_a_narrow_register_is_handed_over_untouched():
    agent = _agent()
    columns = ["record", "recordId", "label", "recordStatus", "criticality"]
    results, kept, dropped = agent._project_columns(_results(columns), columns, "anything")
    assert kept == columns
    assert dropped == []


def test_the_columns_the_question_names_survive():
    agent = _agent()
    question = (
        "which services have a verified alternative location, path and operating capacity?"
    )
    _, kept, _ = agent._project_columns(
        _results(_CONTINUITY_COLUMNS), _CONTINUITY_COLUMNS, question
    )
    for column in ("servesService", "alternativeLocation", "alternativePath"):
        assert column in kept, f"{column} was named in the question and must be kept"


def test_a_plural_in_the_question_matches_a_singular_column():
    """The question says "services"; the column is `servesService`. The first version of
    this compared the words literally and dropped the one column the question was about."""
    agent = _agent()
    _, kept, _ = agent._project_columns(
        _results(_CONTINUITY_COLUMNS), _CONTINUITY_COLUMNS, "which services are covered?"
    )
    assert "servesService" in kept


def test_identity_and_status_are_kept_whatever_was_asked():
    agent = _agent()
    _, kept, _ = agent._project_columns(
        _results(_CONTINUITY_COLUMNS), _CONTINUITY_COLUMNS, "how many are there?"
    )
    for column in ("record", "recordId", "label", "recordStatus"):
        assert column in kept


def test_provenance_stamps_go_first():
    """They say where the record came from, never what it says, and the provenance chip
    carries them anyway."""
    agent = _agent()
    _, kept, dropped = agent._project_columns(
        _results(_CONTINUITY_COLUMNS), _CONTINUITY_COLUMNS, "which services have an alternative?"
    )
    for column in ("retrievedAt", "liftedByMapping", "derivedFromDocument", "isSimulated"):
        assert column in dropped
        assert column not in kept


def test_the_handover_is_capped():
    agent = _agent()
    _, kept, _ = agent._project_columns(
        _results(_CONTINUITY_COLUMNS), _CONTINUITY_COLUMNS, "which services have an alternative?"
    )
    assert len(kept) <= SPARQLAgent.MAX_HANDOVER_COLUMNS


def test_the_rows_carry_only_the_kept_columns():
    agent = _agent()
    results, kept, dropped = agent._project_columns(
        _results(_CONTINUITY_COLUMNS), _CONTINUITY_COLUMNS, "which services have an alternative?"
    )
    row = results["results"]["bindings"][0]
    assert set(row) == set(kept)
    assert not set(row) & set(dropped)


def test_every_column_is_either_kept_or_reported():
    """A column that is silently neither is a field the answer cannot know it is missing."""
    agent = _agent()
    _, kept, dropped = agent._project_columns(
        _results(_CONTINUITY_COLUMNS), _CONTINUITY_COLUMNS, "which services have an alternative?"
    )
    assert set(kept) | set(dropped) == set(_CONTINUITY_COLUMNS)
    assert not set(kept) & set(dropped)


def test_a_question_naming_nothing_still_yields_a_usable_register():
    agent = _agent()
    _, kept, _ = agent._project_columns(_results(_CONTINUITY_COLUMNS), _CONTINUITY_COLUMNS, "")
    assert "recordId" in kept
    assert len(kept) <= SPARQLAgent.MAX_HANDOVER_COLUMNS


# The workspace register is the widest one here, and the one that proved the cap could do more
# harm than the width ever did.
_WORKSPACE_COLUMNS = [
    "record", "recordId", "label", "recordStatus", "workspaceKind", "floor", "seatCount",
    "isBookable", "groupFriendly", "suitableForCalls", "powerAccess", "networkRating",
    "daylightAspect", "noiseProfile", "busiestPeriod", "quietestPeriod",
    "nearestVerticalRoute", "setupMinutes", "recoveryMinutes", "accessNote", "comment",
    "openFrom", "openUntil",
    "retrievedAt", "liftedByMapping", "derivedFromDocument", "recordVersion",
    "owningAuthority", "isSimulated", "effectiveFrom", "recordOwner",
]


def test_a_content_column_is_never_dropped_while_a_provenance_stamp_survives():
    """BUG-622: the cap dropped `noiseProfile` and `quietestPeriod`, and the answer then said
    the building records nothing about how quiet a space is. Denying the building's own data
    is a worse failure than a wide prompt, which is why provenance always goes first."""
    agent = _agent()
    _, kept, dropped = agent._project_columns(
        _results(_WORKSPACE_COLUMNS), _WORKSPACE_COLUMNS,
        "which spaces are suitable for quiet focused work for a group of four?",
    )
    surviving_provenance = [c for c in kept if c in SPARQLAgent._PROVENANCE_COLUMNS]
    dropped_content = [c for c in dropped if c not in SPARQLAgent._PROVENANCE_COLUMNS]
    assert not (surviving_provenance and dropped_content), (
        f"dropped content {dropped_content} while keeping provenance {surviving_provenance}"
    )


def test_the_quietness_columns_reach_a_question_about_quiet():
    agent = _agent()
    _, kept, _ = agent._project_columns(
        _results(_WORKSPACE_COLUMNS), _WORKSPACE_COLUMNS,
        "which spaces are suitable for quiet focused work for a group of four?",
    )
    for column in ("noiseProfile", "quietestPeriod", "seatCount", "groupFriendly"):
        assert column in kept, f"{column} answers this question and must survive"


def test_the_real_registers_lose_no_content_at_all():
    """Both registers in the building fit once the provenance stamps are gone. The cap exists
    for something far wider than anything here."""
    agent = _agent()
    for columns in (_CONTINUITY_COLUMNS, _WORKSPACE_COLUMNS):
        _, _, dropped = agent._project_columns(_results(columns), columns, "what is recorded?")
        assert all(c in SPARQLAgent._PROVENANCE_COLUMNS for c in dropped), dropped


def _handover_rows(dates):
    """A register whose `issued` column is mapped onto effectiveFrom — as ten of them are."""
    return [
        {
            "recordId": {"value": f"HO-{i}"},
            "label": {"value": f"AHU-{i} O&M manual"},
            "recordStatus": {"value": "Held"},
            "effectiveFrom": {"value": d},
            "providerName": {"value": "Meridian Mechanical Ltd"},
            "retrievedAt": {"value": "2026-09-16T10:00:00"},
        }
        for i, d in enumerate(dates, 1)
    ]


def test_a_date_that_differs_per_record_is_content_not_a_stamp():
    """"When was the last project handover?" was answered "the records do not contain dates
    for handovers" — from a register carrying an issue date on every row. The lifter stamps
    effectiveFrom from the front matter ONLY when a row has no mapped column, so in ten
    registers it holds the record's real date (BUG-639)."""
    rows = _handover_rows(["2024-09-30", "2025-01-05", "2025-06-11"])
    columns = sorted(rows[0])
    _, kept, dropped = _agent()._project_columns(rows_to_results(rows), columns, "when was the last handover?")
    assert "effectiveFrom" in kept, "a varying date is the record's own fact"
    assert "retrievedAt" in dropped, "a genuine lifter stamp still goes"


def test_one_date_repeated_on_every_record_is_still_a_stamp():
    """Where the register does NOT map a column onto it, every row carries the same front
    matter date — which says nothing about any individual record."""
    rows = _handover_rows(["2026-09-01", "2026-09-01", "2026-09-01"])
    columns = sorted(rows[0])
    _, kept, dropped = _agent()._project_columns(rows_to_results(rows), columns, "when was the last handover?")
    assert "effectiveFrom" in dropped


def rows_to_results(rows):
    return {"results": {"bindings": rows}}
