"""
Test suite for RAG Service
"""
import pytest
import httpx

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
    async def test_retrieve_tbox(self, client):
        """Test TBox retrieval from brick_schema"""
        response = await client.post("/retrieve", json={
            "query": "Brick temperature sensor",
            "collection": "brick_schema",
            "top_k": 5
        })
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert isinstance(data["results"], list)
        assert data["collection"] == "brick_schema"
    
    @pytest.mark.asyncio
    async def test_retrieve_abox(self, client):
        """Test ABox retrieval from building_instances"""
        response = await client.post("/retrieve", json={
            "query": "VAV box temperature sensor",
            "collection": "building_instances",
            "top_k": 5
        })
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert isinstance(data["results"], list)
        assert data["collection"] == "building_instances"

    @pytest.mark.asyncio
    async def test_embed_texts(self, client):
        """Test text embedding"""
        response = await client.post("/embed", json={
            "texts": ["This is a test sentence", "Another test"],
            "collection": "docs"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["count"] >= 1
    
    @pytest.mark.asyncio
    async def test_list_collections(self, client):
        """Test collections listing"""
        response = await client.get("/collections")
        assert response.status_code == 200
        data = response.json()
        assert "collections" in data
        assert isinstance(data["collections"], list)

    @pytest.mark.asyncio
    async def test_collection_stats(self, client):
        """Test collection stats endpoint"""
        response = await client.get("/collections/building_instances/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "building_instances"
        assert "points_count" in data

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
