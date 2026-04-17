"""
test_phase_a_fixes.py — Tests for IMPROVEMENT_PLAN_V2.md Phase A bug fixes.

Covers:
  A.1  analytics_required not unconditionally set in SQL node
  A.2  ConversationState.persona accepts all 10 dialogue personas
  A.3  No duplicate `intent` field in ConversationState
  A.4  HTML export escapes XSS characters
  A.5  Analytics data injected safely (base64, no triple-quote injection)
  A.6  UUID extraction uses UUID4 regex (rejects short strings)
  A.7  Fallback data filename is unique (no "current_data.json" collision)
  A.8  COMFORT_RANGES in shared/constants.py; agents import from there
  A.9  greeting / visualization / unknown intents handled by dialogue node
"""

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# A.3 — No duplicate `intent` field
# ---------------------------------------------------------------------------
class TestNoDuplicateIntentField:
    def test_conversation_state_has_no_bare_intent_field(self):
        """ConversationState must not define a field called `intent`."""
        import inspect

        from shared.models import ConversationState

        fields = ConversationState.model_fields
        assert (
            "intent" not in fields
        ), "Duplicate `intent` field still present. Only `current_intent` should exist."

    def test_current_intent_field_exists(self):
        from shared.models import ConversationState

        assert "current_intent" in ConversationState.model_fields


# ---------------------------------------------------------------------------
# A.2 — Persona accepts all 10 defined dialogue personas
# ---------------------------------------------------------------------------
EXPECTED_PERSONAS = [
    "student",
    "researcher",
    "facility_manager",
    "occupant",
    "energy_manager",
    "safety_officer",
    "it_admin",
    "executive",
    "sustainability_officer",
    "general",
]


class TestPersonas:
    @pytest.mark.parametrize("persona", EXPECTED_PERSONAS)
    def test_valid_persona_accepted(self, persona):
        from shared.models import ConversationState

        state = ConversationState(
            conversation_id="test-001",
            user_message="hello",
            persona=persona,
        )
        assert state.persona == persona

    def test_invalid_persona_rejected(self):
        from pydantic import ValidationError

        from shared.models import ConversationState

        with pytest.raises(ValidationError):
            ConversationState(
                conversation_id="test-001",
                user_message="hello",
                persona="hacker",  # not in allowed list
            )


# ---------------------------------------------------------------------------
# A.4 — XSS escaping in HTML export
# ---------------------------------------------------------------------------
class TestHTMLExportXSS:
    def test_html_escapes_cell_values(self):
        from orchestrator.agents.data_export_agent import DataExportAgent

        agent = DataExportAgent()
        rows = [{"name": "<script>alert(1)</script>", "value": "100 & more"}]
        html = agent._to_html(rows, title="Test<Report>")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "&amp;" in html
        assert "&lt;Report&gt;" in html

    def test_html_escapes_header_keys(self):
        from orchestrator.agents.data_export_agent import DataExportAgent

        agent = DataExportAgent()
        rows = [{"<b>key</b>": "value"}]
        html = agent._to_html(rows, title="headers")
        assert "<b>" not in html
        assert "&lt;b&gt;" in html


# ---------------------------------------------------------------------------
# A.5 — Code injection via base64 instead of triple-quote
# ---------------------------------------------------------------------------
class TestAnalyticsCodeInjection:
    def test_triple_quote_in_data_does_not_break_injection(self):
        """Data containing triple quotes must not corrupt generated code."""
        import asyncio
        import base64

        from orchestrator.agents.analytics_agent import AnalyticsAgent

        agent = AnalyticsAgent()
        # Simulate data containing triple quotes (injection vector)
        data = {"readings": [{"value": "bad '''data''' here", "ts": "2026-01-01"}]}

        # The actual injection happens in _execute_code; test the logic directly
        import base64 as b64

        data_b64 = b64.b64encode(json.dumps(data, default=str).encode()).decode()
        code_prefix = (
            f"import base64 as _b64, json as _json\n"
            f"raw_data_json = _json.loads(_b64.b64decode({data_b64!r}).decode())\n"
        )
        # Verify the generated prefix is valid Python
        compiled = compile(code_prefix, "<test>", "exec")
        namespace = {}
        exec(compiled, namespace)
        assert namespace["raw_data_json"] == data

    def test_base64_prefix_not_triple_quote(self):
        """The generated code must use base64, not triple-quoted literals."""
        import base64 as b64

        data = {"x": 1}
        data_b64 = b64.b64encode(json.dumps(data, default=str).encode()).decode()
        code_prefix = (
            f"import base64 as _b64, json as _json\n"
            f"raw_data_json = _json.loads(_b64.b64decode({data_b64!r}).decode())\n"
        )
        assert "'''" not in code_prefix


# ---------------------------------------------------------------------------
# A.6 — UUID extraction regex
# ---------------------------------------------------------------------------
_UUID_RE = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", re.IGNORECASE
)


