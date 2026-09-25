#!/usr/bin/env python3
"""
J_complexity_master_table.py
============================

Build a MASTER COMPLEXITY TABLE from the free-form survey questions in
``inputs/questions_by_user.csv``.

Implements the spec in ``scripts/smart_building_classification_prompt.md``.

For every user question the script asks an LLM -- OpenAI (e.g. gpt-5.5), Anthropic
Claude, or a local Ollama model on http://localhost:11434 -- to classify it on TWO
INDEPENDENT axes:

  (1) SURFACE / cognitive complexity (`level`, 1-6) -- how hard the question is for
      a HUMAN to reason about (type of thinking, # reasoning steps, uncertainty,
      ambiguity).
  (2) LATENT / architectural complexity (`latent_level`, 1-6) -- how hard it is to
      ANSWER with an automated smart-building pipeline so the answer matches what a
      knowledgeable human stakeholder would produce manually (data sources, compute,
      components, integration). A question can be cognitively simple (L1) yet
      architecturally complex (L4): "can the building measure greenery's effect on
      satisfaction?" is a one-word capability check to a human, but a real answer
      needs surveys + greenery sensors + time-series correlation.

The 6-level scale (shared by both axes; names per the spec):
  L1 Factual Recall  L2 Comparative Analysis  L3 Inferential Reasoning
  L4 Causal Diagnosis  L5 Systemic Synthesis  L6 Meta / Strategic Reasoning

Core assumptions (from the spec):
  * Actuation is ALWAYS active; there are NO out-of-scope questions. Anything can be
    answered from a mix of building data, ontology, analytics, and general LLM
    knowledge. Capability gaps are recorded as ``answerability=requires_extension``
    (a new component/data pipeline is needed) -- never as "out of scope".
  * ANSWER_BASIS distinguishes how the answer is sourced:
      - general-knowledge : the LLM answers directly with no building data ("how does
        temperature affect the body?", "how does CO2 affect productivity?"). OntoSage
        just makes ONE LLM call, so these get latent_level=1, answerability=full,
        architecture="LLM (general knowledge)", pipeline "dialogue -> LLM -> response",
        and NO [NEW] items. Filter answer_basis=general-knowledge to find the questions
        that need NO data pipeline at all.
      - building-data : needs this building's telemetry/topology/metadata.
      - hybrid : a general norm applied to this building's live data.
  * PERSONA-AWARE: each question carries the asker's role; the model infers the
    likely persona (Building Manager, BMS Operator, Executive, Student, Guest,
    Occupant) and grades the answer depth that persona would expect -- which mainly
    informs the LATENT (architectural) effort.

Grounded in REAL OntoSage capabilities. The prompt tells the model exactly what is
ALREADY IMPLEMENTED (GraphDB+SPARQL Brick/BACnet/ASHRAE-223 ontology, MySQL time-series,
analytics sandbox, forecasting, agentic RAG, Qdrant capability KB, floor-plan/DWG+PDF
spatial, report intake, 26 intents, conversation memory) and what DATA is already loaded
for the active building (bldg1 = Abacws: full ontology for all 6 floors; ~680 sensor
points of temperature/CO2/humidity; floor plans 0-5; capability facts; LIVE data on
Floor 5 only). It also states the KNOWN GAPS (other sensor modalities, floors 0-4 live
data, weather/tariff APIs, satisfaction surveys). The model treats implemented things as
available (no tag) and tags only true gaps with ``[NEW] ``, naming the extension
mechanism -- add a data source, extend the ontology/KB, or drop a file in inputs/. So you
can grep ``[NEW]`` / ``answerability=requires_extension`` for what OntoSage genuinely
lacks, and the architecture is still OPEN-ENDED (multiple data sources allowed).

Why a *fixed* rubric instead of letting the model invent levels?
    The corpus is ~5.8k questions => ~1,150 LLM calls at chunk-size 5.  If each call
    invented its own definitions the levels would drift and the table would be
    unmergeable.  The rubric below is frozen and injected into every prompt; the
    model only *assigns* and *fills requirements*.

Why process 1-5 questions per call (not all at once)?
    Small chunks keep the model focused on each question and keep prompts short
    and cheap.  ``--chunk-size`` is clamped to [1, 5] by design.

Why checkpointing?
    1,150 calls take a long time and can crash/rate-limit halfway.  The output
    CSV is the checkpoint: completed questions are skipped on the next run, so
    you can stop (Ctrl-C) and resume freely.

--------------------------------------------------------------------------------
Usage (PowerShell, run from the repo ROOT -- the folder name has spaces, so the
script path MUST be quoted; input/output default to the script's own folder, so the
current directory does not matter):

    # define the path once, then reuse it:
    $J = "paper/Survey analysis and results/scripts/J_complexity_master_table.py"

    # OpenAI gpt-5.5 (best reasoning; key auto-loaded from .env -> OPENAI_API_KEY):
    python $J --provider openai --model gpt-5.5 --dedup --turns 1

    # Local Ollama (reachable, free, slower):
    python $J --provider ollama --model gpt-oss:20b --dedup --limit 20

    # Anthropic Claude (key from .env -> ANTHROPIC_API_KEY ; pip install anthropic):
    python $J --provider anthropic --model claude-opus-4-8 --dedup

    # one-liner without the variable (mind the quotes):
    python "paper/Survey analysis and results/scripts/J_complexity_master_table.py" --provider openai --model gpt-5.5 --dedup --turns 1

The run is resumable: re-running with the same --output continues where it left off.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
HERE = Path(__file__).resolve().parent  # .../scripts
SURVEY_ROOT = HERE.parent  # .../Survey analysis and results
DEFAULT_INPUT = SURVEY_ROOT / "inputs" / "questions_by_user_unique.csv"
DEFAULT_OUTPUT = SURVEY_ROOT / "outputs" / "tables" / "complexity_master_table.csv"

# --------------------------------------------------------------------------- #
# The frozen rubric (single source of truth, injected into every prompt)
# --------------------------------------------------------------------------- #
RUBRIC = """\
Classify each question on TWO INDEPENDENT axes.

