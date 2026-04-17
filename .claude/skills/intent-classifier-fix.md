---
name: intent-classifier-fix
description: Use when the dialogue agent classifies a query to the wrong intent — e.g. a sensor reading question routed as "general", a compliance question routed as "metadata", or any case where the system gives the right data through the wrong path. Covers: reproduce → measure → pick one of three fix strategies → test safely.
---

# Intent Classifier Fix Runbook — OntoSage 14-Intent System

The intent classifier lives entirely in `orchestrator/agents/dialogue_agent.py`. It is an LLM-based classifier — there is no neural model file to retrain. Every fix is a prompt change or a few-shot example addition.

---

## Step 0 — Understand the 14-Intent Taxonomy

File: `dialogue_agent.py:362-376`

| Intent | Routes to | When to use |
|--------|-----------|-------------|
| `general` | → response (LLM direct) | Greetings, off-topic, knowledge questions without building data |
| `metadata` | → sparql | Static properties: sensor type, location, unit |
| `analytics` | → sparql → sql → analytics | Time-series values: current reading, average, history |
| `clarification` | → response | Query is too vague to execute |
| `discovery` | → response OR sparql (if spatial query) | "What sensors/zones exist?" |
| `report` | → sparql → sql → report | Structured multi-section document |
| `export` | → export node | CSV / JSON / HTML data download |
| `anomaly` | → sparql → sql → anomaly | Threshold violations, spike detection |
| `compare` | → sparql → sql → analytics | Side-by-side sensor/zone/time comparison |
| `trend` | → sparql → sql → analytics | Rate of change, time evolution |
| `recommend` | → sparql → sql → analytics | Optimization suggestions |
| `planner` | → planner | Multi-step: "generate report AND export as CSV" |
| `control` | → response (blocked) | Change system state (not yet supported) |
| `compliance` | → sparql → sql → analytics | Standards check (ASHRAE, WELL, BREEAM) |

**Routing code:** `workflow.py:1079` — `_route_from_dialogue()`

---

## Step 1 — Reproduce the Misclassification

### 1a. Trigger the query through the app and capture the logged intent

```bash
# Watch the orchestrator log while sending the query
docker-compose logs -f orchestrator 2>&1 | grep -E "Intent:|intent=" &
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "<your failing query here>", "session_id": "debug-intent-01"}' \
  | python -m json.tool
```

The log will print:
```
🎯 Intent Detection Result:
   ├─ Intent: <detected_intent>
   ├─ Entities: [...]
   └─ Explanation: ...
```

**Write down:** what was detected vs what was expected.

### 1b. Test the prompt in isolation (no Docker needed)

This lets you iterate without restarting the stack:

```python
# Run from the project root: python -c "..." or in a notebook
import asyncio, json, sys
sys.path.insert(0, '.')

from orchestrator.agents.dialogue_agent import DialogueAgent
from shared.models import ConversationState, Message

async def test_intent(query: str, persona: str = "general"):
    agent = DialogueAgent()
    state = ConversationState(session_id="test", building_id="bldg1")
    state.messages.append(Message(role="user", content=query))
    result = await agent.detect_intent(state)
    print(json.dumps({
        "intent": result.get("intent"),
        "entities": result.get("entities"),
        "explanation": result.get("explanation"),
    }, indent=2))

asyncio.run(test_intent("<your failing query>"))
```

> **Note:** This calls the live LLM. Set `MODEL_PROVIDER` and relevant API key in `.env` before running.

---

## Step 2 — Measure the Scope of the Problem

Before changing anything, check if this is a one-off or a pattern:

```python
# Test a batch of related queries in one call
queries = [
    ("What is the current CO2 level?",         "analytics"),   # expected
    ("Show me CO2 right now",                   "analytics"),   # expected
    ("Is CO2 high in zone 5?",                 "anomaly"),     # expected
    ("List all CO2 sensors",                    "metadata"),    # expected
    ("Export CO2 data as CSV",                  "export"),      # expected
    ("Check WELL standard for CO2",             "compliance"),  # expected
]

results = []
for q, expected in queries:
    result = asyncio.run(test_intent(q))
    got = result["intent"]
    results.append({"q": q, "expected": expected, "got": got, "ok": got == expected})

import tabulate
print(tabulate.tabulate(results, headers="keys"))
```

**Goal:** Know exactly which queries fail and which pass before you make changes.

---

## Step 3 — Choose a Fix Strategy

There are exactly three levers. Use the right one:

### Strategy A — Add/Improve a Few-Shot Example (first choice)

**When:** The LLM is confused between two similar-looking intents (e.g. `analytics` vs `metadata` for "What CO2 sensors are in zone 5?" — is the user asking for a list or a reading?).

**File:** `orchestrator/data/few_shot_library.json`

**Format:** Key = `"persona|intent"`. Value = array of `{"q": ..., "a": ...}` where `a` is valid JSON (the answer the LLM should produce).

```json
"general|analytics": [
  {
    "q": "What is the current CO2 level in zone 5?",
    "a": "{\"intent\":\"analytics\",\"entities\":[\"Zone_5\"],\"required_analytics\":[\"latest\"]}"
  },
  {
    "q": "Is CO2 high in the office right now?",
    "a": "{\"intent\":\"anomaly\",\"entities\":[],\"required_analytics\":[\"anomaly\",\"latest\"]}"
  }
]
```

