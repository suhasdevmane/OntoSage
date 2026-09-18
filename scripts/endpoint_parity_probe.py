#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ask the same questions through BOTH chat endpoints and report where they DIVERGE.

WHY THIS EXISTS
---------------
`scripts/regression_probe.py` posts to ``/chat``. The demo runs through Open WebUI,
which posts to ``/v1/chat/completions``. The two endpoints do not share their wiring,
and the difference is not cosmetic — read `orchestrator/main.py`:

======================  ===================================  ==================================
what                    ``/chat``                            ``/v1/chat/completions``
======================  ===================================  ==================================
auth                    session token, the caller's OWN role shared pipeline key; role pinned
                                                             readonly unless the proxy forwards
                                                             an identity (TRUST_FORWARDED_USER)
conversation id         ``conv_<session_id>:<user>``         ``owui_<X-Chat-Id>:<user>``
prior turns             server-side Redis state only         the client's ``messages`` array,
                                                             PLUS server-side rehydration
carry-forward from
Postgres turn_memory    never loaded                         loaded every turn
``prune_inherited``
(the V12-11 context
switch guard)           runs every turn since BUG-655        runs every turn
older-turn summaries    never injected                       injected as a system message
``turn_memory.save_turn``  never called                      called on both stream and
                                                             non-stream paths
response body           intent, sources, evidence_record,    message text, plus
                        plan_trace, llm_degraded             ontosage_evidence_record,
                                                             ontosage_llm_degraded and (since
                                                             TODO-657) ontosage_intent
======================  ===================================  ==================================

So "60/60 on the probe" is a statement about an endpoint the demo does not use, and it
is no statement at all about multi-turn behaviour: the probe asks every question in a fresh
session, so the memory guard (wired on the probe's endpoint only since BUG-655) is never
exercised by it, and neither is BUG-524 — a co-reference rewrite that swaps the room the
user named, which the existence gate cannot catch because the rewrite has already replaced
the query everywhere downstream.

WHAT IT MEASURES
----------------
Three things, and it keeps them apart.

1. **Single-turn parity.** The SAME cases the regression probe runs — loaded from
   ``scripts/regression_cases.json``, with the regression probe's own marker semantics
   imported, not reimplemented — asked once through each endpoint. A case that passes on
   both is uninteresting. A case that passes on one and fails on the other is the finding.

2. **Multi-turn behaviour**, which the regression probe cannot see at all because its
   endpoint never persists a turn. Short conversations whose LATER turns depend on the
   earlier ones, including a negative case that changes the referent mid-conversation and
   checks the old one is not carried forward.

3. **Streamed versus unstreamed on /v1** (``--stream``, CAVEAT-656). Open WebUI streams by
   default, and the streamed branch of ``/v1/chat/completions`` is separate code: it rebuilds
   the final state from the last streamed step instead of taking the workflow's return value.
   Each case is asked through /v1 twice — ``stream: false`` and ``stream: true`` — and the
   answer reassembled from the chunks is scored and compared against the unstreamed one. The
   streaming client is ``scripts/ask_questions.py``'s, reused rather than written again.

THE RESPONSE CACHE IS FLUSHED BEFORE EVERY ASK
----------------------------------------------
Every mode asks the SAME question twice. The response cache is keyed on the question, the
building, the user and the role — so without a flush the second ask is served the first
ask's answer from Redis in well under a second, the second path never runs, and the two
"agree" by construction (BUG-662's shape). ``--no-flush`` exists for measuring the cache on
purpose, and the report says when it was used or when a flush failed.

Nothing here is building-specific. The rooms and floors the conversations name are
resolved from the live graph at run time (plain Brick, no building literal anywhere in
this file), so the same conversations run unchanged against another building.

    python scripts/endpoint_parity_probe.py --sample 6        # a small live window
    python scripts/endpoint_parity_probe.py --multiturn-only  # just the conversations
    python scripts/endpoint_parity_probe.py --stream --sample 6  # streamed vs unstreamed /v1
    python scripts/endpoint_parity_probe.py --dry-run         # resolve + print, ask nothing
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

CASES_PATH = REPO / "scripts" / "regression_cases.json"


def _load(name: str, rel: str):
    """Import a sibling script by path, the way the regression probe imports its own."""
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── verdicts ────────────────────────────────────────────────────────────────────
#
# Named rather than boolean, because "they disagree" is four different findings and a
# report that flattens them is unreadable. BOTH_FAIL usually means a bad marker or a
# genuinely broken case and says nothing about the endpoints; the two one-sided verdicts
# are the only ones that are about the WIRING.
BOTH_PASS = "BOTH_PASS"
BOTH_FAIL = "BOTH_FAIL"
CHAT_ONLY = "CHAT_ONLY"
V1_ONLY = "V1_ONLY"

#: The verdicts that mean the two endpoints behaved differently on the same question.
DIVERGENT = (CHAT_ONLY, V1_ONLY)


def verdict(chat_ok: bool, v1_ok: bool) -> str:
    """Which of the four outcomes this case landed in."""
    if chat_ok and v1_ok:
        return BOTH_PASS
    if not chat_ok and not v1_ok:
        return BOTH_FAIL
    return CHAT_ONLY if chat_ok else V1_ONLY


# ── co-reference verdicts (the BUG-524 hunt) ────────────────────────────────────
CO_CORRECT = "CORRECT"
CO_CARRIED = "CARRIED_OLD_REFERENT"
CO_NEITHER = "NEITHER_NAMED"
CO_BOTH = "BOTH_NAMED"


def coreference_verdict(answer: str, new_token: str, old_token: str, matches) -> str:
    """Did the answer follow the referent the user just changed to?

    Deliberately NOT "the old name must be absent". A good answer to "what about room B?"
    may legitimately say "room B is warmer than room A" — forbidding the old name outright
    would fail correct answers, and a check that cries wolf is one nobody reads.

    The unambiguous defect is the one BUG-524 describes: the new referent is ABSENT and the
    old one is present, so the user asked about B and was answered about A. That is the only
    combination reported as carried. BOTH_NAMED and NEITHER_NAMED are reported as what they
    are and left for a human, because neither is decidable from the text alone.
    """
    has_new = matches(answer, new_token)
    has_old = matches(answer, old_token)
    if has_new and has_old:
        return CO_BOTH
    if has_new:
        return CO_CORRECT
    if has_old:
        return CO_CARRIED
    return CO_NEITHER


# ── marker evaluation ───────────────────────────────────────────────────────────
#
# The MATCHING semantics are imported from the regression probe (`_matches`) so a marker
# means exactly the same thing here as there — number words, thousands separators, en
# dashes and all. The evaluation LOOP is written out again because the probe's lives inline
# in its `main()` and cannot be imported without running the probe. That is a genuine reuse
# limit, not a fork: no case text and no marker rule is duplicated.
def evaluate_case(case: Dict[str, Any], answer: str, intent: str, expected_live, matches) -> Tuple:
    """(ok, why) for one case against one endpoint's answer, by the probe's own rules."""
    if not answer.strip():
        return False, "empty answer"
    missing = [
        m for m in list(case.get("expect", [])) + list(expected_live) if not matches(answer, m)
    ]
    present = [f for f in case.get("forbid", []) if matches(answer, f)]
    alternatives = list(case.get("expect_any", []) or [])
    any_missing = bool(alternatives) and not any(matches(answer, m) for m in alternatives)

    want_intent = case.get("expect_intent")
    deny_intent = case.get("forbid_intent")
    wrong_lane = ""
    # An intent expectation is only decidable where the endpoint reports one. /v1 does not,
    # so it is SKIPPED there and said so — never silently passed, which would let the demo
    # endpoint look better than the probe endpoint purely by telling us less.
    if intent is not None:
        if want_intent and intent != want_intent:
            wrong_lane = f"intent {intent!r}, expected {want_intent!r}"
        elif deny_intent and intent == deny_intent:
            wrong_lane = f"intent {intent!r} is the lane this case exists to avoid"

    if missing:
        return False, f"missing {missing}"
    if any_missing:
        return False, f"none of {alternatives}"
    if present:
        return False, f"forbidden present {present}"
    if wrong_lane:
        return False, wrong_lane
    return True, ""


def case_checks_intent(case: Dict[str, Any]) -> bool:
    """Whether this case's verdict depends on a lane the /v1 body does not report."""
    return bool(case.get("expect_intent") or case.get("forbid_intent"))


# ── answer comparison, beyond pass/fail ─────────────────────────────────────────
_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w])")