AXIS 1 -- SURFACE / cognitive complexity (`level`, how hard for a HUMAN to reason):
  | cognitive_operation | reasoning_load | answer_determinacy | uncertainty | ambiguity        | level | level_name                |
  | recall              | trivial        | single-fact        | none        | clear            | 1     | Factual Recall            |
  | comparison          | low            | multi-fact         | low         | clear            | 2     | Comparative Analysis      |
  | inference           | moderate       | derived            | moderate    | moderate         | 3     | Inferential Reasoning     |
  | causal_analysis     | high           | causal             | high        | moderate         | 4     | Causal Diagnosis          |
  | synthesis           | high           | synthesised        | high        | ambiguous        | 5     | Systemic Synthesis        |
  | meta_reasoning      | very_high      | open               | very_high   | highly_ambiguous | 6     | Meta / Strategic Reasoning |
  `why` = 1 short justification citing the key fields that set the level.

AXIS 2 -- LATENT / architectural complexity (`latent_level`, how hard for the SYSTEM
to answer so the result matches a knowledgeable human's manual answer). SAME 1-6 scale
and SAME level_names, but graded on SYSTEM effort:
  1 single ontology/metadata lookup; no analytics.
  2 a few reads + light comparison/aggregation.
  3 multi-hop retrieval or derived values across linked datasets.
  4 time-series retrieval + analytics (stats / correlation / anomaly / causal).
  5 multi-system data fusion, modelling/forecasting, multi-section report + visuals.
  6 cross-domain orchestration + planning + actuation/control loop, or a NEW method.
  latent_level is INDEPENDENT of level: a cognitively simple (L1) question can be
  architecturally complex (L4) if a real answer needs sensor fusion + causal inference.
  `latent_why` = what makes the system effort high or low.

CORE ASSUMPTION: actuation is ALWAYS active; there are NO out-of-scope questions. Any
question is answerable from a mix of building data, ontology, analytics and general LLM
LLM knowledge. If a component or dataset is missing, set answerability=requires_extension
(NOT out-of-scope) and still grade the rigorous real answer.

ANSWER_BASIS -- decide HOW the answer is sourced (this gates the latent effort):
  * general-knowledge : answerable satisfactorily from the LLM's OWN world knowledge,
      with NO building-specific data (definitions, science, physiology, "how does X
      affect Y" in general, standards/concepts explained generically, advice).
      OntoSage answers these with a SINGLE LLM call. So for these:
        - latent_level = 1 (trivial system effort), answerability = full,
        - architecture = "LLM (general knowledge)" ONLY -- do NOT attach ontology /
          RAG / time-series / analytics, and do NOT invent a [NEW] evidence corpus or
          literature-retrieval step,
        - data_sources = "general LLM knowledge",
        - pipeline_stages = "dialogue -> LLM answer -> response".
      Do NOT over-engineer a textbook question into a research project. The pragmatic
      LLM answer IS the satisfactory answer here.
  * building-data : needs THIS building's telemetry / topology / metadata (sensors,
      rooms, equipment, logs, knowledge base with text descriptions). Use ontology / time-series / analytics as required.
  * hybrid : a general norm/standard applied to this building's live data, e.g.
      "is my office too hot?" = general comfort range + this room's current temperature + fallback to ask clarifications.
  Pick building-data / hybrid only when building-specific facts are genuinely required;
  otherwise prefer general-knowledge and keep it a cheap LLM call.

PERSONA AWARENESS: each question shows the asker's role. Infer the likely persona and
the answer depth they expect -- this mainly raises/lowers the LATENT effort:
  Building Manager / Facility Team -> data retrieval + analysis + formatted reports (high)
  Technical Engineer / BMS Operator -> system logs, calibration, protocol faults (high-med)
  Executive / Decision Maker -> high-level synthesis, benchmarking, ESG framing (med)
  Student / Academic Researcher -> conceptual explanation + general knowledge (low-med)
  School Guest / Visitor -> factual recall, wayfinding, simple description (low)
  Occupant / General User -> comfort personalisation, simple actuation, lookup (low-med)"""

# Grounded map of what OntoSage ALREADY has vs what is a genuine extension.
TECH_VOCAB = """\
CURRENT ONTOSAGE CAPABILITIES -- these are ALREADY IMPLEMENTED and AVAILABLE. Treat
them as present; do NOT tag them [NEW]. Only tag [NEW] for things NOT in this list.

Implemented components (the deployed pipeline):
  - LangGraph orchestrator: intent routing (26 intents incl. sensor_data, metadata,
    discovery, analytics, compare, trend/forecast, anomaly, recommend, report, export,
    compliance, floor_plan, spatial_query, capability, control, alert, report-intake),
    multi-step planner, conversation memory + co-reference.
  - Ontology / Knowledge Graph on GraphDB via SPARQL: Brick v1.4 + BACnet + ASHRAE 223.
  - Time-series store (MySQL): sensor readings keyed by UUID.
  - Analytics sandbox (sandboxed Python: statistics, anomaly detection, correlation).
  - Forecasting (ARIMA / ETS / linear).
  - Agentic RAG service (semantic fallback when SPARQL is empty).
  - Capability knowledge base (Qdrant, off-ontology facts: amenities, hours, HVAC,
    lifts, fire, etc.).
  - Floor-plan + spatial reasoning (PDF + DWG manifests, per floor).
  - Report intake (fault / complaint / safety / feedback / suggestion -> Postgres).
  - Visualisation, response formatting, RBAC, response cache.
  - LLM backends (OpenAI / Anthropic / local Ollama) for general-knowledge answers.

Already-loaded DATA for the active building (bldg1 = Abacws, Cardiff Univ., 6 floors):
  - Full Brick ontology: topology + device hierarchy for ALL floors; ~680 sensor POINTS
    modelled, of types TEMPERATURE, CO2, HUMIDITY only.
  - Floor plans (PDF + DWG) for floors 0-5.
  - Capability KB facts: building info (opened 2021, architect, ~14000 m2, reception
    hours), HVAC zoning, lifts, showers, baby-change, fire safety, etc.
  - LIVE sensor streams: FLOOR 5 ONLY (floors 0-4 are modelled but not yet streaming).
  - Personas (auditor, caretaker); per-building config (building.yaml, intents.yaml).

KNOWN DATA GAPS -- these ARE genuine extensions, so tag [NEW] and set requires_extension:
  - Live streams for floors 0-4 (modelled but not connected).
  - Any sensor modality beyond temperature / CO2 / humidity -- e.g. energy, water,
    occupancy, noise, light, parking/EV, waste, solar, access/security: NOT instrumented.
  - External feeds (weather, energy tariffs, calendar/occupancy APIs): NOT integrated.
  - Subjective/social data (occupant satisfaction, productivity surveys): NOT collected.
  - Physical BMS write-back / actuation: assumed-on for classification, not yet wired.

EXTENSION RULE -- the answer mechanism is OPEN-ENDED. When something is missing, add it
and PREFIX it with `[NEW] `. A missing item is added via ONE of these mechanisms (say
which): (a) a NEW data source / sensor feed / external API; (b) data/classes added into
the current ontology + capability KB; (c) NEW files placed in the inputs/ folder (TTL,
floor plan, capability YAML). A question may need MULTIPLE data sources -- list each,
prefixing the not-yet-present ones with [NEW]. Set answerability=requires_extension when
any [NEW] item is essential (partial if it only improves the answer); use full only when
the answer needs nothing beyond the CURRENT capabilities + already-loaded data above.

WORKED EXAMPLES (calibrate to these):
  A) "Can the building measure how greenery impacts occupant satisfaction?"
     level=1 Factual Recall (a human reads it as a yes/no capability check).
     latent_level=4 Causal Diagnosis. answer_basis: building-data.
     architecture: ontology/knowledge graph; analytics sandbox; visualisation;
     [NEW] occupant-satisfaction survey pipeline (add as new data source + inputs/ file);
     [NEW] greenery-coverage estimator (CV or IoT plant sensors -> add to ontology).
     data_sources: building ontology; [NEW] occupant satisfaction survey store;
     [NEW] greenery sensor feed.
     pipeline: dialogue -> capability check -> ontology query -> [NEW] survey ingestion
     -> analytics(correlation) -> visualisation -> response
     answerability: requires_extension (greenery + satisfaction data are not collected).
  B) "Why has energy use risen 20% last month despite lower occupancy?"
     level=4 Causal Diagnosis. latent_level=5 Systemic Synthesis. answer_basis: building-data.
     Uses available analytics + anomaly detection + LangGraph, but bldg1 has NO energy,
     occupancy, or tariff data, so those are extensions:
     architecture: ontology/knowledge graph; time-series store; analytics sandbox;
     LangGraph; report generation; [NEW] energy submetering feed; [NEW] occupancy sensing;
     [NEW] weather API; [NEW] energy-tariff API.
     data_sources: building ontology; [NEW] energy meter time-series; [NEW] occupancy
     time-series; [NEW] weather feed; [NEW] tariff feed.
     pipeline: dialogue -> intent classification -> ontology query -> [NEW] energy/occupancy
     retrieval -> [NEW] weather API -> anomaly detection -> causal LangGraph -> report -> response
     answerability: requires_extension (energy + occupancy + weather not yet present).
  C) "What floor is the main cafeteria on?"
     level=1, latent_level=1 (simple ontology topology lookup; no analytics).
     architecture: ontology/knowledge graph. answer_basis: building-data.
     pipeline: dialogue -> intent classification -> ontology query -> response. answerability: full.
  D) "How does temperature affect the human body indoors?"  (GENERAL KNOWLEDGE)
     level=3 Inferential Reasoning (a human explains physiology -- mild reasoning).
     latent_level=1 (the SYSTEM just makes ONE LLM call; no building data needed).
     answer_basis: general-knowledge. architecture: LLM (general knowledge).
     data_sources: general LLM knowledge.
     pipeline: dialogue -> LLM answer -> response. answerability: full.
     NOTE: do NOT add Agentic RAG or a [NEW] literature corpus -- the LLM answers directly.
  E) "How does CO2 affect productivity?"  -> same pattern as D: answer_basis=general-knowledge,
     latent_level=1, architecture "LLM (general knowledge)", answerability=full, no [NEW]."""

# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = f"""\
You are an expert AI system architect and smart-building knowledge engineer. For each
question a human asks a smart-building system, classify it across TWO independent
dimensions -- cognitive (human reasoning) and architectural/technological (automated
pipeline) -- and specify exactly what it takes to answer it like a knowledgeable human
stakeholder would manually.

