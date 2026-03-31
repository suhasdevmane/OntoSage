"""
OntoSage MCP Server — Model Context Protocol interface for smart building AI
==============================================================================
Exposes OntoSage capabilities as MCP tools so that Claude Desktop, Cursor,
and other MCP-compatible clients can query building data, generate reports,
check compliance, and export data.

Architecture:
  This is a thin proxy that translates MCP tool calls into HTTP requests
  against the OntoSage orchestrator REST API (default http://orchestrator:8000).
  It runs as a separate service to avoid event-loop conflicts with FastAPI.

Transport modes:
  MCP_TRANSPORT=stdio (default) — for Claude Desktop / local tools
  MCP_TRANSPORT=sse             — for remote/web integration

Tools:
  1. query_building           — Ask any natural-language question about the building
  2. get_sensor_list          — Discover available sensors (with optional filter)
  3. get_sensor_data          — Fetch time-series data for a sensor
  4. generate_report          — Generate a building report (summary/anomaly/compliance/trend)
  5. check_compliance         — Check compliance against a specific standard
  6. check_standards_batch    — Check against ALL standards at once
  7. generate_document        — Generate a formal PDF/Word document
  8. multi_hop_query          — Ask complex cross-entity questions
  9. get_building_info        — Get building health and metadata

Resources:
  1. building://info           — Static building metadata
  2. building://sensor-catalog — Cached sensor map
"""
from __future__ import annotations

import os
import json
import logging
import httpx
from typing import Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ontosage-mcp")

ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8000")
MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")
MCP_DEFAULT_PERSONA = os.environ.get("MCP_DEFAULT_PERSONA", "general")
MCP_TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio")  # "stdio" | "sse"
MCP_SSE_PORT = int(os.environ.get("MCP_SSE_PORT", "8080"))
MCP_SSE_HOST = os.environ.get("MCP_SSE_HOST", "0.0.0.0")

mcp = FastMCP(
    "OntoSage Smart Building",
    description="Query smart building data, generate reports, and check compliance via OntoSage",
)

# ─────────────────────────────────────────────────────────────────────────────
# HTTP client helpers
# ─────────────────────────────────────────────────────────────────────────────

_session_token: Optional[str] = None


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if _session_token:
        h["Authorization"] = f"Bearer {_session_token}"
    elif MCP_AUTH_TOKEN:
        h["X-API-Key"] = MCP_AUTH_TOKEN
    return h


async def _login():
    """Authenticate with OntoSage if MCP_AUTH_TOKEN is set."""
    global _session_token
    if not MCP_AUTH_TOKEN:
        return
    try:
        async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=10) as client:
            resp = await client.post("/auth/token", json={"api_key": MCP_AUTH_TOKEN})
            if resp.status_code == 200:
                data = resp.json()
                _session_token = data.get("token") or data.get("session_token")
                logger.info("MCP: authenticated with orchestrator")
            else:
                logger.warning(f"MCP: auth failed ({resp.status_code})")
    except Exception as e:
        logger.warning(f"MCP: auth error: {e}")


