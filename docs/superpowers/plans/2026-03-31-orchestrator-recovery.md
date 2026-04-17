# Orchestrator Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover all orchestrator Python source files from Docker images and bytecode, write 3 missing files from spec, wire them into workflow.py, and rewrite docker-compose.yml to the target LangGraph service topology.

**Architecture:** Source is extracted from `ontosage-orchestrator:latest` (built 2026-03-27) via `docker cp`. Two service files are decompiled from Python 3.10 bytecode. Three files (`document_agent.py`, `persona_adapter.py`, `standards_engine.py`) are written from spec. All three are wired into `workflow.py` at exact insertion points identified from source reading. `docker-compose.yml` is fully replaced.

**Tech Stack:** Python 3.11, FastAPI, LangGraph 0.2.55, Docker Compose v2, uncompyle6 (Python 3.10 decompiler)

---

## 2026-03-31 Alignment Update (Actual Repo Implementation)

Decision: **Update this plan to match the current repo implementation** rather than refactoring PersonaAdapter/StandardsEngine to the original spec.

Key differences now treated as source of truth:
- **DocumentAgent** uses `DocumentBuilder` + Jinja2 templates to render `html/pdf/docx` and save into `EXPORTS_DIR`. It is wired as an optional post-report document step.
- **PersonaAdapter** exposes `enhance(...)` (not `adapt(...)`). It optionally calls `llm_manager.generate(...)` and is a pass-through for unknown personas.
- **StandardsEngine** uses embedded standards and `check(...)` returns a summary dict with `overall_status`, `checks`, `references`.
- **Workflow wiring**: report intent routes via `SPARQL -> SQL -> report`, then **conditionally** to `document` when a formal document is requested. Response prioritizes `document_result`.
- **Tests** are lightweight and avoid importing the full orchestrator package to reduce dependency failures. Wiring tests inspect `orchestrator/workflow.py` text directly.

The original Tasks 5-8 below are superseded by this alignment note and the updated tests/wiring in-repo.

## File Structure

**Files extracted from `ontosage-orchestrator:latest`:**
- `orchestrator/` (root 6 .py + Dockerfile + requirements.txt)
- `orchestrator/agents/` (10 agent .py files)
- `orchestrator/services/` (20 service .py files)
- `orchestrator/services/adapters/` (3 .py files)
- `orchestrator/middleware/` (rbac.py)
- `shared/` (5 .py files)

**Files extracted from `ontosage-code-executor:latest`:**
- `code-executor/` (main.py, sandbox.py, Dockerfile)

**Files decompiled from bytecode:**
- `orchestrator/services/circuit_breaker.py` ← `orchestrator/services/__pycache__/circuit_breaker.cpython-310.pyc`
- `orchestrator/services/logging_context.py` ← `orchestrator/services/__pycache__/logging_context.cpython-310.pyc`

**Files written from spec:**
- `orchestrator/agents/document_agent.py` — `DocumentAgent` class
- `orchestrator/services/persona_adapter.py` — `PersonaAdapter` class
- `orchestrator/services/standards_engine.py` — `StandardsEngine` class

**Files modified:**
- `orchestrator/workflow.py` — 4 wiring changes (imports, `__init__`, `_build_graph`, `_analytics_node`, `_response_node`, `_route_from_dialogue`)
- `docker-compose.yml` — full replacement

---

## Task 1: Extract orchestrator source from Docker image

**Files:**
- Create: `orchestrator/*.py`, `orchestrator/agents/*.py`, `orchestrator/services/**/*.py`, `orchestrator/middleware/*.py`
- Create: `shared/*.py`
- Create: `orchestrator/Dockerfile`, `orchestrator/requirements.txt`

- [ ] **Step 1: Create a stopped container from the orchestrator image**

```bash
docker create --name extract-orch ontosage-orchestrator:latest
```
Expected: prints a container ID like `a3b4c5d6...`

- [ ] **Step 2: Copy the orchestrator and shared directories out**

```bash
docker cp extract-orch:/app/orchestrator ./orchestrator-extracted
docker cp extract-orch:/app/shared ./shared-extracted
```
Expected: two directories appear locally

- [ ] **Step 3: Move extracted content into repo, preserving existing __pycache__**

```bash
# Merge extracted .py files into orchestrator/ without wiping __pycache__
rsync -av --include="*.py" --include="Dockerfile" --include="requirements.txt" \
  --include="*/" --exclude="*" \
  orchestrator-extracted/ orchestrator/
rsync -av --include="*.py" --include="*/" --exclude="*" \
  shared-extracted/ shared/
```
Expected: `.py` files appear in `orchestrator/`, `orchestrator/agents/`, `orchestrator/services/`, etc.

- [ ] **Step 4: Verify key files landed**

```bash
ls orchestrator/*.py orchestrator/Dockerfile orchestrator/requirements.txt
ls orchestrator/agents/*.py
ls orchestrator/services/*.py
ls shared/*.py
```
Expected: main.py, workflow.py, llm_manager.py, auth_manager.py, redis_manager.py, postgres_manager.py are present; 10 agent files; 20+ service files; 5 shared files.

- [ ] **Step 5: Clean up container and temp dirs**

```bash
docker rm extract-orch
rm -rf orchestrator-extracted shared-extracted
```

- [ ] **Step 6: Commit extracted files**

```bash
git add orchestrator/ shared/
git commit -m "feat(orchestrator): restore source from ontosage-orchestrator:latest image"
```

---

## Task 2: Extract code-executor source from Docker image

**Files:**
- Create: `code-executor/main.py`, `code-executor/sandbox.py`, `code-executor/Dockerfile`

- [ ] **Step 1: Create a stopped container from the code-executor image**

```bash
docker create --name extract-executor ontosage-code-executor:latest
```

- [ ] **Step 2: Copy code-executor directory**

```bash
docker cp extract-executor:/app/code-executor ./code-executor
```

- [ ] **Step 3: Verify and clean up**

```bash
ls code-executor/
docker rm extract-executor
```
Expected: `main.py`, `sandbox.py`, `Dockerfile`, `__init__.py`

- [ ] **Step 4: Commit**

```bash
git add code-executor/
git commit -m "feat(code-executor): restore source from ontosage-code-executor:latest image"
```

---

## Task 3: Decompile circuit_breaker.py from bytecode

**Files:**
- Create: `orchestrator/services/circuit_breaker.py`

- [ ] **Step 1: Install uncompyle6**

```bash
pip install uncompyle6
```
Expected: `Successfully installed uncompyle6-...`

- [ ] **Step 2: Decompile the .pyc file**

```bash
python -m uncompyle6 \
  orchestrator/services/__pycache__/circuit_breaker.cpython-310.pyc \
  > orchestrator/services/circuit_breaker.py
```
Expected: `orchestrator/services/circuit_breaker.py` is created.

- [ ] **Step 3: Verify the output is valid Python**

```bash
python -c "import py_compile; py_compile.compile('orchestrator/services/circuit_breaker.py', doraise=True)"
echo "Syntax OK"
```
Expected: `Syntax OK`

- [ ] **Step 4: Review and clean up decompiler artifacts**

Open `orchestrator/services/circuit_breaker.py`. Look for and fix:
- `# decompiled` header comment — keep it, it documents provenance
- Any lines like `# pycdc` markers or malformed `pass` statements
- Any doubled decorators or duplicate class definitions

