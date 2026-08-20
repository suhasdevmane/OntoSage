# -*- coding: utf-8 -*-
"""V5-T22: label-aware scoring for the injected-anomaly grader."""

from __future__ import annotations

import pytest

from scripts.grade_anomalies import score_labels

pytestmark = pytest.mark.unit


def _label(det, uid, start, end):
    return {
        "detector_expected": det,
        "uuid": uid,
        "window_start": start,
        "window_end": end,
    }


def _ep(det, uid, start, end):
    return {
        "event_type": f"anomaly:{det}",
        "subject_uuid": uid,
        "start_dt": start,
        "end_dt": end,
    }


def test_matching_episode_scores_recall_and_latency():
    labels = [_label("stuck", "u1", "2026-08-18 06:00:00", "2026-08-18 12:00:00")]
    eps = [_ep("stuck", "u1", "2026-08-18 07:00:00", "2026-08-18 12:00:00")]
    cards = score_labels(labels, eps)
    c = cards["stuck"]
    assert c["recall"] == 1.0 and c["precision"] == 1.0 and c["f1"] == 1.0
    assert c["mean_latency_h"] == 1.0


def test_wrong_detector_class_counts_against_precision():
    labels = [_label("dropout", "u1", "2026-08-18 06:00:00", "2026-08-18 09:00:00")]
    eps = [_ep("spike", "u1", "2026-08-18 06:30:00", "2026-08-18 06:40:00")]
    cards = score_labels(labels, eps)
    c = cards["dropout"]
    assert c["recall"] == 0.0 and c["misclassified"] == 1 and c["precision"] == 0.0


def test_other_sensors_and_windows_are_ignored():
    labels = [_label("spike", "u1", "2026-08-18 06:00:00", "2026-08-18 06:00:00")]
    eps = [
        _ep("spike", "OTHER", "2026-08-18 06:00:00", "2026-08-18 06:10:00"),
        _ep("spike", "u1", "2026-08-17 01:00:00", "2026-08-17 01:10:00"),  # far away
    ]
    cards = score_labels(labels, eps)
    assert cards["spike"]["detected"] == 0 and cards["spike"]["misclassified"] == 0


def test_slack_window_tolerates_boundary_offsets():
    labels = [_label("seasonal_residual", "u1", "2026-08-18 06:00:00", "2026-08-18 08:00:00")]
    # episode starts 1.5h before the label window — within the 2h slack
    eps = [_ep("seasonal_residual", "u1", "2026-08-18 04:30:00", "2026-08-18 07:00:00")]
    cards = score_labels(labels, eps)
    assert cards["seasonal_residual"]["recall"] == 1.0


def test_co_firing_detectors_are_corroboration_not_error():
    """A +300 shift trips drift AND seasonal on the same sensor — when the
    expected detector fired, the extra class is evidence, not confusion."""
    labels = [_label("drift_vs_peers", "u1", "2026-08-18 02:00:00", "2026-08-18 09:00:00")]
    eps = [
        _ep("drift_vs_peers", "u1", "2026-08-18 03:00:00", "2026-08-18 09:00:00"),
        _ep("seasonal_residual", "u1", "2026-08-18 03:10:00", "2026-08-18 09:00:00"),
        _ep("spike", "u1", "2026-08-18 03:20:00", "2026-08-18 03:30:00"),
    ]
    cards = score_labels(labels, eps)
    c = cards["drift_vs_peers"]
    assert c["recall"] == 1.0 and c["precision"] == 1.0
    assert c.get("co_detections") == 2 and c["misclassified"] == 0