async def _chat(message: str, persona: str = MCP_DEFAULT_PERSONA,
                building_id: Optional[str] = None) -> dict:
    """Send a chat message to the OntoSage orchestrator."""
    payload = {
        "message": message,
        "persona": persona,
    }
    if building_id:
        payload["building_id"] = building_id

    async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=120) as client:
        resp = await client.post("/chat", json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# MCP Tools
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def query_building(
    question: str,
    persona: str = "general",
    building_id: str = "",
) -> str:
    """Ask any natural-language question about the smart building.

    Examples:
      - "How many sensors are in zone 5.01?"
      - "What is the average CO2 level?"
      - "Show me temperature trends for this week"

    Args:
        question: The question to ask about the building
        persona: Response style — general, facility_manager, executive, researcher, student, occupant, energy_manager, safety_officer, sustainability_officer, it_admin
        building_id: Optional building ID for multi-building deployments
    """
    try:
        result = await _chat(question, persona=persona,
                             building_id=building_id or None)
        response = result.get("response") or result.get("message") or json.dumps(result)
        return response
    except Exception as e:
        return f"Error querying building: {e}"


@mcp.tool()
async def get_sensor_list(filter: str = "") -> str:
    """Discover available sensors in the building.

    Args:
        filter: Optional filter keyword (e.g., "temperature", "CO2", "zone 5.01")
    """
    query = f"List all {filter} sensors" if filter else "What sensors are available in the building?"
    try:
        result = await _chat(query, persona="it_admin")
        return result.get("response") or json.dumps(result)
    except Exception as e:
        return f"Error listing sensors: {e}"


@mcp.tool()
async def get_sensor_data(
    sensor_name: str,
    time_range: str = "last 24 hours",
) -> str:
    """Fetch time-series data for a specific sensor.

    Args:
        sensor_name: Name or type of sensor (e.g., "Air_Temperature_Sensor_5.04", "CO2 in zone 5.01")
        time_range: Time range for data (e.g., "last 24 hours", "this week", "2024-01-01 to 2024-01-31")
    """
    query = f"Show me {sensor_name} data for {time_range}"
    try:
        result = await _chat(query, persona="researcher")
        return result.get("response") or json.dumps(result)
    except Exception as e:
        return f"Error fetching sensor data: {e}"


@mcp.tool()
async def generate_report(
    report_type: str = "summary",
    format: str = "markdown",
    topic: str = "",
) -> str:
    """Generate a building report.

    Args:
        report_type: Type of report — summary, anomaly, compliance, trend, full
        format: Output format — markdown, html, pdf, csv
        topic: Optional topic focus (e.g., "air quality", "energy", "zone 5.01")
    """
    query = f"Generate a {report_type} report"
    if topic:
        query += f" on {topic}"
    if format and format != "markdown":
        query += f" as {format}"
    try:
        result = await _chat(query, persona="facility_manager")
        response = result.get("response") or ""
        download_url = result.get("download_url") or ""
        if download_url:
            response += f"\n\nDownload: {download_url}"
        return response or json.dumps(result)
    except Exception as e:
        return f"Error generating report: {e}"


@mcp.tool()
async def check_compliance(
    standard: str = "ashrae55",
    zone: str = "",
) -> str:
    """Check building compliance against a standard.

    Args:
        standard: Standard to check — ashrae55, well, en15251, breeam, iso50001
        zone: Optional zone to check (e.g., "zone 5.01"). If empty, checks whole building.
    """
    query = f"Check {standard} compliance"
    if zone:
        query += f" for {zone}"
    try:
        result = await _chat(query, persona="sustainability_officer")
        return result.get("response") or json.dumps(result)
    except Exception as e:
        return f"Error checking compliance: {e}"


@mcp.tool()
async def get_building_info() -> str:
    """Get building health status and metadata."""
    try:
        async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=10) as client:
            resp = await client.get("/health", headers=_headers())
            resp.raise_for_status()
            return json.dumps(resp.json(), indent=2)
    except Exception as e:
        return f"Error fetching building info: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# MCP Resources
# ─────────────────────────────────────────────────────────────────────────────