{RUBRIC}

{TECH_VOCAB}

PER QUESTION, reason in this order:
  (1) Parse intent (information / explanation / diagnosis / prediction / comparison /
      action / creative).
  (2) Identify the likely persona from phrasing + the given role.
  (3) Decide answer_basis: is this GENERAL-KNOWLEDGE (LLM answers directly, no building
      data) vs building-data vs hybrid? (see ANSWER_BASIS above).
  (4) SURFACE cognitive classification -> level (1-6) + the five fields + why.
  (5) LATENT architectural classification -> latent_level (1-6) + latent_why. For
      general-knowledge, latent_level = 1 and architecture is just the LLM.
  (6) Fill architecture / parameters / pipeline_stages / data_sources / answerability.

OUTPUT FORMAT — return ONLY a single JSON object, no prose, no markdown fences:
{{
  "results": [
    {{
      "n": <int, the question number you were given>,
      "cognitive_operation": "<recall | comparison | inference | causal_analysis | synthesis | meta_reasoning>",
      "reasoning_load": "<trivial | low | moderate | high | very_high>",
      "answer_determinacy": "<single-fact | multi-fact | derived | causal | synthesised | open>",
      "uncertainty": "<none | low | moderate | high | very_high>",
      "ambiguity": "<clear | moderate | ambiguous | highly_ambiguous>",
      "level": <int 1-6>,
      "level_name": "<Factual Recall | Comparative Analysis | Inferential Reasoning | Causal Diagnosis | Systemic Synthesis | Meta / Strategic Reasoning>",
      "why": "<<=160 chars: cite the key fields that set the surface level>",
      "latent_level": <int 1-6, system effort; INDEPENDENT of level; =1 for general-knowledge>,
      "latent_level_name": "<same 6-name set as level_name>",
      "latent_why": "<<=160 chars: what makes the system effort high/low>",
      "answer_basis": "<general-knowledge | building-data | hybrid>",
      "architecture": "<components required (baseline + any [NEW]); for general-knowledge use just 'LLM (general knowledge)'>",
      "parameters": "entities: ...; time range: ...; thresholds: ...; units: ...; aggregation: ...; filters: ...",
      "pipeline_stages": "<ordered '->' path; general-knowledge = 'dialogue -> LLM answer -> response'>",
      "data_sources": "<data sources required; general-knowledge = 'general LLM knowledge'>",
      "answerability": "<full | partial | requires_extension>"
    }}
  ]
}}

