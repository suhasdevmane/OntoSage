# -*- coding: utf-8 -*-
"""
subscriptions.py — "alert me if…" binds to persisted anomaly episodes (V5-T23).

The ECA rules engine watches THRESHOLDS ("CO2 above 1200 for 15 min"). Half of
what people actually ask for is a *pattern*, not a threshold: "tell me if a
sensor goes dead", "let me know if any room drifts from its neighbours",
"alert me about anything unusual on floor 2". Those are exactly the episodes
the T19 scanner already persists — this module turns a standing request into a
subscription over that stream and dispatches when a NEW episode matches.

Design:
- A subscription is (user, detectors?, modality?, scope?, min_severity) — all
  optional filters, so "anything unusual" is a valid subscription.
- Matching is done against episodes the scanner wrote, so an alert can always
  point at a durable episode id (no re-derivation, no drift).
- Delivery is de-duplicated by episode id per subscriber: an episode that
  stays open across sweeps notifies ONCE, not every hour.
- Redis-backed seen-set when available; in-memory fallback keeps tests and
  single-process runs honest.

Building-agnostic: nothing here names a building, detector set comes from the
episode stream itself.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2}

#: phrase → detector filter (generic English; the detector names come from T18)
_DETECTOR_PHRASES = (
    (
        re.compile(r"\bdead\b|\bstops? (?:reporting|sending)|\boffline\b|\bnot reporting\b", re.I),
        ("dropout", "stuck"),
    ),
    (re.compile(r"\bstuck\b|\bfrozen\b|\bflat ?line", re.I), ("stuck",)),
    (re.compile(r"\bdrift", re.I), ("drift_vs_peers",)),
    (re.compile(r"\bspike|\bsudden (?:jump|change)", re.I), ("spike",)),
    (
        re.compile(r"\bout of hours\b|\bafter hours\b|\bovernight\b|\bweekend\b", re.I),
        ("schedule_violation",),
    ),
    (re.compile(r"\bunusual\b|\bstrange\b|\banomal", re.I), ()),  # any detector
)

#: phrase → modality filter (lay terms, same vocabulary the concept resolver uses)
_MODALITY_PHRASES = (
    (re.compile(r"\btemperature|\bcold\b|\bhot\b", re.I), "temperature"),
    (re.compile(r"\bco2\b|\bstuffy\b|\bair quality\b", re.I), "co2"),
    (re.compile(r"\bhumid", re.I), "humidity"),
    (re.compile(r"\bnoise|\bloud", re.I), "noise"),
    (re.compile(r"\boccupancy|\bbusy\b|\bpeople\b", re.I), "occupancy"),
    (re.compile(r"\bpm2\.?5\b|\bparticul", re.I), "pm25"),
)


@dataclass
class AnomalySubscription:
    user_id: str
    raw_request: str
    detectors: tuple = ()  # empty = any detector
    modality: Optional[str] = None  # None = any modality
    scope: Optional[str] = None  # room/floor label fragment; None = whole building
    min_severity: str = "low"
    channel: str = "log"
    id: str = ""

    def describe(self) -> str:
        bits = []
        bits.append(", ".join(self.detectors) if self.detectors else "any anomaly")
        if self.modality:
            bits.append(f"on {self.modality}")
        if self.scope:
            bits.append(f"in {self.scope}")
        if self.min_severity != "low":
            bits.append(f"at {self.min_severity}+ severity")
        return " ".join(bits)


def parse_subscription(request: str, user_id: str) -> Optional[AnomalySubscription]:
    """Build a subscription from a standing-alert phrasing, or None.

    Only ANOMALY-shaped standing requests are claimed here; threshold requests
    ("alert me if CO2 goes above 1200") stay with the ECA rules engine, which
    can actually evaluate a numeric condition.
    """
    q = request or ""
    if not re.search(r"\b(alert|notify|tell|warn|let me know|email me)\b", q, re.I):
        return None
    if re.search(r"\b(above|below|over|under|exceeds?|drops? below)\b\s*\d", q, re.I):
        return None  # a numeric threshold — the ECA engine owns it
    detectors: tuple = ()
    matched = False
    for pat, dets in _DETECTOR_PHRASES:
        if pat.search(q):
            detectors, matched = dets, True
            break
    if not matched:
        return None
    modality = next((m for pat, m in _MODALITY_PHRASES if pat.search(q)), None)
    scope = None
    m = re.search(r"\b(?:in|on|for)\s+((?:room\s*)?[A-Za-z]{0,4}\d[\w.]*|floor\s*\w+)\b", q, re.I)
    if m:
        scope = m.group(1).strip()
    severity = "high" if re.search(r"\b(?:serious|severe|critical|important)\b", q, re.I) else "low"
    return AnomalySubscription(
        user_id=user_id,
        raw_request=q.strip(),
        detectors=detectors,
        modality=modality,
        scope=scope,
        min_severity=severity,
    )


def episode_matches(sub: AnomalySubscription, episode: Dict[str, Any]) -> bool:
    """Does this persisted episode satisfy the subscription's filters?"""
    detector = str(episode.get("event_type", "")).split(":", 1)[-1]
    if sub.detectors and detector not in sub.detectors:
        return False
    attrs = episode.get("attrs")
    if isinstance(attrs, str):
        try:
            attrs = json.loads(attrs)
        except ValueError:
            attrs = {}
    attrs = attrs or {}
    if sub.modality and str(attrs.get("modality", "")) != sub.modality:
        return False
    if sub.scope:
        room = str(episode.get("room") or attrs.get("room") or "")
        probe = re.sub(r"[^a-z0-9]", "", sub.scope.lower())
        if probe and probe not in re.sub(r"[^a-z0-9]", "", room.lower()):
            return False
    sev = str(attrs.get("severity", "low")).lower()
    if _SEVERITY_ORDER.get(sev, 0) < _SEVERITY_ORDER.get(sub.min_severity, 0):
        return False
    return True