def numbers_in(text: str) -> set:
    """Every figure the answer states, normalised.

    Two answers can both satisfy a marker list and still disagree about a number the marker
    list does not name. That disagreement is a real divergence and no pass/fail column
    would show it, so it is measured separately.
    """
    out = set()
    for raw in _NUM.findall(text or ""):
        token = raw.replace(",", "")
        try:
            value = float(token)
        except ValueError:
            continue
        out.add(str(int(value)) if value == int(value) else str(value))
    return out


def numeric_divergence(a: str, b: str) -> Dict[str, List[str]]:
    """Figures stated by one answer and not the other, both ways."""
    na, nb = numbers_in(a), numbers_in(b)
    return {
        "shared": sorted(na & nb),
        "only_chat": sorted(na - nb),
        "only_v1": sorted(nb - na),
    }


# ── building vocabulary, resolved from the graph ────────────────────────────────
#
# Not a constant. A room id in this file would make the conversations bldg1-shaped, and the
# whole point of a portability rule is that it holds in the harness too.
_TRAILING_QUALIFIER = re.compile(r"\s*[—–\-(].*$")


def marker_token(label: str) -> str:
    """The shortest piece of a label that still identifies the place, lowercased.

    A Brick label arrives as "Room 2.01 — Research Laboratory" or "Floor 3 (Third Floor)".
    The qualifier after the dash or bracket is prose and an answer need not repeat it, so
    it is dropped. What remains is "Room 2.01" or "Floor 3".

    Then: the last token if it is distinctive ("2.01"), but the WHOLE phrase when the last
    token is a bare small number ("floor 3" rather than "3"). "3" alone would match the 3
    in "3 sensors" and turn a correct answer into a reported defect.
    """
    head = _TRAILING_QUALIFIER.sub("", (label or "").strip()).strip()
    if not head:
        return ""
    last = head.split()[-1]
    if last.isdigit() and len(last) <= 2:
        return head.lower()
    return last.lower()


def distinguishable(a: str, b: str) -> bool:
    """Whether two markers can tell two answers apart.

    "0.1" inside "0.10" would make a carried referent read as a correct one, so a pair that
    contains the other is refused rather than silently weakening every check built on it.
    """
    a, b = (a or "").lower(), (b or "").lower()
    return bool(a) and bool(b) and a != b and a not in b and b not in a


def pick_distinguishable_pair(labels: Sequence[str]) -> Optional[Tuple[str, str]]:
    """The first two labels whose markers cannot be confused for one another."""
    for i, first in enumerate(labels):
        for second in labels[i + 1 :]:
            if distinguishable(marker_token(first), marker_token(second)):
                return first, second
    return None