RULES:
- Return exactly one result object per question, with the SAME "n" you were given.
- GENERAL-KNOWLEDGE questions (answerable by the LLM alone, no building-specific data)
  MUST get: answer_basis=general-knowledge, latent_level=1, architecture="LLM (general
  knowledge)", data_sources="general LLM knowledge",
  pipeline_stages="dialogue -> LLM answer -> response", answerability=full, and NO [NEW]
  items. Do NOT attach RAG / ontology / time-series or invent a literature corpus for a
  textbook question -- OntoSage just asks its LLM. (See worked examples D and E.)
- level (cognitive) and latent_level (architectural) are INDEPENDENT; do not copy one
  onto the other unless they genuinely coincide (see worked examples C, D).
- Know what already exists: anything in CURRENT ONTOSAGE CAPABILITIES + already-loaded
  bldg1 data is AVAILABLE -> do NOT tag it [NEW]. Tag [NEW] ONLY for the KNOWN DATA GAPS
  (sensor modalities beyond temp/CO2/humidity, live data for floors 0-4, external feeds,
  surveys, etc.), and name the extension mechanism: new data source / add to ontology+KB
  / add an inputs/ file. A question may legitimately need MULTIPLE data sources.
- NEVER say out-of-scope. Use answerability=requires_extension when any [NEW] item is
  essential (partial if it only helps; full only when nothing beyond current
  capabilities + loaded data is needed, or general-knowledge).
