"""
Test suite for OntoSage 2.0 Orchestrator
"""

import json
import uuid
from typing import Any, Dict

import httpx
import pytest

BASE_URL = "http://localhost:8000"


class TestOrchestrator:
    """Test Orchestrator endpoints"""

    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test health endpoint"""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=300.0) as client:
            response = await client.get("/health")
            assert response.status_code == 200
            body = response.json()
            assert body["success"] is True
            data = body["data"]
            assert data["status"] == "healthy"
            assert "redis" in data["services"]

    async def _get_auth_headers(self, client):
        """Helper to register/login and get auth headers"""
        username = f"testuser_{uuid.uuid4().hex[:8]}"
        password = "testpassword123!"

        # Register
        await client.post("/auth/register", json={"username": username, "password": password})

        # Login
        response = await client.post(
            "/auth/login", json={"username": username, "password": password}
        )
        if response.status_code != 200:
            return None

        body = response.json()
        if not body.get("success"):
            return None

        token = body["data"]["session_token"]
        return {"Authorization": f"Bearer {token}"}

    @pytest.mark.asyncio
    async def test_chat_greeting(self):
        """Test greeting intent"""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=300.0) as client:
            headers = await self._get_auth_headers(client)
            assert headers is not None, "Failed to authenticate"

            response = await client.post(
                "/chat", json={"message": "Hello", "persona": "general"}, headers=headers
            )

            assert response.status_code == 200
            body = response.json()
            assert body["success"] is True
            data = body["data"]
            assert "conversation_id" in data
            assert "response" in data

    @pytest.mark.asyncio
    async def test_chat_sparql_query(self):
        """Test SPARQL query generation"""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=300.0) as client:
            headers = await self._get_auth_headers(client)

            response = await client.post(
                "/chat",
                json={"message": "Show me all temperature sensors", "persona": "researcher"},
                headers=headers,
            )

            assert response.status_code == 200
            body = response.json()
            assert body["success"] is True

    @pytest.mark.asyncio
    async def test_chat_sql_query(self):
        """Test SQL query generation"""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=300.0) as client:
            headers = await self._get_auth_headers(client)

            response = await client.post(
                "/chat",
                json={
                    "message": "What was the average temperature yesterday?",
                    "persona": "facility_manager",
                },
                headers=headers,
            )

            assert response.status_code == 200
            body = response.json()
            assert body["success"] is True

    @pytest.mark.asyncio
    async def test_chat_analytics(self):
        """Test analytics code generation"""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=300.0) as client:
            headers = await self._get_auth_headers(client)

            response = await client.post(
                "/chat",
                json={
                    "message": "Analyze temperature trends over the last week",
                    "persona": "researcher",
                },
                headers=headers,
            )

            assert response.status_code == 200
            body = response.json()
            assert body["success"] is True

    @pytest.mark.asyncio
    async def test_chat_visualization(self):
        """Test visualization generation"""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=300.0) as client:
            headers = await self._get_auth_headers(client)

            response = await client.post(
                "/chat",
                json={"message": "Create a line chart of temperature data", "persona": "student"},
                headers=headers,
            )

            assert response.status_code == 200
            body = response.json()
            assert body["success"] is True

    @pytest.mark.asyncio
    async def test_conversation_history(self):
        """Test conversation retrieval"""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=300.0) as client:
            headers = await self._get_auth_headers(client)

            # First, create a conversation
            response = await client.post("/chat", json={"message": "Hello"}, headers=headers)
            body = response.json()
            conversation_id = body["data"]["conversation_id"]

            # Retrieve conversation
            response = await client.get(f"/conversation/{conversation_id}", headers=headers)
            assert response.status_code == 200
            data = response.json()
            assert "messages" in data or ("data" in data and "messages" in data.get("data", {}))

    @pytest.mark.asyncio
    async def test_persona_switching(self):
        """Test persona switching"""
        personas = ["student", "researcher", "facility_manager", "general"]

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=300.0) as client:
            headers = await self._get_auth_headers(client)

            for persona in personas:
                response = await client.post(
                    "/chat",
                    json={"message": f"I'm a {persona}", "persona": persona},
                    headers=headers,
                )
                assert response.status_code == 200
                body = response.json()
                assert body["success"] is True

    @pytest.mark.asyncio
    async def test_preferences_update(self):
        """Test user preferences update"""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=300.0) as client:
            headers = await self._get_auth_headers(client)

            # Create conversation
            response = await client.post("/chat", json={"message": "Hello"}, headers=headers)
            body = response.json()
            conversation_id = body["data"]["conversation_id"]

            # Update preferences
            response = await client.post(
                "/preferences",
                json={
                    "conversation_id": conversation_id,
                    "persona": "researcher",
                    "language": "en",
                    "building": "building1",
                },
                headers=headers,
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
