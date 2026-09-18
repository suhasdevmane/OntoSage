# -*- coding: utf-8 -*-
"""A figure a lane COMPUTED is evidence, and until now nothing recorded it (CAVEAT-769).

**The defect this exists for.** Claim binding was switched on for one probe run on
2026-09-18 and reverted 25 minutes later. It had deleted *correct* figures: "How many CO2
sensors are there?" lost the number it was asked for, and a whole-building count answer
logged ``unbound=99/123``. Nothing was wrong with those answers. What was wrong is that the
lanes which produce them answer from a live ``COUNT`` over the building's own model and then
hand the response node **prose and nothing else** — so the only place the figure existed was
the sentence under test, and the binder refuses (rightly) to let a sentence vouch for itself.

To a binder, a lane that computes a figure and does not record it looks exactly like a lane
that invented one. The remedy is not to weaken the binder. It is to record the count, because
**a count IS evidence** — it is the result of a query, with the same standing as a row.

**Why a recorder and not a return value.** The figures are computed deep inside lanes whose
public functions already return the thing their callers want (a snapshot, a list of rows, a
rendered block). Threading an evidence payload back out would mean changing every signature
and every call site in agents this module does not own. A recorder lets the lane say *"this
number came from a query"* at the moment it knows it, and lets the response node collect it
at the moment it needs it, with nothing in between having to care.

**Turn scoping, and why it is keyed by trace id.** A process-wide list would let one
question's figures bind another question's claims. A :class:`~contextvars.ContextVar` is the
usual answer, but it is the wrong one here: a value ``set`` inside a child task never
propagates back to the parent, and LangGraph is free to run a node in a child task — the
figures would then be silently invisible to the response node, which is precisely the class
of defect this file exists to close. The request's ``trace_id`` is set once by the middleware
at the top of the request and *inherited* by every descendant context, so reading it from any
depth gives the same key. Entries are therefore filed under it and read back under it.

Two consequences, stated rather than discovered later:

* If a caller reuses one ``X-Trace-Id`` across concurrent requests, their figures mix. That
  can only make the binder **more** permissive — extra numbers it might bind against, never
  fewer — so the failure direction is the safe one.
* The store is bounded (:data:`_MAX_TRACES`) and evicts oldest-first, so a long-lived process
  cannot grow one turn at a time.

**What is deliberately NOT recorded.** No labels, no prose, no query text. A label is written
by the same renderer that writes the answer, so recording it would smuggle the answer's own
words into the evidence the answer is judged against — the self-vouching hole ``_walk``
already closes for ``response``/``narration`` keys. Only field names that come from the DATA
(a Brick class local name, a snapshot field) and the numbers themselves.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

__all__ = [
    "BUS_KEY",
    "as_payload",
    "record",
    "recorded",
    "reset",
]

#: The bus key the response node's binder reads this back under. Named here so the producer
#: and the consumer cannot drift: ``claim_binder._EVIDENCE_KEYS`` imports it.
BUS_KEY = "computed_figures"

#: How many turns' figures are held at once. Eviction is oldest-first.
_MAX_TRACES = 64

#: How many figures one source may record in one turn. A census is capped at 25 classes and a
#: snapshot at a few dozen fields; a source trying to file thousands is a bug, and truncating
#: is better than filling the binder's index with noise that could bind a wrong figure.
_MAX_FIGURES_PER_SOURCE = 200

#: trace id -> {source -> {field -> number}}
_STORE: "OrderedDict[str, Dict[str, Dict[str, float]]]" = OrderedDict()


def _trace() -> str:
    """The current request's trace id, or a stable local key when there is no request.

    Never raises: offline callers (tests, the replay measurement) have no middleware, and a
    recorder that blew up outside a request would make the lanes it is wired into fragile.
    """
    try:
        from orchestrator.services.logging_context import get_trace_id

        return str(get_trace_id() or "") or "_no_trace"
    except Exception:  # pragma: no cover - import guard only
        return "_no_trace"


def _numeric(value: Any) -> Optional[float]:
    """The value as a plain float, or None when it is not a quantity.

    ``bool`` is excluded on purpose: ``True`` is not the figure 1, and letting it in would
    put a 1 into the evidence index for every boolean flag a lane happens to compute.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    return None


def _field_name(name: Any) -> str:
    """A field name safe to use as a key, keeping the word shape the index reads."""
    return " ".join(str(name or "").split()).replace(".", "_")[:80]


def record(source: str, figures: Mapping[str, Any] | Iterable[Tuple[str, Any]]) -> None:
    """File the figures ``source`` just computed for this turn.

    ``source`` names the computation ("building_metrics", "class_census"), ``figures`` maps a
    field name to a number. Non-numeric values are dropped silently — the caller is usually
    handing over a whole result and should not have to filter it.

    Recording the same field twice overwrites, so a lane may record on every call (including
    the cached path) without the index growing or disagreeing with itself.
    """
    try:
        items = figures.items() if isinstance(figures, Mapping) else figures
        clean: Dict[str, float] = {}
        for name, value in items:
            f = _numeric(value)
            if f is None:
                continue
            clean[_field_name(name)] = f
            if len(clean) >= _MAX_FIGURES_PER_SOURCE:
                break
        if not clean:
            return
        key = _trace()
        bucket = _STORE.get(key)
        if bucket is None:
            bucket = {}
            _STORE[key] = bucket
            while len(_STORE) > _MAX_TRACES:
                _STORE.popitem(last=False)
        _STORE.move_to_end(key)
        bucket.setdefault(str(source or "computed"), {}).update(clean)
    except Exception as exc:  # a recorder must never be able to fail a lane
        logger.debug(f"[computed] record({source!r}) skipped: {type(exc).__name__}: {exc}")


def recorded(trace: Optional[str] = None) -> Dict[str, Dict[str, float]]:
    """Everything recorded for this turn, as ``{source: {field: number}}``."""
    return {s: dict(f) for s, f in (_STORE.get(trace or _trace()) or {}).items()}


def reset(trace: Optional[str] = None) -> None:
    """Drop this turn's figures. Used by tests and by anything replaying turns in-process."""
    _STORE.pop(trace or _trace(), None)


def as_payload(trace: Optional[str] = None, *, consume: bool = False) -> Optional[Dict[str, Any]]:
    """The bus-shaped record, or None when this turn computed nothing.

    One key only. Every extra key would be one more set of digits in the evidence index, and
    a figure that binds against the index's own bookkeeping is not evidenced, it is
    coincidence.

    ``consume=True`` hands the figures over and drops them, which is what the binder does:
    the figures belong to the turn whose answer is being judged, and that read happens once,
    at the end of it. Every HTTP request already has its own trace id (``TracingMiddleware``
    sets one per request), so this is belt-and-braces rather than the isolation mechanism --
    but a path that runs OUTSIDE a request has no middleware, and this bounds what such a
    path can leak into the next turn to nothing.
    """
    sources = recorded(trace)
    if not sources:
        return None
    if consume:
        reset(trace)
    return {"sources": sources}