- Action/actuation requests are real tasks -> include the control loop in pipeline_stages.
- Be terse: short phrases, exact and concrete. Do not restate the question.
- NEVER leave architecture / parameters / pipeline_stages / data_sources empty.
- Extending Brickschema with a new class or property is allowed and preferred for human-building conversation; tag it [NEW] and say "add to ontology".
- Output JSON only."""


def build_user_prompt(chunk: List["Row"]) -> str:
    lines = [
        "Classify these smart-building questions. Each shows the asker's ROLE/persona "
        "(infer persona from phrasing if unhelpful). Return JSON only.\n"
    ]
    for i, row in enumerate(chunk, start=1):
        role = row.roles or "unspecified"
        lines.append(f'{i}. (asker role: {role}) "{row.question}"')
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Stable identifiers — how the script decides "already processed?"
# --------------------------------------------------------------------------- #
def normalize_q(question: str) -> str:
    """Canonical form of a question for content-hashing (case/space-insensitive)."""
    return re.sub(r"\s+", " ", (question or "").strip().lower())


def qid_of(question: str) -> str:
    """Content identifier: stable hash of the normalized question TEXT only.

    Two identical questions (even from different users) share one qid, so a
    --dedup run can tell a question is already in the output table by content.
    """
    return "q" + hashlib.md5(normalize_q(question).encode("utf-8")).hexdigest()[:12]


def key_of(username: str, qnum: str, question: str) -> str:
    """Per-occurrence identifier: ties a qid to who asked it and their q-number.

    Used by full (non-dedup) runs so the *same* question asked by two different
    users is still two rows, but re-running never reprocesses the same occurrence.
    """
    return f"{username}|{qnum}|{qid_of(question)}"


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class Row:
    username: str
    roles: str
    qnum: str
    stage: str
    timestamp: str
    question: str

    @property
    def qid(self) -> str:
        return qid_of(self.question)

    @property
    def key(self) -> str:
        return key_of(self.username, self.qnum, self.question)


OUTPUT_FIELDS = [
    "qid",
    "key",
    "username",
    "roles",
    "qnum",
    "stage",
    "timestamp",
    "question",
    # --- SURFACE / cognitive axis ---
    "cognitive_operation",
    "reasoning_load",
    "answer_determinacy",
    "uncertainty",
    "ambiguity",
    "level",
    "level_name",
    "why",
    # --- LATENT / architectural axis ---
    "latent_level",
    "latent_level_name",
    "latent_why",
    # --- requirements to answer it for real ---
    "answer_basis",
    "architecture",
    "parameters",
    "pipeline_stages",
    "data_sources",
    "answerability",
    "provider",
    "model",
    "classified_at",
]


# --------------------------------------------------------------------------- #
# Input loading
# --------------------------------------------------------------------------- #
def load_questions(path: Path, dedup: bool) -> List[Row]:
    rows: List[Row] = []
    seen_text: set = set()
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for rec in reader:
            q = (rec.get("Question") or "").strip()
            if not q:
                continue
            if dedup:
                norm = normalize_q(q)
                if norm in seen_text:
                    continue
                seen_text.add(norm)
            rows.append(
                Row(
                    username=(rec.get("Username") or "").strip(),
                    roles=(rec.get("Roles") or "").strip(),
                    qnum=(rec.get("QuestionNumber") or "").strip(),
                    stage=(rec.get("Stage") or "").strip(),
                    timestamp=(rec.get("Timestamp") or "").strip(),
                    question=q,
                )
            )
    return rows


def load_done_index(path: Path) -> "tuple[set, set, Optional[list]]":
    """Scan the existing output table and report what's already processed.

    Returns (done_keys, done_qids, header). Identifiers are RECOMPUTED from each
    row's stored question text, so resume works even if an older output file used
    a different column layout. ``header`` is the output's column list (or None if
    the file does not yet exist) for a schema-compatibility check.
    """
    if not path.exists():
        return set(), set(), None
    done_keys: set = set()
    done_qids: set = set()
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        for rec in reader:
            q = (rec.get("question") or "").strip()
            if not q:
                # fall back to any stored key/qid if the question text is absent
                if rec.get("key"):
                    done_keys.add(rec["key"])
                if rec.get("qid"):
                    done_qids.add(rec["qid"])
                continue
            done_qids.add(qid_of(q))
            done_keys.add(
                key_of(
                    (rec.get("username") or "").strip(),
                    (rec.get("qnum") or "").strip(),
                    q,
                )
            )
    return done_keys, done_qids, header


# --------------------------------------------------------------------------- #
# LLM providers
# --------------------------------------------------------------------------- #
class LLMError(RuntimeError):
    pass


def _strip_think(text: str) -> str:
    """deepseek-r1 and similar emit <think>...</think>; drop it."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _extract_json(text: str) -> dict:
    """Pull the first balanced {...} object out of an LLM reply."""
    text = _strip_think(text)
    text = text.strip()
    # strip ```json ... ``` fences if present
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # brace-match the first object
    start = text.find("{")
    if start == -1:
        raise LLMError("no JSON object found in model reply")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start : i + 1])
    raise LLMError("unbalanced JSON object in model reply")


def get_secret(name: str) -> Optional[str]:
    """Read an API key from the environment, falling back to a .env file.

    Searches os.environ first, then any ``.env`` found by walking up from the
    current dir and the script dir (covers the repo root). Values are never logged.
    """
    val = os.environ.get(name)
    if val:
        return val.strip()
    seen = set()
    candidates = [Path.cwd(), HERE, SURVEY_ROOT, *SURVEY_ROOT.parents, *HERE.parents]
    for base in candidates:
        envf = base / ".env"
        if envf in seen or not envf.is_file():
            seen.add(envf)
            continue
        seen.add(envf)
        for line in envf.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == name:
                return v.strip().strip('"').strip("'")
    return None


# OpenAI enforces per-minute AND daily request/token caps. On a 429 ("too many
# requests") we wait and retry. Both overridable via env.
OPENAI_RATE_WAIT = float(
    os.environ.get("OPENAI_RATE_WAIT", "15")
)  # seconds to wait on 429
OPENAI_MAX_RATE_RETRIES = int(os.environ.get("OPENAI_MAX_RATE_RETRIES", "20"))


def call_openai(system: str, user: str, model: str, temperature: float) -> str:
    """Call the OpenAI Chat Completions API via raw HTTP.

    Adaptive to reasoning models (gpt-5.x / o-series): if the API rejects an
    optional parameter (temperature / max_completion_tokens / reasoning_effort /
    response_format), that parameter is dropped (or swapped) and the call retried,
    so the same code works for both classic and reasoning models.

    Rate limits: on HTTP 429 it waits OPENAI_RATE_WAIT seconds (or the Retry-After
    header if longer) and retries, up to OPENAI_MAX_RATE_RETRIES times -- this rides
    out the per-minute cap. A 429 with code 'insufficient_quota' (billing/daily cap
    exhausted) fails fast, since waiting a few seconds will not help.
    """
    import requests

    key = get_secret("OPENAI_API_KEY")
    if not key:
        raise LLMError("OPENAI_API_KEY not found (checked environment and .env)")
    base = (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip(
        "/"
    )
    url = base + "/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload: Dict[str, object] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "max_completion_tokens": 16000,
        "reasoning_effort": "high",  # ask for the strongest reasoning; dropped if unsupported
    }
    # Up to 5 adaptive passes to shed unsupported params. A 429 (rate limit) does NOT
    # consume an adaptive pass -- it just waits and retries the same payload.
    adapt_passes = 0
    rate_retries = 0
    while adapt_passes < 5:
        resp = requests.post(url, headers=headers, json=payload, timeout=900)

        if resp.status_code == 429:
            try:
                err = resp.json().get("error", {}) or {}
            except ValueError:
                err = {}
            code = (err.get("code") or err.get("type") or "").lower()
            if "insufficient_quota" in code:
                raise LLMError(
                    "OpenAI quota exhausted (insufficient_quota / billing or daily cap). "
                    "Not retrying -- top up credits or wait for the cap to reset."
                )
            if rate_retries >= OPENAI_MAX_RATE_RETRIES:
                raise LLMError(
                    f"OpenAI rate limit (429) still hit after {rate_retries} waits; giving up."
                )
            rate_retries += 1
            try:
                retry_after = float(resp.headers.get("retry-after", "") or 0)
            except ValueError:
                retry_after = 0.0
            wait = max(OPENAI_RATE_WAIT, retry_after)
            sys.stderr.write(
                f"  ! OpenAI 429 too-many-requests "
                f"(retry {rate_retries}/{OPENAI_MAX_RATE_RETRIES}); waiting {wait:.0f}s...\n"
            )
            time.sleep(wait)
            continue  # retry same payload; does NOT count as an adaptive pass

        if resp.status_code == 400:
            try:
                err = resp.json().get("error", {}) or {}
            except ValueError:
                err = {}
            msg = (err.get("message") or "").lower()
            param = err.get("param") or ""
            dropped = False
            for cand in (
                "reasoning_effort",
                "response_format",
                "temperature",
                "max_completion_tokens",
            ):
                if cand in payload and (cand == param or cand in msg):
                    payload.pop(cand, None)
                    if cand == "max_completion_tokens":
                        payload["max_tokens"] = 16000  # older models use this name
                    dropped = True
                    break
            if dropped:
                adapt_passes += 1
                continue

        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"OpenAI returned no choices: {str(data)[:200]}")
        return choices[0].get("message", {}).get("content", "") or ""
    raise LLMError("OpenAI request failed after adapting parameters")