def render_alert(sub: AnomalySubscription, episode: Dict[str, Any]) -> str:
    """Alert text that points at the durable episode (never a re-derivation)."""
    detector = str(episode.get("event_type", "")).split(":", 1)[-1]
    attrs = episode.get("attrs")
    if isinstance(attrs, str):
        try:
            attrs = json.loads(attrs)
        except ValueError:
            attrs = {}
    attrs = attrs or {}
    where = episode.get("room") or attrs.get("room") or "an unresolved point"
    modality = attrs.get("modality") or "?"
    sev = attrs.get("severity", "low")
    return (
        f"**Anomaly alert — {detector}** ({sev}) on {modality} in {where}, "
        f"starting {episode.get('start_dt')}. You asked: \"{sub.raw_request}\". "
        f'Ask "why was {where} unusual?" for the evidence behind it. '
        f"(episode `{str(episode.get('event_id', ''))[:8]}`)"
    )


class SubscriptionDispatcher:
    """Matches new episodes to subscriptions; delivers each episode ONCE."""

    def __init__(self, notifier=None, seen_store: Optional[set] = None) -> None:
        self._notifier = notifier
        self._seen = seen_store if seen_store is not None else set()

    async def dispatch(
        self, subs: Iterable[AnomalySubscription], episodes: Iterable[Dict[str, Any]]
    ) -> List[Dict[str, str]]:
        """Returns the delivered alerts (subscription id + episode + text)."""
        delivered: List[Dict[str, str]] = []
        for sub in subs:
            for ep in episodes:
                key = f"{sub.user_id}:{ep.get('event_id')}"
                if key in self._seen:
                    continue
                if not episode_matches(sub, ep):
                    continue
                self._seen.add(key)
                text = render_alert(sub, ep)
                delivered.append(
                    {
                        "user_id": sub.user_id,
                        "episode_id": str(ep.get("event_id", "")),
                        "detector": str(ep.get("event_type", "")).split(":", 1)[-1],
                        "text": text,
                    }
                )
                if self._notifier is not None:
                    try:
                        await self._notifier(sub, ep, text)
                    except Exception as exc:
                        logger.warning(f"[anomaly-subs] delivery failed: {exc}")
        if delivered:
            logger.info(f"[anomaly-subs] delivered {len(delivered)} alert(s)")
        return delivered
