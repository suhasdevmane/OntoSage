# -*- coding: utf-8 -*-
"""reader_text.py -- what a reader is told when the language model, not the building, failed.

An exception's own text is never a reply: "I found relevant ontology data but had trouble
interpreting it: ReadTimeout:" reached a reader on 2026-10-08 (development sample S045), naming a
transport error and saying nothing they could act on. When the model is known to be down
(``circuit_breaker.model_is_unavailable``, which the hosted gateway's refusal now sets -- CAVEAT-1459)
the reader is also told that, because only that failure is worth retrying.

The wording deliberately avoids the five fallback sentences the compound evaluation matches as
provider failures (tasks/V2_COMPOUND_PLAN.md section 5): those are pre-registered against v1's
code, and a new path must not join that list after the fact.
"""

from __future__ import annotations

#: Added after ``lead`` when the model is known to be down.
MODEL_DOWN = (
    " The language model is not answering at the moment; this is not a gap in the building's "
    "records, so the same question should work once it is back."
)


def model_failure_sentence(lead: str) -> str:
    """``lead``, and the reason when the model is known to be the problem. Never raises."""
    try:
        from orchestrator.services.circuit_breaker import model_is_unavailable

        down = model_is_unavailable()
    except Exception:  # pragma: no cover - explaining a failure must not fail
        down = False
    return lead + (MODEL_DOWN if down else "")


__all__ = ["MODEL_DOWN", "model_failure_sentence"]