def call_claude(system: str, user: str, model: str, temperature: float) -> str:
    try:
        import anthropic  # noqa: WPS433 (local import — optional dependency)
    except ImportError as exc:  # pragma: no cover
        raise LLMError(
            "anthropic SDK not installed. Run: pip install anthropic"
        ) from exc
    api_key = get_secret("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY not found (checked environment and .env)")
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(
        block.text for block in resp.content if getattr(block, "type", "") == "text"
    )


def call_ollama(
    system: str, user: str, model: str, temperature: float, base_url: str
) -> str:
    import requests  # available per repo env

    url = base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {"temperature": temperature, "num_ctx": 8192},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    resp = requests.post(url, json=payload, timeout=600)
    resp.raise_for_status()
    data = resp.json()
    return data.get("message", {}).get("content", "")


def call_llm(
    provider: str, system: str, user: str, model: str, temperature: float, base_url: str
) -> str:
    if provider == "anthropic":
        return call_claude(system, user, model, temperature)
    if provider == "openai":
        return call_openai(system, user, model, temperature)
    if provider == "ollama":
        return call_ollama(system, user, model, temperature, base_url)
    raise LLMError(f"unknown provider: {provider}")


# --------------------------------------------------------------------------- #
# Chunk classification with retry
# --------------------------------------------------------------------------- #
def classify_chunk(
    chunk: List[Row],
    provider: str,
    model: str,
    temperature: float,
    base_url: str,
    max_retries: int,
) -> Dict[int, dict]:
    """Return {n: result_dict} for the chunk; raises after exhausting retries."""
    user = build_user_prompt(chunk)
    last_err: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            raw = call_llm(provider, SYSTEM_PROMPT, user, model, temperature, base_url)
            parsed = _extract_json(raw)
            results = parsed.get("results")
            if not isinstance(results, list) or not results:
                raise LLMError("reply missing non-empty 'results' array")
            by_n: Dict[int, dict] = {}
            for item in results:
                try:
                    n = int(item.get("n"))
                except (TypeError, ValueError):
                    continue
                by_n[n] = item
            # require coverage of every question in the chunk
            missing = [i for i in range(1, len(chunk) + 1) if i not in by_n]
            if missing:
                raise LLMError(f"missing results for indices {missing}")
            return by_n
        except Exception as exc:  # noqa: BLE001 — retry on anything transient
            last_err = exc
            wait = min(2**attempt, 30)
            sys.stderr.write(
                f"  ! attempt {attempt}/{max_retries} failed: {exc} "
                f"(retry in {wait}s)\n"
            )
            time.sleep(wait)
    raise LLMError(f"chunk failed after {max_retries} attempts: {last_err}")


def _clean(val: object, limit: int = 1000) -> str:
    s = "" if val is None else str(val)
    s = s.replace("\r", " ").replace("\n", " ").strip()
    return s[:limit]