#: Rooms that hold a sensor whose readings are actually fetchable, one per floor, so a
#: conversation about them has something to answer with. Plain Brick + the reference
#: vocabulary — nothing in it names a building.
_ROOMS_QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
SELECT ?floorLabel (SAMPLE(?roomLabel) AS ?room) WHERE {
  ?floor a brick:Floor ; rdfs:label ?floorLabel ; brick:hasPart ?r .
  ?r rdfs:label ?roomLabel .
  ?s a brick:Temperature_Sensor ; brick:hasLocation ?r ;
     ref:hasExternalReference ?ref .
  ?ref ref:hasTimeseriesId ?uuid .
} GROUP BY ?floorLabel ORDER BY ?floorLabel
"""


def _sparql_rows(query: str, base_url: str, repo: str) -> List[Dict[str, str]]:
    """Every binding of a SELECT, flattened to plain strings. [] on any failure."""
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/repositories/{repo}",
            data=query.encode("utf-8"),
            headers={
                "Content-Type": "application/sparql-query",
                "Accept": "application/sparql-results+json",
            },
            timeout=60,
        )
        if resp.status_code != 200:
            print(f"  [graph] HTTP {resp.status_code}")
            return []
        rows = resp.json().get("results", {}).get("bindings", [])
    except Exception as exc:
        print(f"  [graph] {type(exc).__name__}: {exc}")
        return []
    return [{k: str(v.get("value", "")) for k, v in row.items()} for row in rows]


def resolve_vocabulary(graphdb_url: str, repo: str) -> Optional[Dict[str, str]]:
    """Two rooms on two different floors, with the markers that tell them apart.

    Returns None when the graph cannot supply a distinguishable pair — in which case the
    conversations are SKIPPED and the report says so, rather than falling back to a literal
    and quietly measuring one building.
    """
    rows = _sparql_rows(_ROOMS_QUERY, graphdb_url, repo)
    if len(rows) < 2:
        return None
    floors = [r.get("floorLabel", "") for r in rows]
    by_floor = {r.get("floorLabel", ""): r.get("room", "") for r in rows}
    floor_pair = pick_distinguishable_pair(floors)
    if not floor_pair:
        return None
    # The rooms must also be distinguishable from each other, not merely on different
    # floors: two floors can label their rooms so that one id contains the other.
    room_pair = pick_distinguishable_pair([by_floor[floor_pair[0]], by_floor[floor_pair[1]]])
    if not room_pair:
        return None
    return {
        "floor_a": _TRAILING_QUALIFIER.sub("", floor_pair[0]).strip(),
        "floor_b": _TRAILING_QUALIFIER.sub("", floor_pair[1]).strip(),
        "floor_a_token": marker_token(floor_pair[0]),
        "floor_b_token": marker_token(floor_pair[1]),
        "room_a": _TRAILING_QUALIFIER.sub("", by_floor[floor_pair[0]]).strip(),
        "room_b": _TRAILING_QUALIFIER.sub("", by_floor[floor_pair[1]]).strip(),
        "room_a_token": marker_token(by_floor[floor_pair[0]]),
        "room_b_token": marker_token(by_floor[floor_pair[1]]),
    }


# ── the conversations ───────────────────────────────────────────────────────────
#
# Every place is a placeholder. A literal here would be a building literal in the one
# artifact whose job is to prove the demo endpoint behaves, and it would pass silently on
# bldg1 for as long as bldg1 stayed active.
#
# `coref` names the pair of markers a turn's referent check compares: the referent the user
# just named, and the one they named before. A turn without `coref` is scored on its
# markers alone.
CONVERSATIONS: List[Dict[str, Any]] = [
    {
        "id": "followup-floor",
        "why": (
            "The plainest follow-up there is. Turn 2 names a new floor and nothing else — "
            "no verb, no measurand — so it is answerable ONLY from turn 1."
        ),
        "turns": [
            {
                "question": "What is the average temperature on {floor_a}?",
                "expect_any": ["{floor_a_token}", "°c", "degrees"],
            },
            {
                "question": "And what about {floor_b}?",
                "coref": ["{floor_b_token}", "{floor_a_token}"],
            },
        ],
    },
    {
        "id": "followup-change",
        "why": (
            "Three turns, where turn 2 carries an artifact forward ('how has that changed') "
            "and turn 3 changes the subject back to a place. Carry-forward is loaded from "
            "Postgres turn_memory on /v1 and from nothing at all on /chat."
        ),
        "turns": [
            {
                "question": "What is the temperature in {room_a}?",
                "expect_any": ["{room_a_token}", "°c", "degrees"],
            },
            {"question": "How has that changed over the last week?"},
            {
                "question": "And in {room_b}?",
                "coref": ["{room_b_token}", "{room_a_token}"],
            },
        ],
    },
    {
        "id": "negative-room-switch",
        "why": (
            "THE NEGATIVE CASE — BUG-524. Turn 2 names a DIFFERENT room. If the co-reference "
            "rewrite carries the first room forward, the answer is about a room the user did "
            "not ask about, every figure in it real and attributed to the wrong place. The "
            "rewrite replaces the query everywhere downstream, so the referent-existence gate "
            "cannot catch it: both rooms exist. Only reading the answer can."
        ),
        "turns": [
            {
                "question": "What is the CO2 level in {room_a}?",
                "expect_any": ["{room_a_token}", "ppm", "co2", "carbon dioxide"],
            },
            {
                "question": "What about {room_b}?",
                "coref": ["{room_b_token}", "{room_a_token}"],
            },
        ],
    },
    {
        "id": "negative-room-switch-explicit",
        "why": (
            "The same switch said in full — a whole question naming the new room, not an "
            "elliptical fragment. A rewrite that swaps the referent HERE is the worse defect: "
            "the user left nothing to infer."
        ),
        "turns": [
            {
                "question": "How warm is {room_a} right now?",
                "expect_any": ["{room_a_token}", "°c", "degrees"],
            },
            {
                "question": "Now tell me the temperature in {room_b} instead.",
                "coref": ["{room_b_token}", "{room_a_token}"],
            },
        ],
    },
]


def render_conversations(templates: Sequence[Dict[str, Any]], vocab: Dict[str, str]) -> List[Dict]:
    """Substitute the resolved building vocabulary into the conversation templates.

    Raises KeyError on an unknown placeholder rather than leaving it in the question text:
    a question reading "what about {room_b}?" would be asked, answered, and scored, and the
    run would look like it had measured something.
    """

    def fill(text: str) -> str:
        return text.format(**vocab)

    out: List[Dict[str, Any]] = []
    for template in templates:
        turns = []
        for turn in template["turns"]:
            filled: Dict[str, Any] = {"question": fill(turn["question"])}
            if turn.get("expect_any"):
                filled["expect_any"] = [fill(m) for m in turn["expect_any"]]
            if turn.get("coref"):
                filled["coref"] = [fill(m) for m in turn["coref"]]
            turns.append(filled)
        out.append({"id": template["id"], "why": template["why"], "turns": turns})
    return out


def v1_messages(history: Sequence[Tuple[str, str]], question: str) -> List[Dict[str, str]]:
    """The OpenAI-format messages array Open WebUI would send on this turn.

    `history` is the (user, assistant) pairs already exchanged. Sending them is the whole
    difference: /v1 reconstructs prior turns from this array, while /chat gets its history
    from server-side Redis alone. A harness that sent only the current question to /v1
    would be measuring a client nobody uses.
    """
    messages: List[Dict[str, str]] = []
    for user_text, assistant_text in history:
        messages.append({"role": "user", "content": user_text})
        messages.append({"role": "assistant", "content": assistant_text})
    messages.append({"role": "user", "content": question})
    return messages


def check_turn(turn: Dict[str, Any], answer: str, matches) -> Tuple[bool, str, str]:
    """(ok, why, coref_verdict) for one conversational turn."""
    if not (answer or "").strip():
        return False, "empty answer", ""
    alternatives = list(turn.get("expect_any", []) or [])
    if alternatives and not any(matches(answer, m) for m in alternatives):
        return False, f"none of {alternatives}", ""
    coref = turn.get("coref")
    if not coref:
        return True, "", ""
    outcome = coreference_verdict(answer, coref[0], coref[1], matches)
    if outcome == CO_CARRIED:
        return False, f"answered about {coref[1]!r}, not {coref[0]!r}", outcome
    if outcome == CO_NEITHER:
        return False, f"named neither {coref[0]!r} nor {coref[1]!r}", outcome
    return True, "", outcome


# ── transport ───────────────────────────────────────────────────────────────────
def v1_intent(payload: Dict[str, Any]) -> Optional[str]:
    """The lane a /v1 body or final stream chunk reports, or None when it reports none.

    None and "" are both "no lane": an empty string must not be compared against an
    `expect_intent` and reported as a wrong lane, because nothing was actually reported.
    """
    value = (payload or {}).get("ontosage_intent")
    return str(value) if value else None


def ask_chat(question: str, base_url: str, token: str, session_id: str, timeout: int) -> Dict:
    """One turn through /chat. A stable session_id is what makes it a CONVERSATION.

    The regression probe generates a fresh session per question, which is right for a
    single-turn corpus and is exactly why it can say nothing about multi-turn behaviour.
    """
    t0 = time.time()
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/chat",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            json={"message": question, "session_id": session_id},
            timeout=timeout,
        )
        elapsed = round(time.time() - t0, 1)
        if resp.status_code != 200:
            return {
                "answer": "",
                "intent": "",
                "seconds": elapsed,
                "status": f"HTTP {resp.status_code}",
            }
        payload = resp.json()
        data = payload.get("data") or payload
        degraded = data.get("llm_degraded")
        if degraded:
            causes = ",".join((degraded or {}).get("causes") or ["unknown"])
            return {
                "answer": str(data.get("response") or ""),
                "intent": str(data.get("intent") or ""),
                "seconds": elapsed,
                "status": f"LLM-DEGRADED:{causes}",
            }
        return {
            "answer": str(data.get("response") or ""),
            "intent": str(data.get("intent") or ""),
            "seconds": elapsed,
            "status": "OK",
        }
    except requests.Timeout:
        return {
            "answer": "",
            "intent": "",
            "seconds": round(time.time() - t0, 1),
            "status": "TIMEOUT",
        }
    except Exception as exc:
        return {
            "answer": "",
            "intent": "",
            "seconds": round(time.time() - t0, 1),
            "status": f"ERROR:{type(exc).__name__}",
        }


def ask_v1(
    messages: Sequence[Dict[str, str]],
    base_url: str,
    api_key: str,
    chat_id: str,
    forwarded_user: str,
    forwarded_header: str,
    timeout: int,
) -> Dict[str, Any]:
    """One turn through /v1/chat/completions, shaped the way Open WebUI shapes it.

    The X-Chat-Id header is what pins the conversation id server-side; without it the
    endpoint falls back to hashing the first message, and a run would measure the fallback
    rather than the demo path. The forwarded-user header carries the signed-in identity, so
    the turn runs at that account's real role instead of least-privilege readonly.

    The lane comes from `ontosage_intent` (TODO-657). A server older than that field — or a
    turn that never classified — yields None, and every lane assertion is then SKIPPED
    rather than assumed — see `evaluate_case`.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "X-Chat-Id": chat_id,
    }
    if forwarded_user:
        headers[forwarded_header] = forwarded_user
    t0 = time.time()
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/v1/chat/completions",
            headers=headers,
            json={"model": "ontosage", "stream": False, "messages": list(messages)},
            timeout=timeout,
        )
        elapsed = round(time.time() - t0, 1)
        if resp.status_code != 200:
            return {
                "answer": "",
                "intent": None,
                "seconds": elapsed,
                "status": f"HTTP {resp.status_code}",
            }
        payload = resp.json()
        answer = str(
            ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        )
        intent = v1_intent(payload)
        degraded = payload.get("ontosage_llm_degraded")
        if degraded:
            causes = ",".join((degraded or {}).get("causes") or ["unknown"])
            return {
                "answer": answer,
                "intent": intent,
                "seconds": elapsed,
                "status": f"LLM-DEGRADED:{causes}",
            }
        return {"answer": answer, "intent": intent, "seconds": elapsed, "status": "OK"}
    except requests.Timeout:
        return {
            "answer": "",
            "intent": None,
            "seconds": round(time.time() - t0, 1),
            "status": "TIMEOUT",
        }
    except Exception as exc:
        return {
            "answer": "",
            "intent": None,
            "seconds": round(time.time() - t0, 1),
            "status": f"ERROR:{type(exc).__name__}",
        }