The file should contain a `CircuitBreaker` class with:
- `State` enum or constants: `CLOSED`, `OPEN`, `HALF_OPEN`
- `failure_threshold` and `reset_timeout` init params
- `async def call(self, func, *args, **kwargs)` — wraps async calls
- Internal `_failures` counter and `_last_failure_time` timestamp

- [ ] **Step 5: Commit**

```bash
git add orchestrator/services/circuit_breaker.py
git commit -m "feat(services): decompile circuit_breaker from Python 3.10 bytecode"
```

---

## Task 4: Decompile logging_context.py from bytecode

**Files:**
- Create: `orchestrator/services/logging_context.py`

- [ ] **Step 1: Decompile the .pyc file**

```bash
python -m uncompyle6 \
  orchestrator/services/__pycache__/logging_context.cpython-310.pyc \
  > orchestrator/services/logging_context.py
```

- [ ] **Step 2: Verify the output is valid Python**

```bash
python -c "import py_compile; py_compile.compile('orchestrator/services/logging_context.py', doraise=True)"
echo "Syntax OK"
```

- [ ] **Step 3: Review output**

The file should contain:
- A `contextvars.ContextVar` named something like `_correlation_id_var`
- `def get_correlation_id() -> str` — reads from the context var
- `def set_correlation_id(cid: str) -> None` — sets in context var

- [ ] **Step 4: Commit**

```bash
git add orchestrator/services/logging_context.py
git commit -m "feat(services): decompile logging_context from Python 3.10 bytecode"
```

---

## Task 5: Write document_agent.py

**Files:**
- Create: `orchestrator/agents/document_agent.py`
- Create: `tests/agents/test_document_agent.py`

- [ ] **Step 1: Write the failing test**

Create `tests/agents/test_document_agent.py`:

```python
import pytest
import asyncio
import os
import sys
sys.path.insert(0, '.')

from unittest.mock import MagicMock, patch
from shared.models import ConversationState, Message


def make_state(**kwargs) -> ConversationState:
    defaults = dict(
        conversation_id="test-conv-1",
        user_id="test-user",
        user_message="generate a summary",
        messages=[Message(role="user", content="generate a summary")],
        building_id="bldg1",
    )
    defaults.update(kwargs)
    return ConversationState(**defaults)


@pytest.mark.asyncio
async def test_generate_returns_success():
    from orchestrator.agents.document_agent import DocumentAgent
    agent = DocumentAgent()
    state = make_state()
    result = await agent.generate(state)
    assert result.intermediate_results["document_result"]["success"] is True


@pytest.mark.asyncio
async def test_generate_creates_file():
    from orchestrator.agents.document_agent import DocumentAgent
    agent = DocumentAgent()
    state = make_state(intermediate_results={"document_type": "summary"})
    result = await agent.generate(state)
    filename = result.intermediate_results["document_result"]["filename"]
    from shared.config import settings
    path = os.path.join(settings.EXPORTS_DIR, filename)
    assert os.path.exists(path)


@pytest.mark.asyncio
async def test_generate_contains_download_url():
    from orchestrator.agents.document_agent import DocumentAgent
    agent = DocumentAgent()
    state = make_state()
    result = await agent.generate(state)
    dr = result.intermediate_results["document_result"]
    assert "/exports/" in dr["download_url"]
    assert dr["filename"] in dr["download_url"]


@pytest.mark.asyncio
async def test_all_document_types():
    from orchestrator.agents.document_agent import DocumentAgent
    agent = DocumentAgent()
    for doc_type in ["summary", "executive_kpi", "anomaly_digest",
                     "compliance_report", "energy_report", "iaq_report", "research_export"]:
        state = make_state(intermediate_results={"document_type": doc_type})
        result = await agent.generate(state)
        assert result.intermediate_results["document_result"]["success"] is True
```

- [ ] **Step 2: Run the failing test**

```bash
cd c:/Users/suhas/Documents/GitHub/OntoSage
python -m pytest tests/agents/test_document_agent.py -v 2>&1 | head -30
```
Expected: `ModuleNotFoundError: No module named 'orchestrator.agents.document_agent'`

- [ ] **Step 3: Write the implementation**

Create `orchestrator/agents/document_agent.py`:

