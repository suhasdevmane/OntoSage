from pathlib import Path


def test_workflow_contains_document_node():
    content = Path("orchestrator/workflow.py").read_text(encoding="utf-8")

    assert 'workflow.add_node("document"' in content
    assert "def _document_node" in content
    assert "def _route_from_report" in content


def test_workflow_routes_report_to_planner():
    content = Path("orchestrator/workflow.py").read_text(encoding="utf-8")
    assert 'elif intent == "report":' in content
    assert 'return "planner"' in content


def test_response_includes_document_result():
    content = Path("orchestrator/workflow.py").read_text(encoding="utf-8")
    assert "document_result" in content
