from fastapi import FastAPI, HTTPException
import httpx
import os

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama-deepseek-r1:11434")
MODEL_NAME = os.environ.get("OLLAMA_MODEL", "deepseek-r1:32b")

app = FastAPI(title="Ollama Health", version="1.0.0")

async def fetch(client: httpx.AsyncClient, path: str):
    url = f"{OLLAMA_BASE_URL}{path}"
    r = await client.get(url, timeout=30)
    r.raise_for_status()
    return r.json()

@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient() as client:
            tags = await fetch(client, "/api/tags")
            version = await fetch(client, "/api/version")
        return {"status": "ok", "version": version.get("version"), "models": tags.get("models", [])}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Ollama unreachable: {e}")

@app.get("/status")
async def status():
    # Detailed model presence & lightweight generation dry-run
    async with httpx.AsyncClient() as client:
        try:
            tags = await fetch(client, "/api/tags")
            model_ids = [m.get("name") for m in tags.get("models", [])]
            present = MODEL_NAME in model_ids
            info = {"present": present, "configured_model": MODEL_NAME, "available_models": model_ids}
            if present:
                # Dry-run generate (empty prompt) to verify endpoint without heavy allocation
                gen_payload = {"model": MODEL_NAME, "prompt": "", "stream": False}
                gen_resp = await client.post(f"{OLLAMA_BASE_URL}/api/generate", json=gen_payload, timeout=60)
                if gen_resp.status_code == 200:
                    info["generate_ready"] = True
                else:
                    info["generate_ready"] = False
                    info["generate_error_code"] = gen_resp.status_code
            return info
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Status check failed: {e}")

@app.get("/")
async def root():
    return {"service": "ollama-health", "endpoints": ["/health", "/status"], "model": MODEL_NAME}