# ── streamed versus unstreamed (CAVEAT-656) ─────────────────────────────────────
#
# The streaming CLIENT is not written here. `scripts/ask_questions.py` already has one — the
# one used for every manual rehearsal of the demo path — and a second copy would be a second
# opinion about how Open WebUI's stream reassembles, which is exactly the kind of drift this
# project keeps finding between two copies of one step.

#: The only forwarded-identity header `ask_questions._ask_v1_stream` sends. Stream mode
#: refuses to run with any other, or the streamed turn would run at a different role from
#: the unstreamed one and every divergence would be about identity, not the stream.
STREAM_CLIENT_HEADER = "X-OpenWebUI-User-Email"

STREAM_BOTH_PASS = BOTH_PASS
STREAM_BOTH_FAIL = BOTH_FAIL
UNSTREAMED_ONLY = "UNSTREAMED_ONLY"
STREAMED_ONLY = "STREAMED_ONLY"
STREAM_DIVERGENT = (UNSTREAMED_ONLY, STREAMED_ONLY)


def stream_verdict(unstreamed_ok: bool, streamed_ok: bool) -> str:
    """Which of the four outcomes a streamed/unstreamed pair landed in."""
    if unstreamed_ok and streamed_ok:
        return STREAM_BOTH_PASS
    if not unstreamed_ok and not streamed_ok:
        return STREAM_BOTH_FAIL
    return UNSTREAMED_ONLY if unstreamed_ok else STREAMED_ONLY