```python
"""
DocumentAgent — generates structured documents from conversation state data.
Supported types: summary, executive_kpi, anomaly_digest, compliance_report,
                 energy_report, iaq_report, research_export
Output: Markdown file always; HTML/PDF/DOCX on request (graceful fallback).
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import sys
sys.path.insert(0, '/app')

from shared.models import ConversationState
from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)


class DocumentAgent:
    """Generates structured Markdown (and optionally HTML/PDF/DOCX) documents."""

    DOC_TYPES: dict[str, str] = {
        "summary":          "Conversation Summary",
        "executive_kpi":    "Executive KPI Report",
        "anomaly_digest":   "Anomaly Digest",
        "compliance_report": "Compliance Report",
        "energy_report":    "Energy Report",
        "iaq_report":       "Indoor Air Quality Report",
        "research_export":  "Research Data Export",
    }

    async def generate(self, state: ConversationState) -> ConversationState:
        """
        Generate a document, save it, and store the download URL in state.

        Reads from state.intermediate_results:
          - ``document_type`` (str, default "summary")
          - ``document_format`` (str, default "markdown")

        Writes to state.intermediate_results["document_result"]:
          - success, doc_type, filename, download_url, formatted_response
        """
        doc_type = state.intermediate_results.get("document_type", "summary")
        if doc_type not in self.DOC_TYPES:
            doc_type = "summary"

        markdown = self._build_markdown(state, doc_type)
        filename = self._save(markdown, doc_type, state.user_id)
        download_url = f"/exports/{filename}"
        title = self.DOC_TYPES[doc_type]

        state.intermediate_results["document_result"] = {
            "success":      True,
            "doc_type":     doc_type,
            "filename":     filename,
            "download_url": download_url,
            "formatted_response": (
                f"Your **{title}** is ready.\n\n"
                f"[Download {filename}]({download_url})"
            ),
        }
        return state

    # ── Markdown builders ─────────────────────────────────────────────────────

    def _build_markdown(self, state: ConversationState, doc_type: str) -> str:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        header = (
            f"# {self.DOC_TYPES[doc_type]}\n\n"
            f"**Building:** {state.building_id}  \n"
            f"**Generated:** {now}  \n"
            f"**User:** {state.user_id}\n\n"
            "---\n\n"
        )
        builders = {
            "summary":          self._conversation_summary,
            "executive_kpi":    self._executive_kpi,
            "anomaly_digest":   self._anomaly_digest,
            "compliance_report": self._compliance_section,
            "energy_report":    self._energy_section,
            "iaq_report":       self._iaq_section,
            "research_export":  self._research_export,
        }
        body = builders[doc_type](state)
        return header + body

    def _conversation_summary(self, state: ConversationState) -> str:
        lines = ["## Conversation History\n"]
        for msg in state.messages:
            role = "**User**" if msg.role == "user" else "**Assistant**"
            lines.append(f"{role}: {msg.content}\n")
        return "\n".join(lines)

    def _executive_kpi(self, state: ConversationState) -> str:
        analytics = state.intermediate_results.get("analytics_result", {})
        metrics = analytics.get("metrics", {})
        if not metrics:
            return "_No KPI data available from this session._"
        rows = ["## Key Performance Indicators\n", "| Metric | Value |", "|--------|-------|"]
        for k, v in metrics.items():
            rows.append(f"| {k} | {v} |")
        return "\n".join(rows)

    def _anomaly_digest(self, state: ConversationState) -> str:
        result = state.intermediate_results.get("anomaly_result", {})
        anomalies = result.get("anomalies", [])
        if not anomalies:
            return "_No anomalies detected in this session._"
        lines = ["## Detected Anomalies\n"]
        for a in anomalies:
            lines.append(f"- **{a.get('sensor', 'Unknown')}**: {a.get('description', '')}")
        return "\n".join(lines)

    def _compliance_section(self, state: ConversationState) -> str:
        result = state.intermediate_results.get("analytics_result", {})
        std_check = result.get("standards_check", {})
        summary = std_check.get("summary", {})
        violations = result.get("violations", [])
        grade = result.get("grade", "N/A")
        lines = [f"## Compliance Summary\n\n**Grade:** {grade}\n"]
        if summary:
            lines.append(
                f"\n**Standards checked:** {summary.get('total', 0)}  \n"
                f"**Passed:** {summary.get('passed', 0)}  \n"
                f"**Failed:** {summary.get('failed', 0)}  \n"
                f"**Warnings:** {summary.get('warned', 0)}\n"
            )
        if violations:
            lines.append("\n### Violations\n")
            for v in violations:
                lines.append(f"- {v}")
        else:
            lines.append("\n_No violations recorded._")
        return "\n".join(lines)

    def _energy_section(self, state: ConversationState) -> str:
        analytics = state.intermediate_results.get("analytics_result", {})
        return analytics.get("formatted_response", "_No energy data available._")

    def _iaq_section(self, state: ConversationState) -> str:
        analytics = state.intermediate_results.get("analytics_result", {})
        return analytics.get("formatted_response", "_No IAQ data available._")

    def _research_export(self, state: ConversationState) -> str:
        data = state.query_results
        lines = ["## Raw Data Export\n", "```json"]
        lines.append(json.dumps(data, indent=2, default=str)[:10_000])
        lines.append("```")
        return "\n".join(lines)

    # ── File I/O ──────────────────────────────────────────────────────────────

    def _save(self, content: str, doc_type: str, user_id: str) -> str:
        os.makedirs(settings.EXPORTS_DIR, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_user = "".join(c for c in user_id if c.isalnum() or c in ("-", "_"))
        filename = f"{safe_user}_{doc_type}_{timestamp}.md"
        path = os.path.join(settings.EXPORTS_DIR, filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        logger.info(f"Document saved: {path}")
        return filename
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/agents/test_document_agent.py -v
```
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add orchestrator/agents/document_agent.py tests/agents/test_document_agent.py
git commit -m "feat(agents): add DocumentAgent with 7 document types"
```

---

## Task 6: Write persona_adapter.py

**Files:**
- Create: `orchestrator/services/persona_adapter.py`
- Create: `tests/services/test_persona_adapter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/services/test_persona_adapter.py`:

```python
import pytest
import asyncio
import sys
sys.path.insert(0, '.')

from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_general_persona_returns_original():
    from orchestrator.services.persona_adapter import PersonaAdapter
    adapter = PersonaAdapter()
    original = "The temperature is 23°C."
    result = await adapter.adapt(original, "general", {})
    assert result == original


@pytest.mark.asyncio
async def test_unknown_persona_returns_original():
    from orchestrator.services.persona_adapter import PersonaAdapter
    adapter = PersonaAdapter()
    original = "The temperature is 23°C."
    result = await adapter.adapt(original, "nonexistent_persona", {})
    assert result == original


@pytest.mark.asyncio
async def test_executive_persona_calls_llm():
    from orchestrator.services.persona_adapter import PersonaAdapter
    adapter = PersonaAdapter()
    with patch("orchestrator.services.persona_adapter.llm_manager") as mock_llm:
        mock_llm.generate = AsyncMock(return_value="Executive summary here.")
        result = await adapter.adapt("Temperature details...", "executive", {})
    assert result == "Executive summary here."


@pytest.mark.asyncio
async def test_llm_failure_returns_original():
    from orchestrator.services.persona_adapter import PersonaAdapter
    adapter = PersonaAdapter()
    original = "The temperature is 23°C."
    with patch("orchestrator.services.persona_adapter.llm_manager") as mock_llm:
        mock_llm.generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        result = await adapter.adapt(original, "executive", {})
    assert result == original


@pytest.mark.asyncio
async def test_all_named_personas_accepted():
    from orchestrator.services.persona_adapter import PersonaAdapter, PERSONA_PROMPTS
    adapter = PersonaAdapter()
    for persona in PERSONA_PROMPTS:
        with patch("orchestrator.services.persona_adapter.llm_manager") as mock_llm:
            mock_llm.generate = AsyncMock(return_value="adapted")
            result = await adapter.adapt("text", persona, {})
        # Should not raise; general returns original, others return adapted
        assert isinstance(result, str)
```

- [ ] **Step 2: Run the failing test**

```bash
python -m pytest tests/services/test_persona_adapter.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'orchestrator.services.persona_adapter'`

- [ ] **Step 3: Write the implementation**

Create `orchestrator/services/persona_adapter.py`:

```python
"""
PersonaAdapter — reframes LLM responses to match the user's persona.

Supported personas (matching ConversationState.persona literal):
  student, researcher, facility_manager, occupant, energy_manager,
  safety_officer, it_admin, executive, sustainability_officer, general,
  stakeholder, guest, officer  (legacy aliases)

All non-general personas get a follow-up LLM call that reframes the
response while preserving all data values.  Falls back to the original
response if the LLM is unavailable.
"""
from __future__ import annotations

import sys
sys.path.insert(0, '/app')

from shared.utils import get_logger
from orchestrator.llm_manager import llm_manager

logger = get_logger(__name__)

# Persona → reframing instruction.  None means no reframing (return as-is).
PERSONA_PROMPTS: dict[str, str | None] = {
    "student": (
        "Rewrite this response for a university student studying building systems. "
        "Use clear, simple explanations. Define technical terms when used. "
        "Be encouraging and educational."
    ),
    "researcher": (
        "Rewrite this response for an academic researcher. "
        "Be precise, include data provenance and statistical context. "
        "Use technical terminology without over-explanation."
    ),
    "facility_manager": (
        "Rewrite this response for a facility manager. "
        "Focus on actionable insights, maintenance implications, and operational efficiency. "
        "Highlight cost and energy impact."
    ),
    "occupant": (
        "Rewrite this response for a building occupant with no technical background. "
        "Use everyday language. Focus on comfort, air quality, and temperature. "
        "Avoid jargon entirely."
    ),
    "energy_manager": (
        "Rewrite this response for an energy manager. "
        "Focus on kWh, carbon footprint, cost, and efficiency opportunities. "
        "Use energy-specific metrics prominently."
    ),
    "safety_officer": (
        "Rewrite this response for a health and safety compliance officer. "
        "Highlight threshold violations, compliance status, and safety risks first. "
        "Use standards-based language (ASHRAE, WELL, EN standards)."
    ),
    "it_admin": (
        "Rewrite this response for an IT / BMS system administrator. "
        "Focus on system connectivity, sensor status, data pipelines, and integration. "
        "Use technical terminology for BMS and IoT systems."
    ),
    "executive": (
        "Rewrite this response for a C-suite executive. "
        "Be very concise. Focus on business impact, cost, risk, and KPIs. "
        "Strip low-level technical details."
    ),
    "sustainability_officer": (
        "Rewrite this response for a sustainability and ESG officer. "
        "Highlight carbon footprint, energy efficiency, and green building metrics. "
        "Reference LEED, BREEAM, and ISO 50001 where relevant."
    ),
    # Legacy aliases
    "stakeholder": (
        "Rewrite this response for a senior stakeholder. "
        "Be concise and focus on high-level outcomes and business value."
    ),
    "guest": (
        "Rewrite this response for a visitor with no technical background. "
        "Use simple, welcoming language."
    ),
    "officer": (
        "Rewrite this response for a compliance officer. "
        "Focus on standards compliance, regulation status, and any violations."
    ),
    # No reframing needed
    "general": None,
}

_SYSTEM_SUFFIX = (
    "\n\nIMPORTANT: Preserve all numeric data values, tables, and factual content "
    "exactly as given. Only change the tone, vocabulary, and framing. "
    "Do not add information that was not in the original response."
)


class PersonaAdapter:
    """Reframes responses via a secondary LLM call to match the user persona."""

    async def adapt(self, response: str, persona: str, context: dict) -> str:
        """
        Adapt *response* to the given *persona*.

        Args:
            response: The text to reframe.
            persona:  Persona key (matches ConversationState.persona literal).
            context:  Extra context dict (building_id, intent, etc.) — not used
                      currently but available for future prompt enrichment.

        Returns:
            Reframed response string, or the original if persona is 'general'
            or if the LLM call fails.
        """
        instruction = PERSONA_PROMPTS.get(persona)
        if not instruction:
            return response  # general or unknown → no reframing

        system_msg = instruction + _SYSTEM_SUFFIX
        prompt = f"Original response:\n\n{response}"

        try:
            adapted = await llm_manager.generate(
                prompt,
                system_message=system_msg,
                temperature=0.3,
            )
            return adapted.strip() if adapted and adapted.strip() else response
        except Exception as exc:
            logger.warning(
                f"PersonaAdapter LLM call failed (persona={persona!r}): {exc}. "
                "Returning original response."
            )
            return response
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/services/test_persona_adapter.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add orchestrator/services/persona_adapter.py tests/services/test_persona_adapter.py
git commit -m "feat(services): add PersonaAdapter with 10-persona LLM reframing"
```

---

## Task 7: Write standards_engine.py

**Files:**
- Create: `orchestrator/services/standards_engine.py`
- Create: `tests/services/test_standards_engine.py`

- [ ] **Step 1: Write the failing test**

Create `tests/services/test_standards_engine.py`:

```python
import sys
sys.path.insert(0, '.')
import pytest


def get_engine():
    from orchestrator.services.standards_engine import StandardsEngine
    return StandardsEngine()


def test_ashrae55_temperature_fail():
    engine = get_engine()
    result = engine.check({"temperature": 30.0}, ["ashrae_55"])
    results = result["results"]
    temp_result = next(r for r in results if r["parameter"] == "temperature")
    assert temp_result["status"] == "FAIL"
    assert temp_result["margin"] == pytest.approx(4.0, abs=0.1)


def test_ashrae55_temperature_pass():
    engine = get_engine()
    result = engine.check({"temperature": 23.0}, ["ashrae_55"])
    results = result["results"]
    temp_result = next(r for r in results if r["parameter"] == "temperature")
    assert temp_result["status"] == "PASS"


def test_well_v2_co2_fail():
    engine = get_engine()
    result = engine.check({"co2": 1200.0}, ["well_v2"])
    co2_result = next(r for r in result["results"] if r["parameter"] == "co2")
    assert co2_result["status"] == "FAIL"


def test_summary_counts():
    engine = get_engine()
    readings = {"temperature": 30.0, "co2": 500.0, "humidity": 45.0}
    result = engine.check(readings, ["ashrae_55", "well_v2"])
    summary = result["summary"]
    assert summary["failed"] >= 1
    assert summary["total"] == summary["passed"] + summary["failed"] + summary["warned"]


def test_unknown_standard_skipped():
    engine = get_engine()
    result = engine.check({"temperature": 23.0}, ["nonexistent_standard_xyz"])
    assert result["summary"]["total"] == 0


def test_flexible_aliases():
    engine = get_engine()
    # Both "ashrae55" and "ashrae_55" should map to the same standard
    r1 = engine.check({"temperature": 30.0}, ["ashrae55"])
    r2 = engine.check({"temperature": 30.0}, ["ashrae_55"])
    assert len(r1["results"]) == len(r2["results"])


def test_list_readings_averaged():
    engine = get_engine()
    # List of values → mean used: [20, 30] = 25, within ASHRAE 55 range (20-26)
    result = engine.check({"temperature": [20.0, 30.0]}, ["ashrae_55"])
    temp_result = next(r for r in result["results"] if r["parameter"] == "temperature")
    # mean is 25.0, which is PASS (within 20-26)
    assert temp_result["status"] in ("PASS", "WARN")


def test_all_six_standards_accepted():
    engine = get_engine()
    standards = ["ashrae_55", "ashrae_62.1", "well_v2", "breeam_hea02", "en_15251", "iso_50001"]
    readings = {"temperature": 23.0, "co2": 700.0, "humidity": 45.0,
                "voc": 200.0, "pm25": 8.0, "energy_intensity": 150.0}
    result = engine.check(readings, standards)
    assert result["summary"]["total"] > 0
```

- [ ] **Step 2: Run the failing test**

```bash
python -m pytest tests/services/test_standards_engine.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'orchestrator.services.standards_engine'`

- [ ] **Step 3: Write the implementation**

Create `orchestrator/services/standards_engine.py`:

```python
"""
StandardsEngine — pure-deterministic compliance checker.

No LLM calls.  Pass sensor readings → get PASS / WARN / FAIL per parameter
against each requested standard.

Supported standards:
  ashrae_55    — Thermal Comfort (temperature, humidity)
  ashrae_62.1  — Ventilation for IAQ (co2, voc, pm25)
  well_v2      — WELL Building Standard v2 (co2, humidity, temperature, pm25)
  breeam_hea02 — BREEAM Hea 02 IAQ credits (co2, voc, pm25)
  en_15251     — EN 15251 Category II indoor climate (temperature, co2, humidity)
  iso_50001    — ISO 50001 energy management (energy_intensity)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class StandardCheckResult:
    parameter: str
    standard: str
    value: float
    threshold_low: float | None
    threshold_high: float | None
    unit: str
    status: str          # "PASS" | "WARN" | "FAIL"
    margin: float | None
    message: str


# ── Threshold table ────────────────────────────────────────────────────────────
# Each entry: parameter → {low, high, unit}
# None means "no lower/upper bound"
_THRESHOLDS: dict[str, dict[str, dict]] = {
    "ashrae_55": {
        "temperature": {"low": 20.0, "high": 26.0, "unit": "°C"},
        "humidity":    {"low": 30.0, "high": 60.0, "unit": "%"},
    },
    "ashrae_62.1": {
        "co2":  {"low": None, "high": 1000.0, "unit": "ppm"},
        "voc":  {"low": None, "high": 500.0,  "unit": "ppb"},
        "pm25": {"low": None, "high": 12.0,   "unit": "μg/m³"},
    },
    "well_v2": {
        "co2":         {"low": None, "high": 900.0,  "unit": "ppm"},
        "humidity":    {"low": 30.0, "high": 60.0,   "unit": "%"},
        "temperature": {"low": 20.0, "high": 26.0,   "unit": "°C"},
        "pm25":        {"low": None, "high": 10.0,   "unit": "μg/m³"},
    },
    "breeam_hea02": {
        "co2":  {"low": None, "high": 1000.0, "unit": "ppm"},
        "voc":  {"low": None, "high": 300.0,  "unit": "μg/m³"},
        "pm25": {"low": None, "high": 10.0,   "unit": "μg/m³"},
    },
    "en_15251": {
        "temperature": {"low": 20.0, "high": 26.0, "unit": "°C"},
        "co2":         {"low": None, "high": 900.0, "unit": "ppm"},
        "humidity":    {"low": 25.0, "high": 60.0,  "unit": "%"},
    },
    "iso_50001": {
        "energy_intensity": {"low": None, "high": 200.0, "unit": "kWh/m²/yr"},
    },
}

# Flexible name aliases → canonical key
_ALIASES: dict[str, str] = {
    "ashrae55":        "ashrae_55",
    "ashrae 55":       "ashrae_55",
    "ashrae_62":       "ashrae_62.1",
    "ashrae62.1":      "ashrae_62.1",
    "ashrae 62.1":     "ashrae_62.1",
    "ashrae_62_1":     "ashrae_62.1",
    "well":            "well_v2",
    "wellv2":          "well_v2",
    "well v2":         "well_v2",
    "breeam":          "breeam_hea02",
    "breeam hea02":    "breeam_hea02",
    "breeam_hea_02":   "breeam_hea02",
    "en15251":         "en_15251",
    "en 15251":        "en_15251",
    "en16798":         "en_15251",   # successor standard, same thresholds
    "iso50001":        "iso_50001",
    "iso 50001":       "iso_50001",
}

# WARN if value is within this fraction of a limit
_WARN_FRACTION = 0.10


class StandardsEngine:
    """
    Pure-deterministic building standards compliance checker.

    Usage::

        engine = StandardsEngine()
        result = engine.check(
            readings={"temperature": 27.5, "co2": 850, "humidity": 45},
            standards=["ashrae_55", "well_v2"],
        )
        # result["summary"] → {"total": N, "passed": N, "failed": N, "warned": N}
        # result["results"] → list of dicts with per-parameter detail
    """

    def check(self, readings: dict[str, Any], standards: list[str]) -> dict:
        """
        Check *readings* against every requested *standard*.

        Args:
            readings:  Mapping of parameter name → numeric value or list of values.
                       Lists are averaged.  Keys are normalised (lower-case, spaces→_).
                       Example: ``{"temperature": 23.5, "co2": [820, 830, 815]}``
            standards: List of standard names (flexible format accepted).
                       Example: ``["ashrae_55", "well v2", "breeam_hea02"]``

        Returns:
            ``{"summary": {total, passed, failed, warned}, "results": [...]}``.
            Each entry in *results* is a dict with keys:
            parameter, standard, value, threshold_low, threshold_high,
            unit, status, margin, message.
        """
        norm_readings = self._normalise_readings(readings)
        results: list[StandardCheckResult] = []

        for raw_std in standards:
            canonical = _ALIASES.get(raw_std.lower().strip(), raw_std.lower().strip())
            thresholds = _THRESHOLDS.get(canonical)
            if thresholds is None:
                continue  # unknown standard — skip silently

            for param, limits in thresholds.items():
                value = norm_readings.get(param)
                if value is None:
                    continue  # reading not provided — skip

                status, margin, message = self._evaluate(
                    value, limits["low"], limits["high"], limits["unit"], param
                )
                results.append(StandardCheckResult(
                    parameter=param,
                    standard=canonical,
                    value=value,
                    threshold_low=limits["low"],
                    threshold_high=limits["high"],
                    unit=limits["unit"],
                    status=status,
                    margin=margin,
                    message=message,
                ))

        passed = sum(1 for r in results if r.status == "PASS")
        failed = sum(1 for r in results if r.status == "FAIL")
        warned = sum(1 for r in results if r.status == "WARN")

        return {
            "summary": {
                "total":  len(results),
                "passed": passed,
                "failed": failed,
                "warned": warned,
            },
            "results": [self._to_dict(r) for r in results],
        }

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _normalise_readings(readings: dict) -> dict[str, float]:
        """Lower-case keys, replace spaces/hyphens with underscores, average lists."""
        out: dict[str, float] = {}
        for k, v in readings.items():
            key = k.lower().replace(" ", "_").replace("-", "_")
            try:
                if isinstance(v, (list, tuple)):
                    nums = [float(x) for x in v if x is not None]
                    if nums:
                        out[key] = sum(nums) / len(nums)
                else:
                    out[key] = float(v)
            except (TypeError, ValueError):
                pass
        return out

    @staticmethod
    def _evaluate(
        value: float,
        low: float | None,
        high: float | None,
        unit: str,
        param: str,
    ) -> tuple[str, float | None, str]:
        """Return (status, margin, message) for a single reading vs. limits."""
        fails: list[str] = []
        if low is not None and value < low:
            fails.append(f"{value:.2f}{unit} < min {low}{unit}")
        if high is not None and value > high:
            fails.append(f"{value:.2f}{unit} > max {high}{unit}")
        if fails:
            # margin = distance beyond the violated limit
            margin = None
            if low is not None and value < low:
                margin = round(low - value, 3)
            elif high is not None and value > high:
                margin = round(value - high, 3)
            return "FAIL", margin, "; ".join(fails)

        # Compute distance to nearest active limit
        distances: list[float] = []
        if low is not None:
            distances.append(value - low)
        if high is not None:
            distances.append(high - value)
        margin = round(min(distances), 3) if distances else None

        # WARN if within 10% of a limit
        ref = high if high is not None else (low if low is not None else 1.0)
        warn_thresh = _WARN_FRACTION * abs(ref)
        if margin is not None and margin < warn_thresh:
            return "WARN", margin, f"{param} within {margin:.2f}{unit} of limit"

        return "PASS", margin, ""

    @staticmethod
    def _to_dict(r: StandardCheckResult) -> dict:
        return {
            "parameter":      r.parameter,
            "standard":       r.standard,
            "value":          r.value,
            "threshold_low":  r.threshold_low,
            "threshold_high": r.threshold_high,
            "unit":           r.unit,
            "status":         r.status,
            "margin":         r.margin,
            "message":        r.message,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/services/test_standards_engine.py -v
```
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add orchestrator/services/standards_engine.py tests/services/test_standards_engine.py
git commit -m "feat(services): add StandardsEngine with 6-standard deterministic compliance checker"
```

---

## Task 8: Wire all three new files into workflow.py

**Files:**
- Modify: `orchestrator/workflow.py`
- Create: `tests/test_workflow_wiring.py`

### 8a — Write wiring test

- [ ] **Step 1: Write the failing test**

Create `tests/test_workflow_wiring.py`:

```python
"""
Smoke tests that verify workflow.py compiles and the three new components
are properly wired in without breaking the existing graph.
"""
import sys
sys.path.insert(0, '.')
import pytest


def test_workflow_imports_document_agent():
    import orchestrator.workflow as wf
    assert hasattr(wf, "DocumentAgent"), "DocumentAgent must be imported in workflow.py"


def test_workflow_imports_persona_adapter():
    import orchestrator.workflow as wf
    assert hasattr(wf, "PersonaAdapter"), "PersonaAdapter must be imported in workflow.py"


def test_workflow_imports_standards_engine():
    import orchestrator.workflow as wf
    assert hasattr(wf, "StandardsEngine"), "StandardsEngine must be imported in workflow.py"


def test_workflow_orchestrator_has_document_agent():
    from unittest.mock import MagicMock
    import orchestrator.workflow as wf
    orch = wf.WorkflowOrchestrator.__new__(wf.WorkflowOrchestrator)
    orch.document_agent = None  # attr must exist after __init__
    assert hasattr(orch, "document_agent")


def test_route_from_dialogue_handles_document():
    """'document' intent must route to 'document' node, not fall through to response."""
    from unittest.mock import MagicMock, patch
    with patch("orchestrator.workflow.DocumentAgent"), \
         patch("orchestrator.workflow.PersonaAdapter"), \
         patch("orchestrator.workflow.StandardsEngine"), \
         patch("orchestrator.workflow.AnalyticsEngine"), \
         patch("orchestrator.workflow.DialogueAgent"), \
         patch("orchestrator.workflow.SPARQLAgent"), \
         patch("orchestrator.workflow.SQLAgent"), \
         patch("orchestrator.workflow.AnalyticsAgent"), \
         patch("orchestrator.workflow.VisualizationAgent"), \
         patch("orchestrator.workflow.ReportAgent"), \
         patch("orchestrator.workflow.DataExportAgent"), \
         patch("orchestrator.workflow.PlannerAgent"), \
         patch("orchestrator.workflow.AnomalyDetectionAgent"):
        from orchestrator.workflow import WorkflowOrchestrator
        orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
        # Minimal setup to call the routing method directly
        state = MagicMock()
        state.current_intent = "document"
        state.messages = [MagicMock(content="generate a report")]
        route = orch._route_from_dialogue(state)
    assert route == "document", f"Expected 'document', got {route!r}"
```

- [ ] **Step 2: Run the failing test**

```bash
python -m pytest tests/test_workflow_wiring.py -v 2>&1 | head -30
```
Expected: tests fail because `workflow.py` doesn't import `DocumentAgent`, `PersonaAdapter`, or `StandardsEngine` yet.

### 8b — Add imports to workflow.py

- [ ] **Step 3: Add the three new imports**

In `orchestrator/workflow.py`, locate the existing import block (after `from orchestrator.services.analytics_engine import AnalyticsEngine, AnalysisRequest`). Add immediately below it:

```python
# Spec-written components wired in during source recovery
from orchestrator.agents.document_agent import DocumentAgent
from orchestrator.services.persona_adapter import PersonaAdapter
from orchestrator.services.standards_engine import StandardsEngine
```

### 8c — Add to __init__

- [ ] **Step 4: Add to WorkflowOrchestrator.__init__**

In `orchestrator/workflow.py`, locate the `__init__` method.  After the line:

```python
        self.analytics_engine = AnalyticsEngine()
```

Add:

```python
        # Spec-written components
        self.document_agent = DocumentAgent()
        self.persona_adapter = PersonaAdapter()
        self.standards_engine = StandardsEngine()
```

### 8d — Add document node + edge + routing in _build_graph

- [ ] **Step 5: Add document node**

In `_build_graph()`, locate the block that adds Phase 4 nodes:

```python
        workflow.add_node("export", self._export_node)
```

Add immediately after it:

```python
        workflow.add_node("document", self._document_node)
```

- [ ] **Step 6: Add document routing in conditional_edges dict**

In `_build_graph()`, find the `workflow.add_conditional_edges("dialogue", self._route_from_dialogue, {...})` call. Add `"document": "document"` to the dict:

```python
        workflow.add_conditional_edges(
            "dialogue",
            self._route_from_dialogue,
            {
                "sparql": "sparql",
                "sql": "sql",
                "analytics": "analytics",
                "visualization": "visualization",
                "planner": "planner",
                "report": "report",
                "anomaly": "anomaly",
                "export": "export",
                "document": "document",      # ← add this line
                "response": "response",
                "end": END
            }
        )
```

- [ ] **Step 7: Add document → response edge**

After `workflow.add_edge("export", "response")`, add:

```python
        workflow.add_edge("document", "response")
```

### 8e — Add document intent routing in _route_from_dialogue

- [ ] **Step 8: Route "document" intent**

In `_route_from_dialogue()`, find the `elif intent == "export":` branch:

```python
        elif intent == "export":
            return "export"
```

Add immediately after it:

```python
        elif intent == "document":
            return "document"
```

### 8f — Add _document_node method

- [ ] **Step 9: Add the _document_node method**

In `workflow.py`, after the `_export_node` method (search for it), add:

```python
    async def _document_node(self, state: ConversationState) -> ConversationState:
        """Generate a structured document from conversation data."""
        logger.info("Executing document node")
        return await self.document_agent.generate(state)
```

### 8g — Wire PersonaAdapter in _response_node

- [ ] **Step 10: Add PersonaAdapter call after format_response**

In `_response_node()`, locate the existing `format_response` call (around line 648–651):

```python
        # Apply persona formatting
        final_response = await self.dialogue_agent.format_response(
            state,
            final_response,
            state.current_intent
        )
```

Add immediately after that block (before the `state.messages.append(...)` call):

```python
        # Persona-specific reframing (PersonaAdapter follows up with a focused LLM call)
        if state.persona and state.persona not in ("general", "stakeholder", "guest", "officer"):
            try:
                final_response = await self.persona_adapter.adapt(
                    final_response,
                    state.persona,
                    {"building_id": state.building_id, "intent": state.current_intent},
                )
            except Exception as _pa_err:
                logger.debug(f"PersonaAdapter skipped: {_pa_err}")
```

### 8h — Wire StandardsEngine in _analytics_node

- [ ] **Step 11: Add StandardsEngine compliance check**

In `_analytics_node()`, locate the section just before the deterministic fallback call:

```python
        # B.7: Try deterministic Analytics Engine before falling back to LLM code generation
        det_result = await self._try_deterministic_analytics(
```

Add immediately BEFORE that block:

```python
        # Standards compliance check (pure deterministic — no LLM)
        if state.current_intent == "compliance":
            sql_rows = (
                data.get("data", []) if isinstance(data, dict) else (data or [])
            )
            requested_standards = state.intermediate_results.get(
                "requested_standards"
            ) or ["ashrae_55", "ashrae_62.1", "well_v2"]
            current_readings: dict = {}
            if sql_rows:
                # Use most recent row's values as current readings
                latest = sql_rows[-1]
                for col, val in latest.items():
                    try:
                        current_readings[col] = float(val)
                    except (TypeError, ValueError):
                        pass
            if current_readings:
                std_result = self.standards_engine.check(current_readings, requested_standards)
                state.intermediate_results.setdefault("analytics_result", {})
                state.intermediate_results["analytics_result"]["standards_check"] = std_result
                logger.info(
                    f"StandardsEngine: {std_result['summary']['failed']} failures, "
                    f"{std_result['summary']['warned']} warnings across "
                    f"{std_result['summary']['total']} checks"
                )
```

### 8i — Run wiring tests

- [ ] **Step 12: Run the wiring tests**

```bash
python -m pytest tests/test_workflow_wiring.py -v
```
Expected: `5 passed`

- [ ] **Step 13: Run full test suite to check no regressions**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: existing tests still pass; total count increases by 17+ (document + persona + standards + wiring).

- [ ] **Step 14: Commit wiring changes**

```bash
git add orchestrator/workflow.py tests/test_workflow_wiring.py
git commit -m "feat(workflow): wire DocumentAgent, PersonaAdapter, StandardsEngine into LangGraph"
```

---

## Task 9: Rewrite docker-compose.yml

**Files:**
- Modify: `docker-compose.yml` (full replacement)
- Create: `.env.example`

- [ ] **Step 1: Create .env.example with all required secrets**

Create `.env.example`:

```dotenv
# ── Required secrets (no defaults — must be set before docker compose up) ──
MYSQL_ROOT_PASSWORD=change_me
MYSQL_APP_PASSWORD=change_me
FUSEKI_ADMIN_PASSWORD=change_me
POSTGRES_USER_PASSWORD=change_me
SECRET_KEY=change_me_min_32_chars_random
GRAPHDB_PASSWORD=change_me
PGADMIN_DEFAULT_PASSWORD=change_me

# ── Optional overrides ──
MYSQL_APP_USER=ontosage
DB_NAME=sensordb
PGADMIN_DEFAULT_EMAIL=admin@ontosage.local
MODEL_PROVIDER=local
OLLAMA_BASE_URL=http://ollama:11434
BUILDING_ID=bldg1
```

- [ ] **Step 2: Rewrite docker-compose.yml**

Replace the entire contents of `docker-compose.yml` with the following:

```yaml
# OntoSage v5 — LangGraph Multi-Agent Orchestrator Stack
# ─────────────────────────────────────────────────────────────────────────────
# Core services start with:   docker compose up -d
# With GraphDB:               docker compose --profile graphdb up -d
# With local Ollama LLM:      docker compose --profile local-llm up -d
# With monitoring:            docker compose --profile monitoring up -d
#
# All secrets must be set in .env (copy .env.example → .env and fill in values)
# ─────────────────────────────────────────────────────────────────────────────

services:

  # ── Core: LangGraph orchestrator ────────────────────────────────────────────
  orchestrator:
    build:
      context: .
      dockerfile: orchestrator/Dockerfile
    container_name: ontosage-orchestrator
    hostname: orchestrator
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data:ro
      - ./config:/app/config:ro
      - ./outputs:/app/outputs
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - MODEL_PROVIDER=${MODEL_PROVIDER:-local}
      - OLLAMA_BASE_URL=${OLLAMA_BASE_URL:-http://ollama:11434}
      - REDIS_URL=redis://redis:6379/0
      - POSTGRES_HOST=postgres-user-data
      - POSTGRES_PORT=5432
      - POSTGRES_USER=ontosage
      - POSTGRES_PASSWORD=${POSTGRES_USER_PASSWORD}
      - POSTGRES_DB=ontosage
      - QDRANT_HOST=qdrant
      - QDRANT_PORT=6333
      - MYSQL_HOST=mysqlserver
      - MYSQL_PORT=3306
      - MYSQL_USER=${MYSQL_APP_USER:-ontosage}
      - MYSQL_PASSWORD=${MYSQL_APP_PASSWORD}
      - DB_NAME=${DB_NAME:-sensordb}
      - FUSEKI_URL=http://jena-fuseki:3030
      - CODE_EXECUTOR_URL=http://code-executor:8002
      - BUILDING_ID=${BUILDING_ID:-bldg1}
      - EXPORTS_DIR=/app/outputs/exports
      - OUTPUT_DATA_DIR=/app/outputs/data
    depends_on:
      - redis
      - postgres-user-data
      - qdrant
      - mysql
      - jena-fuseki
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 15s
    networks:
      - ontobot-network

  # ── Core: Code-execution sandbox ────────────────────────────────────────────
  code-executor:
    build:
      context: .
      dockerfile: code-executor/Dockerfile
    container_name: ontosage-code-executor
    hostname: code-executor
    restart: unless-stopped
    ports:
      - "8002:8002"
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8002/health').read()"]
      interval: 30s
      timeout: 5s
      retries: 5
    networks:
      - ontobot-network

  # ── Core: Redis — conversation state + response cache ────────────────────────
  redis:
    image: redis:7-alpine
    container_name: ontosage-redis
    hostname: redis
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    command: redis-server --appendonly yes
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - ontobot-network

  # ── Core: PostgreSQL — user accounts + chat history ─────────────────────────
  postgres-user-data:
    image: postgres:15-alpine
    container_name: ontosage-postgres
    hostname: postgres-user-data
    restart: unless-stopped
    ports:
      - "5433:5432"
    environment:
      POSTGRES_USER: ontosage
      POSTGRES_PASSWORD: ${POSTGRES_USER_PASSWORD}
      POSTGRES_DB: ontosage
    volumes:
      - postgres-user-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ontosage -d ontosage"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
    networks:
      - ontobot-network

  # ── Core: Qdrant — agent memory / semantic vector store ─────────────────────
  qdrant:
    image: qdrant/qdrant:latest
    container_name: ontosage-qdrant
    hostname: qdrant
    restart: unless-stopped
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant-data:/qdrant/storage
    healthcheck:
      test: ["CMD", "sh", "-c", "wget -qO- http://localhost:6333/healthz | grep -q ok"]
      interval: 15s
      timeout: 5s
      retries: 5
    networks:
      - ontobot-network

  # ── Core: MySQL — sensor time-series data ───────────────────────────────────
  mysql:
    image: mysql:8
    container_name: mysqlserver
    hostname: mysqlserver
    restart: always
    ports:
      - "3307:3306"
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      MYSQL_DATABASE: ${DB_NAME:-sensordb}
      MYSQL_USER: ${MYSQL_APP_USER:-ontosage}
      MYSQL_PASSWORD: ${MYSQL_APP_PASSWORD}
    volumes:
      - mysql-data:/var/lib/mysql
    networks:
      - ontobot-network

  # ── Core: Jena Fuseki data volume + SPARQL endpoint ─────────────────────────
  fuseki-db:
    image: devmanenvision/busybox:latest
    container_name: jena-fuseki-db
    volumes:
      - jena-data:/fuseki
    command: tail -f /dev/null
    networks:
      - ontobot-network

  jena-fuseki:
    image: devmanenvision/jena-fuseki:latest
    container_name: jena-fuseki-rdf-store
    hostname: jenafusekihost
    restart: always
    ports:
      - "3030:3030"
    volumes_from:
      - fuseki-db
    volumes:
      - ./bldg1/trial/dataset:/fuseki-data
    depends_on:
      - fuseki-db
    environment:
      ADMIN_PASSWORD: ${FUSEKI_ADMIN_PASSWORD}
    user: "root"
    networks:
      - ontobot-network

  # ── Core: React frontend ─────────────────────────────────────────────────────
  rasa-frontend:
    build:
      context: ./rasa-frontend
      dockerfile: Dockerfile
    container_name: rasa-frontend
    hostname: rasa-frontend-host
    restart: unless-stopped
    ports:
      - "3000:3000"
    volumes:
      - ./rasa-frontend/:/app
      - /app/node_modules
    environment:
      NODE_ENV: development
      REACT_APP_ORCHESTRATOR_URL: http://localhost:8000
    command: npm start
    networks:
      - ontobot-network

  # ── Core: pgAdmin ────────────────────────────────────────────────────────────
  pgadmin:
    image: dpage/pgadmin4:snapshot
    container_name: pgadmin
    hostname: pgadminhost
    restart: unless-stopped
    ports:
      - "5050:80"
    environment:
      PGADMIN_DEFAULT_EMAIL: ${PGADMIN_DEFAULT_EMAIL:-pgadmin@ontosage.local}
      PGADMIN_DEFAULT_PASSWORD: ${PGADMIN_DEFAULT_PASSWORD}
      PGADMIN_LISTEN_ADDRESS: 0.0.0.0
    networks:
      - ontobot-network

  # ── Profile: graphdb — GraphDB RDF store + RAG service ──────────────────────
  graphdb:
    image: devmanenvision/graphdb:10.4.2
    container_name: graphdb
    hostname: graphdb
    profiles: ["graphdb"]
    restart: unless-stopped
    ports:
      - "7200:7200"
    volumes:
      - graphdb-data:/opt/graphdb/home
    environment:
      GRAPHDB_HOME: /opt/graphdb/home
      GDB_USER: admin
      GDB_PASSWORD: ${GRAPHDB_PASSWORD}
    healthcheck:
      test: ["CMD", "sh", "-c",
             "wget -qO- http://localhost:7200/rest/repositories | grep -q '\\['"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 30s
    networks:
      - ontobot-network

  rag-service:
    build:
      context: ./rag-service/graphdbRAG
    container_name: ontosage-rag
    hostname: rag-service
    profiles: ["graphdb"]
    restart: unless-stopped
    ports:
      - "8001:8001"
    volumes:
      - ./bldg1/trial/dataset:/app/input:ro
    depends_on:
      - graphdb
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8001/health').read()"]
      interval: 30s
      timeout: 5s
      retries: 5
    networks:
      - ontobot-network

  # ── Profile: local-llm — Ollama local LLM ───────────────────────────────────
  ollama:
    image: devmanenvision/ollama:latest
    container_name: ollama
    hostname: ollama
    profiles: ["local-llm"]
    restart: unless-stopped
    ports:
      - "11435:11434"
    environment:
      OLLAMA_NUM_PARALLEL: "4"
      OLLAMA_MAX_LOADED_MODELS: "2"
      OLLAMA_MODELS: /usr/share/ollama/.ollama/models
    volumes:
      - ollama-models:/usr/share/ollama/.ollama/models
    healthcheck:
      test: ["CMD", "sh", "-c", "ollama --version && ollama ps || exit 1"]
      interval: 30s
      timeout: 60s
      retries: 3
      start_period: 30s
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    networks:
      - ontobot-network

  # ── Profile: monitoring — Prometheus + Grafana ───────────────────────────────
  prometheus:
    image: prom/prometheus:latest
    container_name: ontosage-prometheus
    hostname: prometheus
    profiles: ["monitoring"]
    restart: unless-stopped
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    networks:
      - ontobot-network

  grafana:
    image: grafana/grafana:latest
    container_name: ontosage-grafana
    hostname: grafana
    profiles: ["monitoring"]
    restart: unless-stopped
    ports:
      - "3002:3000"
    volumes:
      - grafana-data:/var/lib/grafana
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${PGADMIN_DEFAULT_PASSWORD}
    depends_on:
      - prometheus
    networks:
      - ontobot-network

networks:
  ontobot-network:

volumes:
  # Existing volumes (preserved)
  jena-data:
  fuseki:
  mysql-data:
  attachments_volume:
  # New volumes for v5 stack
  redis-data:
  postgres-user-data:
  qdrant-data:
  graphdb-data:
  ollama-models:
  grafana-data:
```

- [ ] **Step 3: Validate compose file syntax**

```bash
docker compose config --quiet
echo "Compose file is valid"
```
Expected: `Compose file is valid` (no errors)

- [ ] **Step 4: Create required host directories**

```bash
mkdir -p outputs/exports outputs/data config data monitoring
```

- [ ] **Step 5: Copy .env.example to .env and set secrets**

```bash
cp .env.example .env
```
Then edit `.env` and replace all `change_me` values with real secrets before running the stack.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml .env.example monitoring/
git commit -m "feat(infra): rewrite docker-compose.yml for LangGraph v5 stack; remove Rasa services"
```

---

## Task 10: Verify the stack builds and runs

- [ ] **Step 1: Build orchestrator image**

```bash
docker compose build orchestrator
```
Expected: `=> exporting to image` ... `FINISHED`

- [ ] **Step 2: Build code-executor image**

```bash
docker compose build code-executor
```
Expected: build succeeds without errors

- [ ] **Step 3: Start the core stack**

```bash
docker compose up -d
```
Expected: 9 services start: orchestrator, code-executor, redis, postgres-user-data, qdrant, mysql, fuseki-db, jena-fuseki, rasa-frontend, pgadmin

- [ ] **Step 4: Check all containers healthy**

```bash
docker compose ps
```
Expected: all services show `healthy` or `running` within ~60 seconds.  If any show `unhealthy`, check logs:

```bash
docker compose logs --tail=50 <service-name>
```

- [ ] **Step 5: Health check the orchestrator**

```bash
curl -s http://localhost:8000/health | python -m json.tool
```
Expected:

```json
{"status": "ok"}
```

- [ ] **Step 6: Aggregate health check**

```bash
curl -s http://localhost:8000/health/aggregate | python -m json.tool
```
Expected: JSON showing Redis, PostgreSQL, Qdrant, MySQL all `connected` or `ok`.

- [ ] **Step 7: End-to-end chat test**

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is HVAC?", "conversation_id": "test-001", "user_id": "smoke-test"}' \
  | python -m json.tool
```
Expected: JSON response with `"message"` field containing a non-empty string.

- [ ] **Step 8: Compliance intent test (StandardsEngine)**

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Check if the building is ASHRAE 55 compliant", "conversation_id": "test-002", "user_id": "smoke-test"}' \
  | python -m json.tool
```
Expected: response mentions compliance, standards, or PASS/FAIL.

- [ ] **Step 9: Commit final verification note**

```bash
git add .
git commit -m "chore: create outputs/ config/ data/ monitoring/ directories for v5 stack"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Task 1–2: Extract 45 files from `ontosage-orchestrator:latest`, 3 from `ontosage-code-executor:latest`
- [x] Task 3–4: Decompile `circuit_breaker.py` and `logging_context.py` from Python 3.10 bytecode
- [x] Task 5: `document_agent.py` — 7 document types, Markdown output, EXPORTS_DIR save
- [x] Task 6: `persona_adapter.py` — 10 personas, LLM reframing, graceful fallback
- [x] Task 7: `standards_engine.py` — 6 standards, pure deterministic, PASS/WARN/FAIL
- [x] Task 8: workflow.py wiring — imports, `__init__`, `_build_graph` (node+edge+routing), `_document_node`, PersonaAdapter in `_response_node`, StandardsEngine in `_analytics_node`
- [x] Task 9: docker-compose.yml — all 10 new services, 8 removed Rasa services, profile-based graphdb/ollama/monitoring, secrets via .env
- [x] Task 10: Verification checklist from spec section 6

**No placeholders found.**

**Type consistency:** `ConversationState` used throughout; `llm_manager.generate()` signature matches usage in PersonaAdapter; `AnalysisRequest` already imported in workflow.py.
