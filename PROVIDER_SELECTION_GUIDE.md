# 🚀 OntoSage 2.0 - Model Provider Selection Guide

## Overview

OntoSage 2.0 now supports **three model providers** with easy switching:

1. **🖥️ Local Ollama** - FREE, runs on your GPU (slow but private)
2. **☁️ Cloud Ollama** - FAST cloud inference via Ollama API (recommended)
3. **🌐 OpenAI** - Industry-standard GPT-4 models

---

## 📊 Quick Comparison

| Feature | Local | Cloud | OpenAI |
|---------|-------|-------|--------|
| **Model** | deepseek-r1:32b | gpt-oss:120b-cloud | gpt-4-turbo |
| **Speed** | 🐌 2-3 min | ⚡ 5-10 sec | ⚡ 5-10 sec |
| **Cost** | 💰 FREE | 💳 Pay/token | 💳 $0.01/1K |
| **Privacy** | 🔒 100% Local | ☁️ Cloud | ☁️ Cloud |
| **GPU** | ✅ Required | ❌ Not needed | ❌ Not needed |
| **Setup** | Complex | API key only | API key only |

---

## 🎯 Method 1: Interactive Startup Script (Recommended)

The easiest way to start OntoSage with your choice of provider.

### Usage

```powershell
# Run the interactive script
.\start-ontosage.ps1
```

**What it does:**
1. Shows provider comparison table
2. Lets you choose: Local (1), Cloud (2), or OpenAI (3)
3. Validates API keys (if needed)
4. Stops existing services
5. Starts services with selected provider
6. Performs health checks
7. Shows access URLs

### Command-Line Options

```powershell
# Start with cloud provider directly
.\start-ontosage.ps1 -Provider cloud

# Start local without rebuilding images (faster)
.\start-ontosage.ps1 -Provider local -SkipBuild

# Stop all services
.\start-ontosage.ps1 -StopOnly
```

---

## 🔄 Method 2: Quick Switcher (Fastest)

Switch providers **without restarting all services** - only restarts orchestrator!

### Usage

```powershell
# Switch to cloud (5-10 sec restart)
.\switch-provider.ps1 cloud

# Switch to local (5-10 sec restart)
.\switch-provider.ps1 local

# Switch to OpenAI
.\switch-provider.ps1 openai
```

**What it does:**
1. Validates API key (if needed)
2. Updates `.env` file
3. Restarts only the orchestrator service
4. Verifies provider in logs
5. Done in ~15 seconds!

---

## 🖱️ Method 3: Batch Files (Double-Click)

Simplest method - just double-click!

### Local Mode
```
Double-click: start-local.bat
```

### Cloud Mode
```
Double-click: start-cloud.bat
```

---

## ⚙️ Method 4: Manual Setup

For advanced users who want full control.

### Step 1: Edit `.env` File

Open `.env` and find line 52:

```env
# Change this line:
MODEL_PROVIDER=local     # Current setting

# To one of these:
MODEL_PROVIDER=local     # Option 1: Local Ollama (FREE, slow)
MODEL_PROVIDER=cloud     # Option 2: Cloud Ollama (FAST, paid) ⭐
MODEL_PROVIDER=openai    # Option 3: OpenAI GPT-4 (FAST, paid)
```

### Step 2: Ensure API Keys (if using cloud/openai)

**For Cloud Ollama (line ~450):**
```env
OLLAMA_CLOUD_API_KEY=2cc44a30514f4c7ba01d9ca4a276e499.Wf8tWmThMQn9bGmiLEBqPm4n
OLLAMA_CLOUD_BASE_URL=https://api.ollama.ai/v1
OLLAMA_CLOUD_MODEL=gpt-oss:120b-cloud
```

**For OpenAI (line ~93):**
```env
OPENAI_API_KEY=sk-your-actual-key-here
OPENAI_MODEL=gpt-4-turbo-preview
OPENAI_TEMPERATURE=0.1
```

### Step 3: Restart Services

```powershell
# Full restart (all services)
docker-compose -f docker-compose.agentic.yml down
docker-compose -f docker-compose.agentic.yml up -d

# Quick restart (orchestrator only)
docker-compose -f docker-compose.agentic.yml restart orchestrator
```

---

## 🧪 Verify Your Setup

### Check Current Provider

```powershell
# View orchestrator logs
docker logs ontosage-orchestrator --tail 20

# Look for one of these:
# ✅ Local:  "Initialized Ollama LLM: deepseek-r1:32b at http://ollama:11434"
# ✅ Cloud:  "Initialized Ollama Cloud LLM: gpt-oss:120b-cloud at https://api.ollama.ai/v1"
# ✅ OpenAI: "Initialized OpenAI LLM: gpt-4-turbo-preview"
```

### Test Query

1. Open http://localhost:3000
2. Ask: "What is the location of the Abacws building?"
3. Measure response time:
   - **Local**: 2-3 minutes
   - **Cloud/OpenAI**: 5-10 seconds