def _stream_client():
    """`ask_questions._ask_v1_stream`, imported by path like every other sibling here."""
    return _load("_ask_questions", "scripts/ask_questions.py")._ask_v1_stream


def ask_v1_stream(
    messages: Sequence[Dict[str, str]],
    base_url: str,
    api_key: str,
    chat_id: str,
    forwarded_user: str,
    timeout: int,
    client=None,
) -> Dict[str, Any]:
    """One /v1 turn with ``stream: true``, through ask_questions' client, in ask_v1's shape.

    `intent` is None: the client reassembles `delta.content` only, and does not read the
    `ontosage_intent` the server now puts on the final chunk — so lane assertions are skipped
    for the streamed side and the comparison is made on the text. `status` keeps the client's
    own values ("OK", "EMPTY", "TIMEOUT", "HTTP 500", ...), so an empty stream is a failure
    rather than an empty answer that happens to match nothing.
    """
    asker = client or _stream_client()
    t0 = time.time()
    try:
        res = asker(list(messages), base_url, api_key, chat_id, forwarded_user, timeout) or {}
    except Exception as exc:  # the client catches its own; this is belt and braces
        res = {"answer": "", "status": f"ERROR:{type(exc).__name__}"}
    return {
        "answer": str(res.get("answer") or ""),
        "intent": None,
        "seconds": round(time.time() - t0, 1),
        "status": str(res.get("status") or "ERROR:no status"),
        "first_byte": res.get("first_byte"),
    }


def compare_streamed(
    case: Dict[str, Any],
    unstreamed: Dict[str, Any],
    streamed: Dict[str, Any],
    expected_live: Sequence[str],
    matches,
) -> Dict[str, Any]:
    """Score one case on both /v1 paths by the probe's rules, and say where they differ.

    The LANE is checked only when BOTH sides report one. Otherwise the side that reports a
    lane would be graded on more evidence than the side that does not, and a lane failure on
    the unstreamed path would read as a stream divergence. The unstreamed lane is still
    carried in the row, so a wrong lane is visible — it is just not what this verdict is about.
    """
    lane_comparable = unstreamed.get("intent") is not None and streamed.get("intent") is not None
    u_intent = unstreamed.get("intent") if lane_comparable else None
    s_intent = streamed.get("intent") if lane_comparable else None
    u_ok, u_why = evaluate_case(case, unstreamed["answer"], u_intent, expected_live, matches)
    s_ok, s_why = evaluate_case(case, streamed["answer"], s_intent, expected_live, matches)
    if unstreamed["status"] != "OK":
        u_ok, u_why = False, f"transport {unstreamed['status']}"
    if streamed["status"] != "OK":
        s_ok, s_why = False, f"transport {streamed['status']}"
    same_text = " ".join(unstreamed["answer"].split()) == " ".join(streamed["answer"].split())
    return {
        "group": case.get("group", ""),
        "question": case["question"],
        "unstreamed_ok": u_ok,
        "streamed_ok": s_ok,
        "unstreamed_why": u_why,
        "streamed_why": s_why,
        "verdict": stream_verdict(u_ok, s_ok),
        "lane_expected": case_checks_intent(case),
        "lane_checked": lane_comparable and case_checks_intent(case),
        "unstreamed_intent": unstreamed.get("intent"),
        "same_text": same_text,
        "numbers": numeric_divergence(unstreamed["answer"], streamed["answer"]),
        "unstreamed_answer": unstreamed["answer"][:1200],
        "streamed_answer": streamed["answer"][:1200],
        "unstreamed_seconds": unstreamed.get("seconds"),
        "streamed_seconds": streamed.get("seconds"),
        "first_byte": streamed.get("first_byte"),
    }