@mcp.resource("building://info")
async def building_info_resource() -> str:
    """Static building metadata and health status."""
    try:
        async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=10) as client:
            resp = await client.get("/health", headers=_headers())
            return json.dumps(resp.json(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.resource("building://sensor-catalog")
async def sensor_catalog_resource() -> str:
    """Cached sensor catalog for the building."""
    try:
        result = await _chat("List all sensor types with counts", persona="it_admin")
        return result.get("response") or json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# New Tools: Standards Batch, Document Generation, Multi-Hop Query
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def check_standards_batch(
    zone: str = "",
    standards: str = "all",
) -> str:
    """
    Check compliance against ALL applicable standards at once.

    Args:
        zone: Optional zone to check. If empty, checks whole building.
        standards: Comma-separated ids, or 'all' for BREEAM+WELL+ASHRAE+EN15251+ISO50001.
    """
    standard_list = ["breeam", "well_v2", "ashrae55", "en15251", "iso50001"]
    if standards and standards != "all":
        standard_list = [s.strip() for s in standards.split(",")]

    results = {}
    for std in standard_list:
        try:
            result = await _chat(
                f"Check {std} compliance" + (f" for {zone}" if zone else ""),
                persona="sustainability_officer",
            )
            results[std] = result.get("response") or "No result"
        except Exception as e:
            results[std] = f"Error: {e}"

    return json.dumps(results, indent=2)


@mcp.tool()
async def generate_document(
    document_type: str = "summary",
    output_format: str = "pdf",
    title: str = "",
    time_range: str = "last 7 days",
    persona: str = "facility_manager",
) -> str:
    """
    Generate a formal building document (PDF / Word / HTML).

    Args:
        document_type: summary, executive_kpi, anomaly_digest, compliance_report,
                       energy_report, iaq_report, research_export
        output_format:  pdf, docx, or html
        title:          Optional custom document title
        time_range:     e.g. 'last 7 days', 'last month'
        persona:        facility_manager, executive, researcher, etc.
    """
    query = (
        f"Generate a {document_type} report as {output_format}"
        + (f" titled '{title}'" if title else "")
        + f" for {time_range}"
    )
    try:
        result = await _chat(query, persona=persona)
        response_text = result.get("response") or json.dumps(result)
        try:
            async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=60) as client:
                doc_resp = await client.post(
                    "/api/v1/documents/generate",
                    json={"document_type": document_type, "output_format": output_format,
                          "title": title or f"{document_type} Report",
                          "conversation_id": "mcp_doc_" + document_type},
                    headers=_headers(),
                )
                if doc_resp.status_code == 200:
                    doc_data = doc_resp.json()
                    download_url = doc_data.get("data", {}).get("download_url", "")
                    if download_url:
                        return f"{response_text}\n\n📄 Document ready: {download_url}"
        except Exception:
            pass
        return response_text
    except Exception as e:
        return f"Error generating document: {e}"


@mcp.tool()
async def multi_hop_query(
    question: str,
    persona: str = "researcher",
) -> str:
    """
    Ask a complex cross-entity question requiring multi-step reasoning.

    Best for: 'Which floor has highest CO2?', 'Compare energy per zone', etc.

    Args:
        question: Complex natural-language question
        persona:  researcher, energy_manager, facility_manager, etc.
    """
    try:
        result = await _chat(question, persona=persona)
        return result.get("response") or result.get("formatted_response") or json.dumps(result)
    except Exception as e:
        return f"Error in multi-hop query: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────────────────────────────
# Entry point — supports stdio and SSE transport
# ────────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    async def _startup():
        await _login()

    asyncio.get_event_loop().run_until_complete(_startup())
    logger.info(
        f"OntoSage MCP Server starting "
        f"(orchestrator={ORCHESTRATOR_URL}, transport={MCP_TRANSPORT})"
    )

    if MCP_TRANSPORT == "sse":
        # SSE transport for remote / web integration
        logger.info(f"SSE mode: listening on {MCP_SSE_HOST}:{MCP_SSE_PORT}")
        try:
            mcp.run(transport="sse", host=MCP_SSE_HOST, port=MCP_SSE_PORT)
        except TypeError:
            # Some FastMCP versions don't support host/port directly; use env vars
            os.environ.setdefault("MCP_SSE_HOST", MCP_SSE_HOST)
            os.environ.setdefault("MCP_SSE_PORT", str(MCP_SSE_PORT))
            mcp.run(transport="sse")
    else:
        # Default: stdio for Claude Desktop / local clients
        mcp.run(transport="stdio")
