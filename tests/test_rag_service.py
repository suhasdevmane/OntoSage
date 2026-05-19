"""
Test suite for RAG Service
"""

import httpx
import pytest

BASE_URL = "http://localhost:8001"


@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
        yield client


class TestRAGService:
    """Test RAG Service endpoints"""

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """Test health endpoint"""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_retrieve_brick_tbox(self, client):
        """Test GraphDB TBox retrieval — returns SPARQL triples for ontology terms"""
        response = await client.post(
            "/graphdb/retrieve",
            json={"query": "Brick temperature sensor", "collection": "brick_schema", "top_k": 5},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "triples" in data
        assert isinstance(data["triples"], list)
        assert "query" in data

    @pytest.mark.asyncio
    async def test_retrieve_building_instances(self, client):
        """Test GraphDB ABox retrieval — returns building instance triples"""
        response = await client.post(
            "/graphdb/retrieve",
            json={
                "query": "VAV box temperature sensor",
                "collection": "building_instances",
                "top_k": 5,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "triples" in data
        assert isinstance(data["triples"], list)

    @pytest.mark.asyncio
    async def test_retrieve_returns_summary(self, client):
        """Test that retrieve response includes a natural language summary"""
        response = await client.post(
            "/graphdb/retrieve",
            json={"query": "CO2 sensors", "top_k": 3},
        )
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data

    @pytest.mark.asyncio
    async def test_retrieve_returns_prefixes(self, client):
        """Test that retrieve response includes SPARQL prefix declarations"""
        response = await client.post(
            "/graphdb/retrieve",
            json={"query": "humidity sensor", "top_k": 3},
        )
        assert response.status_code == 200
        data = response.json()
        assert "prefixes" in data
        assert "prefix_declarations" in data
        assert isinstance(data["prefixes"], dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