def stream_report_lines(rows: List[Dict[str, Any]], header: Dict[str, str]) -> List[str]:
    """The written report for --stream. Divergence first."""
    divergent = [r for r in rows if r["verdict"] in STREAM_DIVERGENT]
    lines = [
        "# Streamed versus unstreamed — /v1/chat/completions\n",
        f"Model `{header.get('model','')}` · building `{header.get('building','')}` · "
        f"identity `{header.get('identity','')}` · run {header.get('when','')}\n",
        *header.get("cache_lines", []),
        "Open WebUI streams by default, and the streamed branch rebuilds the final state from "
        "the last streamed step rather than from the workflow's return value. Each case was "
        "asked through /v1 unstreamed and streamed; the streamed answer is reassembled from "
        "its chunks by `scripts/ask_questions.py`'s client, with the pipeline-steps panel "
        "removed.\n",
        f"**{len(rows)} cases, {len(divergent)} divergent.** Two generations of one question "
        "are not expected to be word-identical at temperature, so `same text` is reported "
        "and not scored; the verdict is the probe's markers on each side.\n",
        "| verdict | group | question | unstreamed | streamed | same text | lane | why |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda x: x["verdict"] not in STREAM_DIVERGENT):
        mark = "**" if r["verdict"] in STREAM_DIVERGENT else ""
        lines.append(
            f"| {mark}{r['verdict']}{mark} | {r['group']} | {r['question'][:52]} | "
            f"{'PASS' if r['unstreamed_ok'] else 'FAIL'} | "
            f"{'PASS' if r['streamed_ok'] else 'FAIL'} | {'yes' if r['same_text'] else 'no'} | "
            f"{r['unstreamed_intent'] or '—'} | "
            f"{(r['unstreamed_why'] or r['streamed_why'])[:60]} |"
        )
    lines.append("")
    unchecked = [r for r in rows if not r["lane_checked"] and r.get("lane_expected")]
    if unchecked:
        lines.append(
            f"{len(unchecked)} case(s) assert a lane. The streamed side reports none to this "
            "client, so those assertions were skipped on BOTH sides and the verdict is on the "
            "text alone. The unstreamed lane is in the `lane` column.\n"
        )
    numeric = [r for r in rows if r["numbers"]["only_chat"] or r["numbers"]["only_v1"]]
    if numeric:
        lines += [
            "## Figures one path stated and the other did not\n",
            "| question | only unstreamed | only streamed |",
            "|---|---|---|",
        ]
        for r in numeric:
            lines.append(
                f"| {r['question'][:50]} | {', '.join(r['numbers']['only_chat'][:8])} | "
                f"{', '.join(r['numbers']['only_v1'][:8])} |"
            )
        lines.append("")
    if divergent:
        lines.append("## What came back on the divergent cases\n")
        for r in divergent:
            lines += [
                f"### {r['question']}",
                "",
                "unstreamed:",
                "```",
                r["unstreamed_answer"][:700],
                "```",
                "streamed:",
                "```",
                r["streamed_answer"][:700],
                "```",
                "",
            ]
    return lines


# ── the response cache ──────────────────────────────────────────────────────────
class CacheFlusher:
    """Flush `resp_cache:*` before an ask, using the regression probe's own flush.

    Remembers every failure so the report can say, at the top, that a comparison may have
    been between an answer and its own cached copy.
    """

    def __init__(self, flush, container: str, enabled: bool = True):
        self._flush = flush
        self.container = container
        self.enabled = enabled
        self.flushes = 0
        self.failures: List[str] = []

    def __call__(self) -> None:
        if not self.enabled:
            return
        result = self._flush(self.container)
        self.flushes += 1
        if not result.get("ok"):
            error = str(result.get("error") or "unknown error")
            if not self.failures:
                print(f"  !! RESPONSE CACHE NOT FLUSHED: {error}")
            self.failures.append(error)

    def report_lines(self) -> List[str]:
        """What the report says about the cache, placed under its title."""
        if not self.enabled:
            return [
                "> **RESPONSE CACHE DELIBERATELY NOT FLUSHED (`--no-flush`).** The second ask "
                "of each question may have been served the first ask's answer, in which case "
                "the two paths agree by construction.\n"
            ]
        if self.failures:
            return [
                f"> ## WARNING — {len(self.failures)} of {self.flushes} RESPONSE-CACHE "
                "FLUSHES FAILED\n"
                f"> first error: {self.failures[0]}\n>\n"
                "> Any comparison after a failed flush may be between an answer and its own "
                "cached copy (BUG-662). Do not read agreement here as parity.\n"
            ]
        return [f"Response cache flushed before every ask ({self.flushes} flushes).\n"]


# ── report ──────────────────────────────────────────────────────────────────────
def report_lines(
    single: List[Dict[str, Any]],
    conversations: List[Dict[str, Any]],
    header: Dict[str, str],
) -> List[str]:
    """The written report. Divergence first; agreement is the boring part."""
    divergent = [r for r in single if r["verdict"] in DIVERGENT]
    lines = [
        "# Endpoint parity — /chat versus /v1/chat/completions\n",
        f"Model `{header.get('model','')}` · building `{header.get('building','')}` · "
        f"identity `{header.get('identity','')}` · run {header.get('when','')}\n",
        *header.get("cache_lines", []),
        "The regression probe posts to `/chat`. Open WebUI — the demo client — posts to "
        "`/v1/chat/completions`. The two endpoints do not share their memory wiring, so a "
        "pass rate measured on one is not evidence about the other. This asks the same "
        "questions through both.\n",
    ]
    if single:
        lines += [
            f"**Single-turn: {len(single)} cases asked through both endpoints, "
            f"{len(divergent)} divergent.**\n",
            "| verdict | group | question | /chat | /v1 | why |",
            "|---|---|---|---|---|---|",
        ]
        for r in sorted(single, key=lambda x: x["verdict"] not in DIVERGENT):
            mark = "**" if r["verdict"] in DIVERGENT else ""
            lines.append(
                f"| {mark}{r['verdict']}{mark} | {r['group']} | {r['question'][:56]} | "
                f"{'PASS' if r['chat_ok'] else 'FAIL'} | {'PASS' if r['v1_ok'] else 'FAIL'} | "
                f"{(r['chat_why'] or r['v1_why'])[:60]} |"
            )
        lines.append("")
        skipped_lane = [r for r in single if r["intent_check_skipped"]]
        if skipped_lane:
            lines += [
                f"{len(skipped_lane)} case(s) assert a LANE, and `/v1/chat/completions` "
                "does not report one for them (no `ontosage_intent` — a server older than "
                "TODO-657, or a turn that never classified). Those assertions were skipped on "
                "`/v1` and the case is scored on its text markers alone there — so `/v1` is "
                "being graded on LESS evidence, never on more.\n",
            ]
        numeric = [r for r in single if r["numbers"]["only_chat"] or r["numbers"]["only_v1"]]
        if numeric:
            lines += [
                "## Figures one endpoint stated and the other did not\n",
                "Both answers can satisfy the same markers and still disagree about a number "
                "no marker names.\n",
                "| question | only /chat | only /v1 |",
                "|---|---|---|",
            ]
            for r in numeric:
                lines.append(
                    f"| {r['question'][:50]} | {', '.join(r['numbers']['only_chat'][:8])} | "
                    f"{', '.join(r['numbers']['only_v1'][:8])} |"
                )
            lines.append("")
    if conversations:
        lines += [
            "## Multi-turn — what the regression probe cannot see\n",
            "`/chat` persists no turn summary; both endpoints run the context-switch guard "
            "since BUG-655. These "
            "conversations hold one session id (`/chat`) or one chat id plus the full message "
            "array (`/v1`) across their turns.\n",
            "| conversation | turn | endpoint | question | result | referent | why |",
            "|---|---|---|---|---|---|---|",
        ]
        for c in conversations:
            for t in c["turns"]:
                lines.append(
                    f"| {c['id']} | {t['n']} | {t['endpoint']} | {t['question'][:40]} | "
                    f"{'PASS' if t['ok'] else '**FAIL**'} | {t.get('coref') or '—'} | "
                    f"{t['why'][:44]} |"
                )
        lines.append("")
        lines.append("### Why each conversation exists\n")
        for c in conversations:
            lines.append(f"- **{c['id']}** — {c['why']}")
        lines.append("")
        lines.append("### What came back\n")
        for c in conversations:
            for t in c["turns"]:
                lines.append(f"#### {c['id']} · turn {t['n']} · {t['endpoint']}")
                lines.append("")
                lines.append(f"> {t['question']}")
                lines.append("")
                lines.append("```")
                lines.append((t["answer"] or "")[:700])
                lines.append("```")
                lines.append("")
    return lines


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--graphdb-url", default="http://localhost:7200")
    ap.add_argument("--graphdb-repo", default="bldg")
    ap.add_argument("--only", default="", help="single-turn cases in this group only")
    ap.add_argument(
        "--sample",
        type=int,
        default=0,
        help="every Nth case so the sample spreads across groups; 0 = all of them. A small "
        "sample is the responsible default while anything else shares the GPU.",
    )
    ap.add_argument("--multiturn-only", action="store_true")
    ap.add_argument("--single-only", action="store_true")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument(
        "--forwarded-user",
        default="",
        help="identity forwarded to /v1 (X-OpenWebUI-User-Email by default). Defaults to the "
        "SAME account /chat logs in as, so a divergence is about the wiring and not about two "
        "different roles. Pass a demo account to measure a role instead.",
    )
    ap.add_argument("--dry-run", action="store_true", help="resolve and print; ask nothing")
    ap.add_argument(
        "--stream",
        action="store_true",
        help="CAVEAT-656: ask each single-turn case through /v1 unstreamed AND streamed (as "
        "Open WebUI does) and compare the reassembled answers. Conversations are not run.",
    )
    ap.add_argument(
        "--no-flush",
        action="store_true",
        help="do NOT flush resp_cache:* before each ask — the second ask of a question is then "
        "likely served the first ask's cached answer",
    )
    ap.add_argument("--redis-container", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    if not args.out:
        stem = "ENDPOINT_PARITY_STREAM_RUN" if args.stream else "ENDPOINT_PARITY_RUN"
        args.out = str(REPO / "docs" / f"{stem}_{date.today():%Y-%m-%d}.md")

    probe = _load("_regression_probe", "scripts/regression_probe.py")
    cap = _load("_cap", "scripts/capture_golden_baseline.py")
    replay = _load("_replay", "scripts/corpus_replay.py")
    matches = probe._matches

    api_key = replay._env_or_dotenv("PIPELINE_API_KEY", "sk-ontobot-pipeline")
    forwarded_header = replay._env_or_dotenv("FORWARDED_USER_HEADER", "X-OpenWebUI-User-Email")
    forwarded_user = args.forwarded_user or replay._env_or_dotenv("ADMIN_USERNAME", "")

    if args.stream and forwarded_header.lower() != STREAM_CLIENT_HEADER.lower():
        print(
            f"--stream reuses scripts/ask_questions.py's client, which forwards the identity "
            f"only as {STREAM_CLIENT_HEADER}; FORWARDED_USER_HEADER is {forwarded_header}. The "
            "streamed turn would run at a different role from the unstreamed one, so every "
            "divergence would be about identity. Refusing to measure that."
        )
        return 2

    fresh = CacheFlusher(
        probe.flush_response_cache,
        args.redis_container or probe.REDIS_CONTAINER,
        enabled=not args.no_flush and not args.dry_run,
    )

    vocab = resolve_vocabulary(args.graphdb_url, args.graphdb_repo)
    conversations = render_conversations(CONVERSATIONS, vocab) if vocab else []
    if not vocab:
        print("  NO CONVERSATIONS: the graph did not yield two distinguishable rooms/floors.")

    cases: List[Dict[str, Any]] = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    active = probe._active_building(args.base_url) if not args.dry_run else ""
    if active:
        cases = [c for c in cases if not c.get("building") or c["building"] == active]
    if args.only:
        cases = [c for c in cases if c.get("group") == args.only]
    if args.sample and args.sample > 0:
        step = max(1, len(cases) // args.sample)
        cases = cases[::step][: args.sample]
    if args.multiturn_only:
        cases = []
    if args.stream:
        conversations = []

    if args.dry_run:
        print(f"vocabulary: {json.dumps(vocab, indent=2) if vocab else '(unresolved)'}")
        print(f"single-turn cases selected: {len(cases)}")
        for c in cases:
            print(f"  [{c.get('group','')}] {c['question'][:80]}")
        for conv in conversations:
            print(f"\nconversation {conv['id']}:")
            for i, t in enumerate(conv["turns"], 1):
                print(f"  {i}. {t['question']}")
                if t.get("coref"):
                    print(
                        f"     referent check: must mean {t['coref'][0]!r}, not {t['coref'][1]!r}"
                    )
        return 0

    token = cap._login(args.base_url)
    provider, model = cap._active_model(args.base_url, token)
    header = {
        "model": f"{provider}/{model}",
        "building": active or "unreported",
        "identity": forwarded_user or "anonymous readonly",
        "when": time.strftime("%Y-%m-%d %H:%M"),
    }

    if args.stream:
        return _run_stream_mode(args, cases, probe, matches, api_key, forwarded_user, fresh, header)

    print(
        f"endpoint parity: {len(cases)} single-turn cases + "
        f"{len(conversations)} conversations · {provider}/{model} · building {active or '?'}"
    )
    print(f"  /chat as the logged-in session · /v1 as {forwarded_user or '(anonymous readonly)'}\n")

    single: List[Dict[str, Any]] = []
    for i, case in enumerate(cases, 1):
        timeout = int(case.get("timeout_s") or args.timeout)
        expected_live: List[str] = []
        for query in case.get("expect_sparql", []) or []:
            value = probe._scalar_from_graph(query, args.graphdb_url, args.graphdb_repo)
            expected_live.append(value if value is not None else "<graph query failed>")
        fresh()
        chat = ask_chat(
            case["question"], args.base_url, token, f"parity-{uuid.uuid4().hex[:8]}", timeout
        )
        fresh()
        v1 = ask_v1(
            v1_messages([], case["question"]),
            args.base_url,
            api_key,
            f"parity-{uuid.uuid4().hex[:8]}",
            forwarded_user,
            forwarded_header,
            timeout,
        )
        chat_ok, chat_why = evaluate_case(
            case, chat["answer"], chat["intent"], expected_live, matches
        )
        v1_ok, v1_why = evaluate_case(case, v1["answer"], v1["intent"], expected_live, matches)
        chat_ok = chat_ok and chat["status"] == "OK"
        v1_ok = v1_ok and v1["status"] == "OK"
        if chat["status"] != "OK":
            chat_why = f"transport {chat['status']}"
        if v1["status"] != "OK":
            v1_why = f"transport {v1['status']}"
        row = {
            "group": case.get("group", ""),
            "question": case["question"],
            "chat_ok": chat_ok,
            "v1_ok": v1_ok,
            "chat_why": chat_why,
            "v1_why": v1_why,
            "verdict": verdict(chat_ok, v1_ok),
            "intent_check_skipped": case_checks_intent(case) and v1["intent"] is None,
            "numbers": numeric_divergence(chat["answer"], v1["answer"]),
            "chat_answer": chat["answer"][:1200],
            "v1_answer": v1["answer"][:1200],
            "chat_seconds": chat["seconds"],
            "v1_seconds": v1["seconds"],
        }
        single.append(row)
        print(
            f"  {row['verdict']:<10} {i:>3}/{len(cases)} [{row['group']}] {case['question'][:52]}"
            + (f"\n       -> /chat: {chat_why}" if chat_why else "")
            + (f"\n       -> /v1:   {v1_why}" if v1_why else "")
        )

    results: List[Dict[str, Any]] = []
    if not args.single_only:
        for conv in conversations:
            print(f"\nconversation {conv['id']}")
            turns: List[Dict[str, Any]] = []
            for endpoint in ("/chat", "/v1"):
                session = f"parity-{conv['id']}-{uuid.uuid4().hex[:6]}"
                history: List[Tuple[str, str]] = []
                for n, turn in enumerate(conv["turns"], 1):
                    # The cache is keyed on the question text, not the conversation, so the
                    # same turn asked on the other endpoint would otherwise be a cache hit.
                    fresh()
                    if endpoint == "/chat":
                        res = ask_chat(
                            turn["question"], args.base_url, token, session, args.timeout
                        )
                    else:
                        res = ask_v1(
                            v1_messages(history, turn["question"]),
                            args.base_url,
                            api_key,
                            session,
                            forwarded_user,
                            forwarded_header,
                            args.timeout,
                        )
                    ok, why, coref = check_turn(turn, res["answer"], matches)
                    if res["status"] != "OK":
                        ok, why = False, f"transport {res['status']}"
                    history.append((turn["question"], res["answer"]))
                    turns.append(
                        {
                            "n": n,
                            "endpoint": endpoint,
                            "question": turn["question"],
                            "ok": ok,
                            "why": why,
                            "coref": coref,
                            "answer": res["answer"],
                            "seconds": res["seconds"],
                        }
                    )
                    print(
                        f"  {endpoint:<5} turn {n} {'PASS' if ok else 'FAIL'} "
                        f"{coref or ''} {why}"
                    )
            results.append({"id": conv["id"], "why": conv["why"], "turns": turns})

    divergent = [r for r in single if r["verdict"] in DIVERGENT]
    carried = [
        (c["id"], t["endpoint"])
        for c in results
        for t in c["turns"]
        if t.get("coref") == CO_CARRIED
    ]
    print(f"\n{len(divergent)}/{len(single)} single-turn cases DIVERGE between the endpoints")
    if carried:
        print(f"CARRIED REFERENT (BUG-524 shape) on: {carried}")
    header["cache_lines"] = fresh.report_lines()
    Path(args.out).write_text(
        "\n".join(report_lines(single, results, header)) + "\n", encoding="utf-8"
    )
    print(f"[written] {args.out}")
    return 1 if (divergent or carried) else 0


def _run_stream_mode(args, cases, probe, matches, api_key, forwarded_user, fresh, header) -> int:
    """--stream: each case through /v1 unstreamed, then streamed; report where they differ."""
    print(
        f"stream parity: {len(cases)} cases through /v1, stream:false then stream:true · "
        f"{header['model']} · building {header['building']} · as {header['identity']}\n"
    )
    rows: List[Dict[str, Any]] = []
    for i, case in enumerate(cases, 1):
        timeout = int(case.get("timeout_s") or args.timeout)
        expected_live: List[str] = []
        for query in case.get("expect_sparql", []) or []:
            value = probe._scalar_from_graph(query, args.graphdb_url, args.graphdb_repo)
            expected_live.append(value if value is not None else "<graph query failed>")
        messages = v1_messages([], case["question"])
        fresh()
        unstreamed = ask_v1(
            messages,
            args.base_url,
            api_key,
            f"parity-{uuid.uuid4().hex[:8]}",
            forwarded_user,
            STREAM_CLIENT_HEADER,
            timeout,
        )
        fresh()
        streamed = ask_v1_stream(
            messages,
            args.base_url,
            api_key,
            f"parity-{uuid.uuid4().hex[:8]}",
            forwarded_user,
            timeout,
        )
        row = compare_streamed(case, unstreamed, streamed, expected_live, matches)
        rows.append(row)
        print(
            f"  {row['verdict']:<15} {i:>3}/{len(cases)} [{row['group']}] "
            f"{case['question'][:48]}"
            + (f"\n       -> unstreamed: {row['unstreamed_why']}" if row["unstreamed_why"] else "")
            + (f"\n       -> streamed:   {row['streamed_why']}" if row["streamed_why"] else "")
        )
    divergent = [r for r in rows if r["verdict"] in STREAM_DIVERGENT]
    print(f"\n{len(divergent)}/{len(rows)} cases DIVERGE between streamed and unstreamed /v1")
    header["cache_lines"] = fresh.report_lines()
    Path(args.out).write_text("\n".join(stream_report_lines(rows, header)) + "\n", encoding="utf-8")
    print(f"[written] {args.out}")
    return 1 if divergent else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