def result_to_record(row: Row, res: dict, provider: str, model: str) -> Dict[str, str]:
    return {
        "qid": row.qid,
        "key": row.key,
        "username": row.username,
        "roles": row.roles,
        "qnum": row.qnum,
        "stage": row.stage,
        "timestamp": row.timestamp,
        "question": row.question,
        "cognitive_operation": _clean(res.get("cognitive_operation"), 40),
        "reasoning_load": _clean(res.get("reasoning_load"), 20),
        "answer_determinacy": _clean(res.get("answer_determinacy"), 40),
        "uncertainty": _clean(res.get("uncertainty"), 20),
        "ambiguity": _clean(res.get("ambiguity"), 20),
        "level": _clean(res.get("level"), 8),
        "level_name": _clean(res.get("level_name"), 60),
        "why": _clean(res.get("why"), 240),
        "latent_level": _clean(res.get("latent_level"), 8),
        "latent_level_name": _clean(res.get("latent_level_name"), 60),
        "latent_why": _clean(res.get("latent_why"), 200),
        "answer_basis": _clean(res.get("answer_basis"), 24),
        "architecture": _clean(res.get("architecture")),
        "parameters": _clean(res.get("parameters")),
        "pipeline_stages": _clean(res.get("pipeline_stages"), 300),
        "data_sources": _clean(res.get("data_sources"), 300),
        "answerability": _clean(res.get("answerability"), 20),
        "provider": provider,
        "model": model,
        "classified_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    p = argparse.ArgumentParser(
        description="Build the 6-level complexity master table from survey questions.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--provider",
        choices=["anthropic", "claude", "openai", "gpt", "ollama"],
        default="ollama",
        help="LLM backend. 'claude'==anthropic, 'gpt'==openai. Keys read from env or .env.",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Model id. Default per provider: claude-opus-4-8 (anthropic) / "
        "gpt-5.5 (openai) / deepseek-r1:32b (ollama).",
    )
    p.add_argument(
        "--base-url", default="http://localhost:11434", help="Ollama base URL."
    )
    p.add_argument(
        "--chunk-size",
        type=int,
        default=5,
        help="Questions per LLM call / per turn (clamped to 1-5).",
    )
    p.add_argument(
        "--turns",
        type=int,
        default=0,
        help="Process only the first N turns (LLM calls) THIS run, then stop. "
        "0 = all. e.g. --turns 1 runs a single turn. Resumable: re-run to continue.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only process the first N questions (0 = all).",
    )
    p.add_argument("--start", type=int, default=0, help="Skip the first N questions.")
    p.add_argument(
        "--dedup", action="store_true", help="Process each unique question text once."
    )
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--max-retries", type=int, default=4)
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = p.parse_args()

    chunk_size = max(1, min(5, args.chunk_size))
    # Normalize aliases ('claude'->anthropic, 'gpt'->openai) so the stored provider
    # value is canonical.
    _alias = {
        "claude": "anthropic",
        "anthropic": "anthropic",
        "gpt": "openai",
        "openai": "openai",
        "ollama": "ollama",
    }
    provider = _alias[args.provider]
    _default_model = {
        "anthropic": "claude-opus-4-8",
        "openai": "gpt-5.5",
        "ollama": "deepseek-r1:32b",
    }
    model = args.model or _default_model[provider]

    if not args.input.exists():
        sys.stderr.write(f"ERROR: input not found: {args.input}\n")
        return 2

    rows = load_questions(args.input, dedup=args.dedup)
    if args.start:
        rows = rows[args.start :]
    if args.limit:
        rows = rows[: args.limit]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    done_keys, done_qids, header = load_done_index(args.output)

    # Schema guard: refuse to append rows that would misalign with an existing
    # output written under a different column layout.
    if header is not None and header != OUTPUT_FIELDS:
        sys.stderr.write(
            "ERROR: existing output has an incompatible column layout.\n"
            f"  output : {args.output}\n"
            "  Its header does not match this script's columns. Either point\n"
            "  --output at a new file, or remove/rename the old one, then rerun.\n"
        )
        return 3

    # Decide 'already processed?' by CONTENT in --dedup mode (qid), or by the
    # exact occurrence in a full run (key). Either way, re-runs never reprocess.
    if args.dedup:
        pending = [r for r in rows if r.qid not in done_qids]
    else:
        pending = [r for r in rows if r.key not in done_keys]
    skipped_done = len(rows) - len(pending)

    remaining_after = 0
    if args.turns and args.turns > 0:
        cap = args.turns * chunk_size
        remaining_after = max(0, len(pending) - cap)
        pending = pending[:cap]

    turns_note = (
        f" turns={args.turns} (this run: <= {len(pending)} q; "
        f"{remaining_after} q left after)"
        if args.turns
        else ""
    )
    print(
        f"provider={provider} model={model} chunk={chunk_size} "
        f"skip-by={'qid (content)' if args.dedup else 'key (occurrence)'}{turns_note}\n"
        f"input={args.input}\noutput={args.output}\n"
        f"loaded={len(rows)} already_in_table={skipped_done} pending_this_run={len(pending)}"
    )
    if not pending:
        print("Nothing to do — every input question is already in the output table.")
        return 0

    new_file = not args.output.exists()
    processed = 0
    failed_chunks = 0
    try:
        with args.output.open("a", encoding="utf-8", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=OUTPUT_FIELDS)
            if new_file:
                writer.writeheader()
                out.flush()

            total_chunks = (len(pending) + chunk_size - 1) // chunk_size
            for ci in range(0, len(pending), chunk_size):
                chunk = pending[ci : ci + chunk_size]
                idx = ci // chunk_size + 1
                t0 = time.time()
                try:
                    by_n = classify_chunk(
                        chunk,
                        provider,
                        model,
                        args.temperature,
                        args.base_url,
                        args.max_retries,
                    )
                except LLMError as exc:
                    failed_chunks += 1
                    sys.stderr.write(f"[chunk {idx}/{total_chunks}] SKIPPED: {exc}\n")
                    continue
                for i, row in enumerate(chunk, start=1):
                    writer.writerow(result_to_record(row, by_n[i], provider, model))
                out.flush()
                processed += len(chunk)
                dt = time.time() - t0
                print(
                    f"[chunk {idx}/{total_chunks}] +{len(chunk)} "
                    f"({processed}/{len(pending)}) {dt:.1f}s  "
                    f"e.g. L{_clean(by_n[1].get('level'),2)}"
                    f"/lat{_clean(by_n[1].get('latent_level'),2)} "
                    f'"{chunk[0].question[:55]}"'
                )
    except KeyboardInterrupt:
        print(f"\nInterrupted. Progress saved to {args.output} ({processed} new rows).")
        return 130

    print(
        f"\nDone. wrote {processed} new rows; {failed_chunks} chunk(s) skipped.\n"
        f"Master table: {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ============================================================================ #
# HOW TO USE THIS SCRIPT  (PowerShell, run from the repo ROOT)
# ============================================================================ #
#
# The folder name "Survey analysis and results" has SPACES, so an unquoted path
# breaks ( "...\paper\Survey" : No such file ). Two fixes -- always quote the path,
# or set a variable once. The script resolves its input/output from its OWN folder
# (via __file__), so it does NOT matter which directory you launch it from.
#
#   PS C:\Users\suhas\Documents\GitHub\OntoSage>     # <- run from here (repo root)
#   $J = "paper/Survey analysis and results/scripts/J_complexity_master_table.py"
#   python $J --provider openai --model gpt-5.5 --dedup --turns 1
#
# (or, without the variable, just quote it:)
#   python "paper/Survey analysis and results/scripts/J_complexity_master_table.py" --provider openai --model gpt-5.5 --dedup --turns 1
#
# PROVIDERS & API KEYS
# --------------------
# Three backends, chosen with --provider:
#   openai     (aliases: gpt)     default model gpt-5.5      -> best reasoning, paid
#   anthropic  (aliases: claude)  default model claude-opus-4-8
#   ollama                        default model deepseek-r1:32b  -> local, free, slower
# API keys are read from the ENVIRONMENT first, then from a .env file found by walking
# up from the repo root (so .env at the repo root just works). Keys are never printed.
#   .env lines expected:   OPENAI_API_KEY=sk-...      ANTHROPIC_API_KEY=sk-ant-...
#   (override the OpenAI endpoint with OPENAI_BASE_URL if you use a proxy/Azure gateway)
# OpenAI reasoning models: the script auto-sends reasoning_effort=high and
# max_completion_tokens, and silently drops any param a given model rejects -- so
# gpt-5.5 / o-series / classic models all work without code changes. --temperature is
# ignored by OpenAI reasoning models (they run at their own default), which is fine.
#
# RESUMABILITY / SKIPPING (important)
# -----------------------------------
# Every output row carries two identifiers:
#   * qid  = "q" + md5(normalised question text)[:12]  -> CONTENT identity
#   * key  = "<username>|<qnum>|<qid>"                  -> per-OCCURRENCE identity
# On startup the script reads the existing --output table, recomputes these from
# each stored question, and SKIPS anything already present. So you can stop any
# time (Ctrl-C is safe — each turn is flushed) and just rerun to continue.
#   * with --dedup : a question is "done" if its qid is in the table (by content;
#                    the same question from another user is skipped too).
#   * without --dedup : "done" is judged per occurrence (key), so the same text
#                    asked by two different users is still two rows.
# Mixing modes is fine; pick one per output file. The script refuses to append to
# an output whose column layout differs from the current schema (use a new
# --output or remove the old file).
#
# All examples below assume:  $J = "paper/Survey analysis and results/scripts/J_complexity_master_table.py"
# (swap --provider/--model freely; openai gpt-5.5 = best reasoning, ollama = free/local)
#
# 1) FIRST / SINGLE TURN (one LLM call, <=5 questions) — inspect the first output:
#       python $J --provider openai --model gpt-5.5 --dedup --turns 1
#
# 2) A FEW TURNS (e.g. 10 calls = 50 questions) then stop — rerun to continue:
#       python $J --provider openai --model gpt-5.5 --dedup --turns 10
#
# 3) FULL CORPUS (all remaining questions; resumes across runs):
#       python $J --provider openai --model gpt-5.5 --dedup
#
# 4) QUICK / CHEAP SMOKE TEST on a local model first:
#       python $J --provider ollama --model gpt-oss:20b --dedup --limit 20
#
# 5) RUN A SPECIFIC SLICE (skip the first 100, do the next 25):
#       python $J --provider openai --model gpt-5.5 --dedup --start 100 --limit 25
#
# 6) USE ANTHROPIC CLAUDE  (--provider claude == anthropic):
#       pip install anthropic        # key from .env -> ANTHROPIC_API_KEY
#       python $J --provider anthropic --model claude-opus-4-8 --dedup
#
# 7) USE A LOCAL OLLAMA MODEL / DIFFERENT HOST:
#       python $J --provider ollama --model deepseek-r1:32b --base-url http://localhost:11434 --dedup
#
# 8) COMPARE TWO MODELS SIDE BY SIDE (write to separate tables):
#       python $J --provider openai --model gpt-5.5 --dedup --output "paper/Survey analysis and results/outputs/tables/complexity_gpt55.csv"
#       python $J --provider ollama --model gpt-oss:20b --dedup --output "paper/Survey analysis and results/outputs/tables/complexity_gptoss.csv"
#
# NOTE: --input / --output default to the script's own folder, so you usually omit
# them. If you DO pass them from the repo root, quote them (they contain spaces):
#       --output "paper/Survey analysis and results/outputs/tables/my_table.csv"
#
# COST / SPEED (rough, ~5.7k unique questions at chunk-size 5 = ~1,135 calls):
#   openai gpt-5.5  : deepest reasoning, ~30-160s/turn, paid per token -> budget for it;
#                     start with --turns to sample, then let it run (resumable).
#   ollama (local)  : free, similar wall-clock, lower reasoning quality.
#   Always validate with --turns 1 (or --limit 20 on ollama) before a full paid run.
#
# KEY FLAGS
#   --provider {openai|gpt|anthropic|claude|ollama}  backend (default: ollama)
#   --model NAME                model id (per-provider default if omitted)
#   --base-url URL              Ollama host           (default: localhost:11434)
#                               (OpenAI endpoint: set env OPENAI_BASE_URL if needed)
#   --chunk-size N              questions per call/turn, clamped 1..5  (default: 5)
#   --turns N                   process only N turns this run, then stop (0 = all)
#   --limit N                   only the first N input questions        (0 = all)
#   --start N                   skip the first N input questions        (default: 0)
#   --dedup                     collapse identical question text to one row
#   --temperature F             sampling temp (ignored by OpenAI reasoning models)
#   --max-retries N             retries per chunk on bad/short JSON     (default: 4)
#   --input PATH                input CSV  (default: inputs/questions_by_user.csv)
#   --output PATH              output CSV (default: outputs/tables/complexity_master_table.csv)
# ============================================================================ #
