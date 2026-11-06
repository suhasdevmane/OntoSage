"""
OntoSage MCP Server — Model Context Protocol interface for smart building AI
==============================================================================
Exposes OntoSage as MCP tools so Claude Desktop, Cursor and other MCP clients can ask the
building questions, request reports and check compliance.

Architecture:
  A thin proxy that turns MCP tool calls into requests to the OntoSage orchestrator. Every
  answer goes through the same pipeline, RBAC and evidence checks as the chat interface.

How it signs in to the orchestrator (BUG-1695, fixed 2026-11-05 — it called /auth/token, which
does not exist, and sent an X-API-Key header nothing reads, so every tool returned an error):
  MCP_USERNAME + MCP_PASSWORD  → POST /auth/login, then /chat with that account's role.
                                 Use a non-admin account (e.g. facility_manager): any local
                                 process that can reach this server asks as that account.
  MCP_PIPELINE_KEY             → /v1/chat/completions with the pipeline key (the path Open
                                 WebUI uses). MCP_AUTH_TOKEN is read as an alias.

Transport (MCP_TRANSPORT):
  stdio            — default when run by hand for Claude Desktop.
  streamable-http  — what docker-compose runs: listens on MCP_HOST:MCP_PORT (8003), endpoint /mcp.
  sse              — legacy HTTP transport, endpoint /sse.

Tools: query_building, get_sensor_list, get_sensor_data, generate_report, check_compliance,
check_standards_batch, generate_document, multi_hop_query, get_building_info.
Resources: building://info, building://sensor-catalog.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, Optional

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ontosage-mcp")

ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8000")
MCP_USERNAME = os.environ.get("MCP_USERNAME", "")
MCP_PASSWORD = os.environ.get("MCP_PASSWORD", "")
MCP_PIPELINE_KEY = os.environ.get("MCP_PIPELINE_KEY", "") or os.environ.get("MCP_AUTH_TOKEN", "")
MCP_DEFAULT_PERSONA = os.environ.get("MCP_DEFAULT_PERSONA", "general")
MCP_TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio")  # stdio | streamable-http | sse
MCP_HOST = os.environ.get("MCP_HOST", os.environ.get("MCP_SSE_HOST", "127.0.0.1"))
MCP_PORT = int(os.environ.get("MCP_PORT", os.environ.get("MCP_SSE_PORT", "8003")))
#: One conversation per server process, so a follow-up ("and on floor 3?") has its context.
_CONVERSATION_ID = f"mcp-{uuid.uuid4().hex[:12]}"

mcp = FastMCP(
    "OntoSage Smart Building",
    instructions=(
        "Ask a smart building about its sensors, rooms, records and documents in plain English. "
        "Answers are computed from the building's own data and say when something is unknown."
    ),
    host=MCP_HOST,
    port=MCP_PORT,
)

_session_token: Optional[str] = None


async def _login() -> bool:
    """Sign in with MCP_USERNAME / MCP_PASSWORD; True when a session token was obtained."""
    global _session_token
    if not (MCP_USERNAME and MCP_PASSWORD):
        return False
    try:
        async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=15) as client:
            resp = await client.post(
                "/auth/login", json={"username": MCP_USERNAME, "password": MCP_PASSWORD}
            )
        body = resp.json() if resp.content else {}
        token = (body.get("data") or {}).get("session_token")
        if resp.status_code == 200 and token:
            _session_token = token
            logger.info("MCP: signed in to the orchestrator as %s", MCP_USERNAME)
            return True
        logger.warning("MCP: sign-in failed (HTTP %s): %s", resp.status_code, body.get("error"))
    except Exception as e:  # never crash the server on a sign-in problem; the tools report it
        logger.warning("MCP: sign-in error: %s", e)
    return False


def _no_credentials_message() -> str:
    return (
        "The MCP server has no orchestrator credentials. Set MCP_USERNAME and MCP_PASSWORD "
        "(an OntoSage account), or MCP_PIPELINE_KEY (the orchestrator's PIPELINE_API_KEY)."
    )


async def _chat(
    message: str, persona: str = MCP_DEFAULT_PERSONA, building_id: Optional[str] = None
) -> Dict[str, Any]:
    """Ask the orchestrator; return {"response": text, "download_url": str} whichever path ran."""
    global _session_token
    if MCP_USERNAME and MCP_PASSWORD:
        if not _session_token:
            await _login()
        payload: Dict[str, Any] = {
            "message": message,
            "persona": persona,
            "conversation_id": _CONVERSATION_ID,
        }
        if building_id:
            payload["building_id"] = building_id
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {_session_token}"} if _session_token else {}
            async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=420) as client:
                resp = await client.post("/chat", json=payload, headers=headers)
            if resp.status_code == 401 and attempt == 1 and await _login():
                continue  # the session lapsed; one fresh sign-in, then give up
            resp.raise_for_status()
            body = resp.json()
            data = body.get("data") or {}
            if not body.get("success", True) and not data.get("response"):
                raise RuntimeError(body.get("error") or "the orchestrator returned no answer")
            return {
                "response": data.get("response") or data.get("message") or "",
                "download_url": data.get("download_url") or "",
            }
    if MCP_PIPELINE_KEY:
        body = {
            "model": "ontosage",
            "stream": False,
            "messages": [{"role": "user", "content": message}],
        }
        headers = {
            "Authorization": f"Bearer {MCP_PIPELINE_KEY}",
            "X-OpenWebUI-Chat-Id": _CONVERSATION_ID,
        }
        async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=420) as client:
            resp = await client.post("/v1/chat/completions", json=body, headers=headers)
        resp.raise_for_status()
        out = resp.json()
        text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        return {"response": text, "download_url": ""}
    raise RuntimeError(_no_credentials_message())


def _text(result: Dict[str, Any]) -> str:
    text = result.get("response") or ""
    if result.get("download_url"):
        text += f"\n\nDownload: {result['download_url']}"
    return text or "(the orchestrator returned an empty answer)"


# ─────────────────────────────────────────────────────────────────────────────
# MCP Tools
# ─────────────────────────────────────────────────────────────────────────────


@mcp.tool()
async def query_building(question: str, persona: str = "general", building_id: str = "") -> str:
    """Ask any natural-language question about the smart building.

    Examples: "How many sensors are in room 5.01?", "What is the average CO2 level on floor 2?",
    "Show me the temperature trend in room 2.01 over the last 24 hours".

    Args:
        question: The question to ask about the building
        persona: Response framing — general, facility_manager, executive, researcher, student,
            occupant, energy_manager, safety_officer, sustainability_officer, it_admin
        building_id: Optional building ID (one building is served at a time)
    """
    try:
        return _text(await _chat(question, persona=persona, building_id=building_id or None))
    except Exception as e:
        return f"Error querying building: {e}"


@mcp.tool()
async def get_sensor_list(filter: str = "") -> str:
    """Discover the sensors in the building, optionally filtered ("temperature", "floor 2")."""
    query = (
        f"List all {filter} sensors" if filter else "What sensors are available in the building?"
    )
    try:
        return _text(await _chat(query, persona="it_admin"))
    except Exception as e:
        return f"Error listing sensors: {e}"


@mcp.tool()
async def get_sensor_data(sensor_name: str, time_range: str = "last 24 hours") -> str:
    """Fetch readings for a sensor or quantity ("CO2 in room 2.01") over a time range."""
    try:
        return _text(
            await _chat(f"Show me {sensor_name} data for {time_range}", persona="researcher")
        )
    except Exception as e:
        return f"Error fetching sensor data: {e}"


@mcp.tool()
async def generate_report(
    report_type: str = "summary", format: str = "markdown", topic: str = ""
) -> str:
    """Generate a building report (summary, anomaly, compliance, trend) in markdown, csv or pdf."""
    query = f"Generate a {report_type} report"
    if topic:
        query += f" on {topic}"
    if format and format != "markdown":
        query += f" as {format}"
    try:
        return _text(await _chat(query, persona="facility_manager"))
    except Exception as e:
        return f"Error generating report: {e}"


@mcp.tool()
async def check_compliance(standard: str = "ashrae55", zone: str = "") -> str:
    """Check the building (or one zone) against a standard: ashrae55, well, en15251, breeam, iso50001."""
    query = f"Check {standard} compliance" + (f" for {zone}" if zone else "")
    try:
        return _text(await _chat(query, persona="sustainability_officer"))
    except Exception as e:
        return f"Error checking compliance: {e}"


@mcp.tool()
async def check_standards_batch(zone: str = "", standards: str = "all") -> str:
    """Check compliance against several standards at once (comma-separated ids, or 'all')."""
    standard_list = ["breeam", "well_v2", "ashrae55", "en15251", "iso50001"]
    if standards and standards != "all":
        standard_list = [s.strip() for s in standards.split(",") if s.strip()]
    results = {}
    for std in standard_list:
        try:
            res = await _chat(
                f"Check {std} compliance" + (f" for {zone}" if zone else ""),
                persona="sustainability_officer",
            )
            results[std] = res.get("response") or "No result"
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
    """Generate a formal document (pdf, docx or html); the answer carries its download link."""
    query = (
        f"Generate a {document_type} report as {output_format}"
        + (f" titled '{title}'" if title else "")
        + f" for {time_range}"
    )
    try:
        return _text(await _chat(query, persona=persona))
    except Exception as e:
        return f"Error generating document: {e}"


@mcp.tool()
async def multi_hop_query(question: str, persona: str = "researcher") -> str:
    """Ask a question that needs several steps, e.g. 'Which floor has the highest CO2?'."""
    try:
        return _text(await _chat(question, persona=persona))
    except Exception as e:
        return f"Error in multi-hop query: {e}"


@mcp.tool()
async def get_building_info() -> str:
    """Get the orchestrator's health and the active building."""
    try:
        async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=10) as client:
            resp = await client.get("/health")
            resp.raise_for_status()
            return json.dumps(resp.json(), indent=2)
    except Exception as e:
        return f"Error fetching building info: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# MCP Resources
# ─────────────────────────────────────────────────────────────────────────────


@mcp.resource("building://info")
async def building_info_resource() -> str:
    """Building health status and metadata."""
    return await get_building_info()


@mcp.resource("building://sensor-catalog")
async def sensor_catalog_resource() -> str:
    """Sensor types with counts, as the building model states them."""
    try:
        return _text(await _chat("List all sensor types with counts", persona="it_admin"))
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if MCP_USERNAME and MCP_PASSWORD:
        asyncio.run(_login())
    elif not MCP_PIPELINE_KEY:
        logger.warning("MCP: %s", _no_credentials_message())
    logger.info(
        "OntoSage MCP server starting (orchestrator=%s, transport=%s%s)",
        ORCHESTRATOR_URL,
        MCP_TRANSPORT,
        f", {MCP_HOST}:{MCP_PORT}" if MCP_TRANSPORT != "stdio" else "",
    )
    if MCP_TRANSPORT not in ("stdio", "sse", "streamable-http"):
        raise SystemExit(
            f"MCP_TRANSPORT must be stdio, sse or streamable-http (got {MCP_TRANSPORT!r})"
        )
    mcp.run(transport=MCP_TRANSPORT)