---

## 📁 File Reference

| File | Purpose |
|------|---------|
| `start-ontosage.ps1` | Interactive startup with provider selection |
| `switch-provider.ps1` | Fast provider switching (orchestrator only) |
| `start-local.bat` | Double-click to start local mode |
| `start-cloud.bat` | Double-click to start cloud mode |
| `.env` | Configuration file (MODEL_PROVIDER setting) |
| `docker-compose.agentic.yml` | Main service definitions |
| `docker-compose.override.yml` | Provider-specific overrides |

---

## 🔧 Troubleshooting

### Issue: "API key not found" (Cloud/OpenAI)

**Solution:**
```powershell
# Edit .env file and add your API key
notepad .env

# For Cloud Ollama:
OLLAMA_CLOUD_API_KEY=your-actual-key-here

# For OpenAI:
OPENAI_API_KEY=sk-your-actual-key-here
```

### Issue: Local Ollama slow or not responding

**Solution:**
```powershell
# Check if model is loaded
docker exec ollama-deepseek-r1 ollama list

# If missing, pull it:
docker exec ollama-deepseek-r1 ollama pull deepseek-r1:32b

# Check GPU usage:
docker exec ollama-deepseek-r1 nvidia-smi
```

### Issue: Cloud Ollama authentication error

**Solution:**
```powershell
# Verify API key format (should be 32+ hex characters)
Get-Content .env | Select-String "OLLAMA_CLOUD_API_KEY"

# Test API endpoint directly:
curl -H "Authorization: Bearer YOUR_KEY" https://api.ollama.ai/v1/models
```

### Issue: Services not starting

**Solution:**
```powershell
# Check service status
docker-compose -f docker-compose.agentic.yml ps

# View logs for specific service
docker-compose -f docker-compose.agentic.yml logs orchestrator

# Full restart
docker-compose -f docker-compose.agentic.yml down
docker-compose -f docker-compose.agentic.yml up -d
```

---

## 💡 Best Practices

### For Development/Testing
- Use **Local Ollama** (FREE)
- Accept slower response times
- No API costs
- 100% private data

### For Demos/Presentations
- Use **Cloud Ollama** (FAST)
- 5-10 second responses
- Budget for API costs
- Reliable and consistent

### For Production
- Use **Cloud Ollama** or **OpenAI**
- Enable monitoring
- Set usage limits
- Configure rate limiting

---

## 📈 Performance Tips

### Local Ollama Optimization

```env
# In .env file:
OLLAMA_NUM_GPU=1
OLLAMA_GPU_LAYERS=-1          # Use all GPU layers
OLLAMA_KEEP_ALIVE=24h         # Keep model in VRAM
OLLAMA_NUM_CTX=4096          # Context window
```

### Cloud Ollama Optimization

```env
# In .env file:
OLLAMA_CLOUD_MODEL=gpt-oss:120b-cloud  # Larger = better quality
OPENAI_TEMPERATURE=0.1                  # Lower = more deterministic
```

### OpenAI Optimization

```env
# In .env file:
OPENAI_MODEL=gpt-4-turbo-preview  # Latest model
OPENAI_TEMPERATURE=0.1             # Precise answers
```

---

## 🔐 Security Notes

### API Key Safety

1. **Never commit .env to Git**
   ```bash
   # Already in .gitignore
   .env
   ```

2. **Rotate keys regularly**
   - Cloud Ollama: Every 90 days
   - OpenAI: Every 90 days or on suspected breach

3. **Monitor usage**
   - Cloud Ollama: Check dashboard
   - OpenAI: https://platform.openai.com/usage

### Local vs Cloud Privacy

| Aspect | Local | Cloud |
|--------|-------|-------|
| Query data | Stays on server | Sent to API |
| Ontology data | Private | Private (not sent) |
| Sensor data | Private | Private (not sent) |
| Model weights | Downloaded once | Hosted remotely |

---

## 📚 Additional Resources

- **OntoSage Documentation**: `README.md`
- **Cloud Ollama Setup**: `CLOUD_OLLAMA_SETUP.md`
- **Docker Compose Guide**: `docker-compose.agentic.yml` (see comments)
- **Troubleshooting**: `TROUBLESHOOTING.md`

---

## 🎯 Quick Reference Commands

```powershell
# Start with interactive menu
.\start-ontosage.ps1

# Quick switch to cloud (15 sec)
.\switch-provider.ps1 cloud

# Quick switch to local (15 sec)
.\switch-provider.ps1 local

# Check current provider
docker logs ontosage-orchestrator --tail 20 | Select-String "Initialized"

# View all logs
docker-compose -f docker-compose.agentic.yml logs -f

# Stop everything
docker-compose -f docker-compose.agentic.yml down

# Full restart
docker-compose -f docker-compose.agentic.yml restart
```

---

**✅ You're all set!** Choose your preferred method above and start OntoSage 2.0 with your desired model provider.

For questions, check the troubleshooting section or view service logs.
