# -*- coding: utf-8 -*-
"""The generator checks its own authored context against the live building (2026-08-27).

Authoring and verifying had two owners: `generate_building_context.py` wrote the
amenities and knowledge topics, and whether any of them could actually be ASKED was
established by me typing questions by hand. That is the shape of this project's
recurring defect -- a capability that is present, correct, tested, and that nothing
ever invokes (lessons.md #87, six instances).

So the generator probes what it authored. It is the only thing that knows which lay
terms it minted, which makes it the right thing to ask them.

What is pinned here is everything that can be checked without a live stack: the
questions come from the authored lay terms, and a polite refusal is not counted as an
answer. The probe's value depends entirely on that second point -- "I don't have
information about that" is a well-formed HTTP 200 with prose in it, and a probe that
scores it as success reports a building answering nothing as a building answering
everything.
"""

import importlib.util
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]


def _mod():
    path = _REPO / "scripts" / "generate_building_context.py"
    spec = importlib.util.spec_from_file_location("_genctx", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── the refusal vocabulary ───────────────────────────────────────────────────
@pytest.mark.parametrize(
    "reply",
    [
        "I don't have information about that for this building.",
        "I do not have that information.",
        "No information is available on recycling here.",
        "I couldn't find anything about deliveries.",
        "I processed your request, but couldn't generate a response.",
        "There is no data for that.",
    ],
)
def test_a_refusal_is_not_counted_as_an_answer(reply):
    """Each of these is an HTTP 200 with fluent prose in it. Counting them would make
    a building that answers nothing score the same as one that answers everything."""
    low = reply.lower()
    assert any(m in low for m in _mod()._REFUSALS), reply


@pytest.mark.parametrize(
    "reply",
    [
        "Recycling. Mixed recycling and landfill bins sit on every floor by the stair core.",
        "Drinkability: safe to drink - published by Cardiff University Estates on 2020-01-01.",
        "The building is open Monday-Friday 07:00-21:00.",
    ],
)
def test_a_real_answer_is_not_read_as_a_refusal(reply):
    low = reply.lower()
    assert not any(m in low for m in _mod()._REFUSALS), reply


# ── the questions come from what was authored ────────────────────────────────
def _questions_from(text: str):
    """The extraction the probe performs, kept in step with it by the test below."""
    out = []
    for m in re.finditer(r'ontosage:layTerms\s+"([^"]+)"', text):
        first = m.group(1).split(",")[0].strip()
        if first:
            out.append(first)
    return out


def test_one_question_per_authored_topic_using_its_first_lay_term():
    """The first term is the phrasing a person types; the rest are synonyms of it, so
    asking all of them would multiply the probe's cost without widening its coverage."""
    ttl = (
        '  ontosage:layTerms "recycling, bins, waste, rubbish" ;\n'
        '  ontosage:layTerms "book a room, reserve, meeting room booking" ;\n'
    )
    assert _questions_from(ttl) == ["recycling", "book a room"]


def test_the_probe_uses_the_same_extraction_this_test_pins():
    """Two copies of one regex is how they drift. If the probe's changes, this fails."""
    import inspect

    src = inspect.getsource(_mod().probe)
    assert r'ontosage:layTerms\s+"([^"]+)"' in src
    assert 'split(",")[0]' in src


# ── and it authenticates, because /chat is gated ─────────────────────────────
def test_the_probe_authenticates_before_asking():
    """An unauthenticated probe gets 401 for every question, which is indistinguishable
    from a building that answers nothing. The first run of this probe did exactly that
    and reported 0/5.
    """
    import inspect

    src = inspect.getsource(_mod().probe)
    assert "_login" in src, "the probe must obtain a session token"
    assert "Authorization" in src


def test_the_probe_reuses_the_canonical_login_rather_than_copying_it():
    """Three scripts already carry their own _login. A fourth copy is a fourth thing to
    fix when session auth changes."""
    import inspect

    src = inspect.getsource(_mod().probe)
    assert "capture_golden_baseline.py" in src
    assert "def _login" not in src, "the probe defines its own login instead of reusing one"


# ── a probe that cannot fail is not a check ──────────────────────────────────
def test_a_partial_result_is_reported_as_a_failure_exit_code():
    """Returning 0 when some topics refuse would make the probe unusable in CI and,
    worse, readable as a pass by whoever runs it by hand."""
    import inspect

    src = inspect.getsource(_mod().probe)
    assert "return 0 if answered == len(questions) else 2" in src
