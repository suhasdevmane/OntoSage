"""
Test suite for Code Executor
"""
import pytest
import httpx

BASE_URL = "http://localhost:8002"

@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
        yield client

class TestCodeExecutor:
    """Test Code Executor endpoints"""
    
    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """Test health endpoint"""
        response = await client.get("/health")
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_simple_execution(self, client):
        """Test simple code execution"""
        code = """
print("Hello, World!")
result = 2 + 2
print(f"2 + 2 = {result}")
"""
        response = await client.post("/execute", json={"code": code})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "output" in data
        assert "Hello, World!" in data["output"]
    
    @pytest.mark.asyncio
    async def test_pandas_execution(self, client):
        """Test pandas code execution"""
        code = """
import pandas as pd
import numpy as np

data = {'A': [1, 2, 3], 'B': [4, 5, 6]}
df = pd.DataFrame(data)
print(df.describe())
"""
        response = await client.post("/execute", json={"code": code})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
    
    @pytest.mark.asyncio
    async def test_unsafe_code_blocked(self, client):
        """Test that unsafe code is blocked"""
        code = """
import os
os.system('ls')
"""
        response = await client.post("/execute", json={"code": code})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "error" in data
    
    @pytest.mark.asyncio
    async def test_code_validation(self, client):
        """Test code syntax validation"""
        response = await client.post("/validate", json={
            "code": "print('valid')"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        
        response = await client.post("/validate", json={
            "code": "print('invalid'"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
