# Cloud Ollama Setup Guide

## 🌩️ Quick Switch Between Local and Cloud Models

OntoSage 2.0 now supports **three LLM providers**:

1. **Local Ollama** (default) - Free, runs on your GPU
2. **Cloud Ollama** (NEW) - Fast cloud inference with Ollama API
3. **OpenAI** - GPT-4/GPT-3.5 models

---

## ⚡ Switch to Cloud Ollama (Fast Response!)

### Option 1: Environment Variable (Temporary)

```bash
# Windows PowerShell
$env:MODEL_PROVIDER="cloud"
docker-compose -f docker-compose.agentic.yml restart orchestrator

# Linux/Mac
MODEL_PROVIDER=cloud docker-compose -f docker-compose.agentic.yml restart orchestrator
```

### Option 2: Edit .env File (Permanent)

Open `.env` file and change:

```env
# FROM:
MODEL_PROVIDER=local

# TO:
MODEL_PROVIDER=cloud
```

Then restart:
```bash
docker-compose -f docker-compose.agentic.yml restart orchestrator
```

---

## 🔑 Cloud Ollama Configuration

Your cloud Ollama settings are already configured in `.env`:

```env
# Cloud Ollama API (alternative to local Ollama)
OLLAMA_CLOUD_API_KEY=2cc44a30514f4c7ba01d9ca4a276e499.Wf8tWmThMQn9bGmiLEBqPm4n
OLLAMA_CLOUD_BASE_URL=https://api.ollama.ai/v1
OLLAMA_CLOUD_MODEL=gpt-oss:120b-cloud
```

**API Key**: Already set (your provided key)  
**Model**: `gpt-oss:120b-cloud` (120 billion parameter model)  
**Endpoint**: Ollama Cloud API (OpenAI-compatible)

---

## 📊 Provider Comparison

| Feature | Local Ollama | Cloud Ollama | OpenAI |
|---------|--------------|--------------|--------|
| **Speed** | 2-3 min/query | ~5-10 sec | ~5-10 sec |
| **Cost** | FREE | Pay per token | Pay per token |
| **Model** | deepseek-r1:32b | gpt-oss:120b | gpt-4-turbo |
| **Privacy** | 100% local | Cloud | Cloud |
| **GPU Required** | Yes (NVIDIA) | No | No |
| **Setup** | Complex | Simple | Simple |

---

## 🧪 Test Cloud Ollama

### 1. Switch to Cloud Mode

Edit `.env`:
```env
MODEL_PROVIDER=cloud
```

### 2. Restart Orchestrator

```bash
docker-compose -f docker-compose.agentic.yml restart orchestrator
```

### 3. Check Logs

```bash
docker logs ontosage-orchestrator --tail 20
```

You should see:
```
Initialized Ollama Cloud LLM: gpt-oss:120b-cloud at https://api.ollama.ai/v1
```

### 4. Test Query

Open http://localhost:3000 and ask:
```
What is the location of the Abacws building?
```

**Expected**: Response in ~5-10 seconds (vs 2-3 minutes with local model)

---

## 🔄 Switch Back to Local

Edit `.env`:
```env
MODEL_PROVIDER=local
```

Restart:
```bash
docker-compose -f docker-compose.agentic.yml restart orchestrator
```

---

## ⚙️ Advanced Configuration

### Change Cloud Model

Edit `.env`:
```env
# Use different cloud model
OLLAMA_CLOUD_MODEL=llama3.1:70b
# or
OLLAMA_CLOUD_MODEL=mixtral:8x7b
```

### Adjust Temperature

Edit `shared/config.py`:
```python
OPENAI_TEMPERATURE: float = Field(default=0.1)  # 0.0 = deterministic, 1.0 = creative
```

### Use Different API Endpoint

Edit `.env`:
```env
OLLAMA_CLOUD_BASE_URL=https://your-custom-endpoint.com/v1
```

---

## 🐛 Troubleshooting

### Issue: "Authentication required" or 401 errors

**Solution**: Verify API key in `.env`
```bash
# Check if key is set
docker exec ontosage-orchestrator printenv | grep OLLAMA_CLOUD
```

### Issue: Still slow responses

**Solution**: Confirm cloud mode is active
```bash
docker logs ontosage-orchestrator --tail 50 | grep "Initialized"
```

Should show:
```
Initialized Ollama Cloud LLM: gpt-oss:120b-cloud
```

NOT:
```
Initialized Ollama LLM: deepseek-r1:32b
```

### Issue: Model not found

**Solution**: Check available models at Ollama Cloud:
```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  https://api.ollama.ai/v1/models
```

---

## 💡 Best Practices

### For Development/Testing:
- Use **Local Ollama** (free, private)
- Accept slower responses

### For Demos/Production:
- Use **Cloud Ollama** (fast, reliable)
- Budget for API costs

### For Maximum Performance:
- Use **Cloud Ollama** with streaming enabled
- Monitor API usage/costs

---

## 📝 Environment Variables Reference

```env
# ==================== MODEL PROVIDER SELECTION ====================
MODEL_PROVIDER=cloud              # Options: local, cloud, openai

# ==================== LOCAL OLLAMA ====================
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=deepseek-r1:32b

# ==================== CLOUD OLLAMA ====================
OLLAMA_CLOUD_API_KEY=2cc44a30514f4c7ba01d9ca4a276e499.Wf8tWmThMQn9bGmiLEBqPm4n
OLLAMA_CLOUD_BASE_URL=https://api.ollama.ai/v1
OLLAMA_CLOUD_MODEL=gpt-oss:120b-cloud

# ==================== OPENAI (ALTERNATIVE) ====================
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4-turbo-preview
OPENAI_TEMPERATURE=0.1
```

---

## 🚀 Quick Commands

```bash
# Use cloud Ollama (FAST)
echo "MODEL_PROVIDER=cloud" >> .env
docker-compose -f docker-compose.agentic.yml restart orchestrator

# Use local Ollama (FREE)
echo "MODEL_PROVIDER=local" >> .env
docker-compose -f docker-compose.agentic.yml restart orchestrator

# Check current provider
docker logs ontosage-orchestrator 2>&1 | grep "Initialized.*LLM"

# View all environment variables
docker exec ontosage-orchestrator printenv | grep -E "MODEL_PROVIDER|OLLAMA"
```

---

**✅ Setup Complete!** You can now switch between local and cloud models anytime by changing `MODEL_PROVIDER` in `.env`.
