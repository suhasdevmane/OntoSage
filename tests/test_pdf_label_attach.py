# -*- coding: utf-8 -*-
"""A room number and its name are ONE room, not two spaces.

A drawing writes a room as two pieces of text placed together inside it — "5.05"
and "Research Laboratory". The extractor turned each into its own space. The
named one carries no zone id, so it can never resolve to anything in the
ontology: on a real floor that was 27-42 permanently unlinkable spaces, which
both understated the link rate and cluttered every space listing.
"""

from __future__ import annotations

import pytest

from orchestrator.services.floor_plan_pipeline import (
    _NAME_ATTACH_RADIUS,
    _attach_names_to_zones,
)
from shared.models import NormalisedPoint, Space

pytestmark = pytest.mark.unit


def zone(zid, x, y, label=None):
    return Space(
        id=f"b.{zid}",
        zone_id=zid,
        label=label or f"Zone {zid}",
        type="zone",
        centroid=NormalisedPoint(x=x, y=y),
        source="text_extraction",
    )


def named(text, x, y, kind="office"):
    return Space(
        id=f"b.fp.{text}",
        zone_id=f"fp.{text}",
        label=text,
        type=kind,
        centroid=NormalisedPoint(x=x, y=y),
        source="text_extraction",
    )


class TestANearbyNameBecomesTheZonesName:
    def test_the_label_is_folded_in_not_duplicated(self):
        z = zone("5.05", 0.50, 0.50)
        left = _attach_names_to_zones([z], [named("Research Laboratory", 0.505, 0.505)])
        assert left == [], "the descriptive label should not survive as its own space"
        assert "Research Laboratory" in z.label
        assert z.zone_id == "5.05"

    def test_the_zone_takes_the_rooms_type(self):
        z = zone("5.05", 0.50, 0.50)
        _attach_names_to_zones([z], [named("Toilet", 0.501, 0.501, kind="toilet")])
        assert z.type == "toilet"

    def test_the_original_text_is_kept_as_an_alias(self):
        z = zone("5.05", 0.50, 0.50)
        _attach_names_to_zones([z], [named("Research Laboratory", 0.502, 0.502)])
        assert "Research Laboratory" in z.aliases

    def test_the_nearest_zone_wins(self):
        near, far = zone("5.05", 0.500, 0.500), zone("5.99", 0.520, 0.500)
        _attach_names_to_zones([near, far], [named("Office", 0.502, 0.500)])
        assert "Office" in near.label and "Office" not in far.label


class TestWhatMustSurviveOnItsOwn:
    def test_a_label_far_from_every_zone_is_kept(self):
        """A legend entry in the page margin is nobody's room name."""
        z = zone("5.05", 0.50, 0.50)
        left = _attach_names_to_zones([z], [named("Fire Alarm Legend", 0.05, 0.95)])
        assert len(left) == 1
        assert z.label == "Zone 5.05", "a distant label must not rename a room"

    def test_a_room_named_but_never_numbered_is_still_a_room(self):
        left = _attach_names_to_zones([], [named("Plant Room", 0.5, 0.5)])
        assert len(left) == 1

    def test_a_label_without_a_position_cannot_be_attached(self):
        z = zone("5.05", 0.50, 0.50)
        orphan = named("Office", 0.0, 0.0)
        orphan.centroid = None
        assert _attach_names_to_zones([z], [orphan]) == [orphan]


class TestExistingNamesAreRespected:
    def test_a_zone_that_already_has_a_real_name_keeps_it(self):
        z = zone("5.05", 0.50, 0.50, label="5.05 Main Reception")
        _attach_names_to_zones([z], [named("Office", 0.501, 0.501)])
        assert z.label == "5.05 Main Reception"

    def test_the_radius_is_tight_enough_to_be_meaningful(self):
        """Loose enough and every room in a corridor claims the same label."""
        assert 0.0 < _NAME_ATTACH_RADIUS <= 0.05