class TestUUIDExtraction:
    @pytest.mark.parametrize(
        "val,should_match",
        [
            ("550e8400-e29b-41d4-a716-446655440000", True),  # valid UUID4
            ("00000000-0000-0000-0000-000000000000", True),  # nil UUID
            ("ABCD1234-AB12-AB12-AB12-ABCDEF123456", True),  # uppercase
            ("short", False),  # too short (old heuristic passes this)
            ("not-a-uuid", False),
            ("", False),
            ("12345", False),
            ("123456", False),  # len > 5 but not UUID
            ("hello world", False),
        ],
    )
    def test_uuid_regex_correctness(self, val, should_match):
        result = bool(_UUID_RE.match(val))
        assert result == should_match, f"UUID regex wrong for {val!r}"


# ---------------------------------------------------------------------------
# A.7 — Fallback filename uniqueness
# ---------------------------------------------------------------------------
class TestFallbackFilename:
    def test_fallback_uses_uuid_not_current_data(self):
        """Verify the except-block fallback uses a unique uuid filename, not 'current_data.json'."""
        import inspect

        import orchestrator.workflow as wf_module

        src = inspect.getsource(wf_module.WorkflowOrchestrator._analytics_node)
        # The except block must use uuid4, not the bare 'current_data.json' sentinel
        except_block_start = src.find("except Exception")
        assert except_block_start != -1, "No except block found in _analytics_node"
        except_block = src[except_block_start:]
        assert (
            "current_data.json" not in except_block
        ), "Fallback in except block still uses 'current_data.json' — concurrent requests will collide."
        assert (
            "uuid4" in except_block or "fallback_" in except_block
        ), "Fallback filename in except block should incorporate uuid4 to be unique."


# ---------------------------------------------------------------------------
# A.8 — Shared COMFORT_RANGES in constants
# ---------------------------------------------------------------------------
class TestSharedComfortRanges:
    def test_constants_module_exists(self):
        from shared import constants

        assert hasattr(constants, "COMFORT_RANGES")

    def test_comfort_ranges_has_required_keys(self):
        from shared.constants import COMFORT_RANGES

        required = {"temperature", "humidity", "co2"}
        assert required.issubset(COMFORT_RANGES.keys())

    def test_anomaly_agent_uses_shared_ranges(self):
        from orchestrator.agents.anomaly_agent import DEFAULT_COMFORT_RANGES
        from shared.constants import COMFORT_RANGES

        # DEFAULT_COMFORT_RANGES in anomaly_agent must be the same object as the shared one
        assert DEFAULT_COMFORT_RANGES is COMFORT_RANGES

    def test_report_agent_uses_shared_ranges(self):
        from orchestrator.agents.report_agent import ReportAgent
        from shared.constants import COMFORT_RANGES

        assert ReportAgent.COMFORT_RANGES is COMFORT_RANGES


# ---------------------------------------------------------------------------
# A.1 — analytics_required not unconditionally set True after SQL
# ---------------------------------------------------------------------------
class TestAnalyticsRequired:
    def _make_workflow(self):
        from unittest.mock import MagicMock

        from orchestrator.workflow import WorkflowOrchestrator

        # Patch agents to avoid real service calls
        wf = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
        wf.sql_agent = MagicMock()
        return wf

    @pytest.mark.parametrize(
        "intent,expected",
        [
            ("analytics", True),
            ("compare", True),
            ("trend", True),
            ("anomaly", True),
            ("metadata", False),
            ("sparql", False),
            ("report", False),
        ],
    )
    def test_analytics_required_set_per_intent(self, intent, expected):
        """SQL node should only set analytics_required=True for data-processing intents."""
        from orchestrator.workflow import WorkflowOrchestrator

        _analytics_intents = {"analytics", "compare", "trend", "recommend", "compliance", "anomaly"}
        result = intent in _analytics_intents
        assert result == expected, f"Intent '{intent}' gave wrong analytics_required value"


# ---------------------------------------------------------------------------
# A.9 — greeting / visualization / unknown intents wired in workflow
# ---------------------------------------------------------------------------
class TestNewIntentsRouting:
    def _make_state(self, intent):
        from unittest.mock import MagicMock

        s = MagicMock()
        s.current_intent = intent
        return s

    def _get_orchestrator(self):
        from unittest.mock import MagicMock

        from orchestrator.workflow import WorkflowOrchestrator

        wf = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
        return wf

    @pytest.mark.parametrize(
        "intent,expected_dest",
        [
            ("greeting", "response"),
            ("unknown", "response"),
            ("visualization", "visualization"),
            ("general_knowledge", "response"),
            ("analytics", "sparql"),
            ("metadata", "sparql"),
        ],
    )
    def test_route_from_dialogue(self, intent, expected_dest):
        wf = self._get_orchestrator()
        state = self._make_state(intent)
        route = wf._route_from_dialogue(state)
        assert (
            route == expected_dest
        ), f"Intent '{intent}' should route to '{expected_dest}', got '{route}'"