**Rules:**
- Max 2 examples per `persona|intent` key (the picker selects up to 2 at runtime — more are silently ignored).
- Use the `"general|intent"` key unless the failure only affects one persona.
- The `"a"` field must be valid JSON — test it with `json.loads()`.
- The few-shot examples are injected at `dialogue_agent.py:408` via `_get_few_shot_examples()`.

**After adding, rerun Step 1b to verify the fix.**

---

### Strategy B — Sharpen the Intent Description in the Prompt

**When:** The intent description itself is ambiguous — e.g. two intents overlap in definition, or an important distinction is not described.

**File:** `orchestrator/agents/dialogue_agent.py:362-376` — the numbered list inside `_build_intent_detection_prompt()`

**What to change:**

Look at the description for the failing intent and the competing intent. Add a distinguishing phrase.

Example — sharpening `analytics` vs `anomaly`:

```python
# Before
- "analytics"  : Dynamic data queries (current reading, average, history, time-series)
- "anomaly"    : Detect out-of-range, spike, or unusual sensor readings.

# After
- "analytics"  : Dynamic data queries (current reading, average, history, time-series). Use this when user wants a VALUE.
- "anomaly"    : Detect out-of-range, spike, or unusual readings. Use ONLY when user implies a PROBLEM or THRESHOLD violation (e.g. "high", "too much", "alert", "unsafe", "violation").
```

**Rules:**
- Keep each description on one line — the LLM sees all 14 in a numbered list.
- Do not add new intents here — the routing code in `workflow.py:1079` must handle every label you add.
- Run the full batch from Step 2 after changing to confirm you haven't broken other intents.

---

### Strategy C — Reorder the Taxonomy

**When:** The LLM systematically picks the first matching intent out of two near-synonyms. This is a positioning effect.

**Effect:** Move the more specific intent above the more general one.

**Example:** If `compliance` is being resolved as `analytics` (because analytics is listed first and both involve data), move `compliance` above `analytics` in the prompt list at `dialogue_agent.py:362`.

**Warning:** Reordering affects all queries. Always run the full batch from Step 2 before and after.

---

## Step 4 — Verify the Routing After the Fix

Intent is only half the problem. After the fix, confirm the route is correct.

```bash
# The routing logic
grep -n "elif intent ==" orchestrator/workflow.py | head -20
```

**File:** `workflow.py:1079` — `_route_from_dialogue()`

Check that the intent you fixed routes to the correct node. The test suite for routing is:

```bash
pytest tests/test_routing_and_contracts.py -v -k "route" 2>&1 | tail -30
```

If you added a new intent string (you shouldn't need to), add the corresponding `elif` in `_route_from_dialogue()` or the test will fail.

---

## Step 5 — Automated Accuracy Test

Run the built-in routing tests to catch regressions:

```bash
# Routing correctness (14+ intents)
pytest tests/test_routing_and_contracts.py -v 2>&1 | tail -40

# Prompt builder sanity
pytest tests/test_phase_cde_improvements.py -v -k "intent" 2>&1 | tail -20

# Full unit suite
pytest -m unit -x -q 2>&1 | tail -20
```

**Gate:** All tests must pass (0 failed) before committing.

---

## Step 6 — Write a Regression Fixture

Always add a test that would have caught this failure:

**File:** `tests/test_routing_and_contracts.py` — add to the `TestDialogueRouting` class

```python
@pytest.mark.parametrize("query,expected_intent", [
    # Regression: CO2 level question was incorrectly classified as metadata
    ("What is the current CO2 level in zone 5?",    "analytics"),
    ("Is CO2 too high in the office?",               "anomaly"),
    ("Check WELL standard CO2 limits",               "compliance"),
])
def test_intent_co2_family(self, query, expected_intent):
    """Regression: CO2 queries must route to correct intent."""
    # This is a routing-layer test — we assert the intent string, not the LLM output
    # (LLM output is non-deterministic; routing logic is deterministic)
    state = self._make_state(expected_intent)
    dest = self._route(expected_intent)
    assert dest != "response" or expected_intent in ["general", "clarification", "control"]
```

> **Note:** Because LLM calls are non-deterministic, unit tests assert routing correctness (given an intent, where does it go?) not LLM classification accuracy. For classification accuracy, use the manual batch test in Step 2 with a fixed-seed model or mock.

---

## Quick Reference: Common Misclassifications

| User says | Often misclassified as | Correct intent | Fix |
|-----------|----------------------|----------------|-----|
| "Is X too high?" | `analytics` | `anomaly` | Strategy A — add anomaly few-shot with "too high", "unsafe" |
| "Show me the trend for..." | `analytics` | `trend` | Strategy B — add "rate of change" to trend description |
| "Compare zone 5 and zone 6" | `analytics` | `compare` | Strategy A — add compare few-shot with two entities |
| "Check ASHRAE compliance" | `analytics` or `report` | `compliance` | Strategy B — make compliance description more specific |
| "Give me everything about zone 5" | `discovery` | `metadata` | Strategy B — "everything about X" → metadata |
| "Export last week's data as CSV" | `report` | `export` | Strategy A — export few-shot with explicit format |
| "Generate a report and save it" | `report` | `planner` | Strategy A — planner few-shot: multi-step with "and" |
| "What sensors are available?" | `metadata` | `discovery` | Already correct — but check `discovery_filter` is set |

---

## Files Modified By This Skill

| File | What changes |
|------|-------------|
| `orchestrator/data/few_shot_library.json` | Strategy A: new `{"q","a"}` entries |
| `orchestrator/agents/dialogue_agent.py:362-376` | Strategy B/C: intent description text |
| `tests/test_routing_and_contracts.py` | Regression test fixture |
