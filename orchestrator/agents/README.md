# OntoSage 2.0 - LLM Agent Configuration

This directory contains the `.env` file for OpenAI API credentials used by all agents.

## Quick Start

### Option 1: Use Local Ollama (Default)
```bash
# In root .env file
MODEL_PROVIDER=local
OLLAMA_MODEL=deepseek-r1:32b
OLLAMA_BASE_URL=http://ollama:11434
```

No additional configuration needed. The system uses local Ollama by default.

### Option 2: Use OpenAI API
```bash
# 1. Set MODEL_PROVIDER in root .env
MODEL_PROVIDER=openai

# 2. Add credentials to orchestrator/agents/.env
OPENAI_API_KEY=sk-proj-your-key-here
OPENAI_MODEL=gpt-4o-mini
```

## Configuration Files

### Root `.env` (Main Configuration)
- `MODEL_PROVIDER`: Choose `local` (Ollama) or `openai` (OpenAI API)
- `OLLAMA_MODEL`: Local model name (e.g., `deepseek-r1:32b`, `mistral:latest`)
- `OPENAI_TEMPERATURE`: LLM temperature (default: 0.1)

### `orchestrator/agents/.env` (OpenAI Credentials)
```dotenv
OPENAI_API_KEY=sk-proj-your-actual-key-here
OPENAI_MODEL=gpt-4o-mini  # or gpt-4, gpt-4-turbo, etc.
```

**Note**: This file is mounted as read-only in Docker and used only when `MODEL_PROVIDER=openai`

## Supported Models

### Local (Ollama)
- `deepseek-r1:32b` - Current production model (requires GPU)
- `mistral:latest` - Lightweight alternative
- `llama2:latest` - Meta's open model
- Any model from Ollama library

### OpenAI
- `gpt-4o-mini` - Cost-effective, fast (Recommended)
- `gpt-4o` - Latest GPT-4 optimized
- `gpt-4-turbo` - High performance
- `gpt-4` - Flagship model
- `gpt-3.5-turbo` - Fast and cheap

## How Agents Use LLMs

All agents (`sparql_agent`, `analytics_agent`, `dialogue_agent`, etc.) use the shared `LLMManager`:

```python
from orchestrator.llm_manager import llm_manager

# Automatically uses correct provider based on MODEL_PROVIDER
response = await llm_manager.generate(prompt)
```

The `LLMManager` automatically:
1. Reads `MODEL_PROVIDER` from environment
2. Loads OpenAI credentials from `agents/.env` if needed
3. Initializes the correct LangChain client (Ollama or OpenAI)
4. Handles temperature, model selection, and API calls

## Analytics Flag Logic

The SPARQL agent now uses **improved analytics decision logic**:

### `analytics=false` (SPARQL results ARE the final answer)
- Queries for structural/metadata information
- Examples:
  - "List all sensors"
  - "What is the UUID of sensor X?"
  - "Where is equipment Y located?"

### `analytics=true` (SPARQL results need FURTHER PROCESSING)
- Queries for computed values from time-series data
- Queries for real-time sensor readings
- Examples:
  - **"What temperature sensors are in room 5.01?"** → Returns sensor metadata, needs actual temperature data
  - "What is the average CO2 level?" → Needs to compute from readings
  - "Which rooms have high CO2?" → Needs to compare values against threshold

**Key Insight**: Most sensor queries require `analytics=true` because users want DATA/VALUES, not just metadata!

## Token Optimization

The new prompts only include **necessary prefixes** instead of all 27:

**Before** (Old Prompt):
```sparql
PREFIX br: <http://vocab.deri.ie/br#>
PREFIX bl: <https://w3id.org/biolink/vocab/>
PREFIX bld: <http://biglinkeddata.com/>
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
... (21 more prefixes)
```

**After** (New Prompt):
```sparql
# Only include what's actually used:
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX bldg: <http://abacwsbuilding.cardiff.ac.uk/abacws#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
```

**Savings**: ~70% reduction in prompt tokens!

## Switching Providers During Development

You can easily switch between providers without rebuilding:

```bash
# Test with OpenAI
echo "MODEL_PROVIDER=openai" >> .env
docker-compose -f docker-compose.agentic.yml restart orchestrator

# Back to local Ollama
echo "MODEL_PROVIDER=local" >> .env
docker-compose -f docker-compose.agentic.yml restart orchestrator
```

## Troubleshooting

### "OpenAI API key required" error
- Ensure `OPENAI_API_KEY` is set in `orchestrator/agents/.env`
- Verify the key is not expired
- Check the key starts with `sk-proj-` or `sk-`

### Model not found
- For Ollama: Run `docker exec -it ollama-deepseek-r1 ollama list`
- For OpenAI: Check model name matches available models

### Slow responses
- Local Ollama: Normal, especially for large models
- OpenAI: Check internet connection and API rate limits

## Cost Comparison

### Local Ollama
- **Cost**: FREE
- **Speed**: 2-5 seconds per response (GPU)
- **Privacy**: All data stays local

### OpenAI (gpt-4o-mini)
- **Cost**: ~$0.15 per 1M input tokens, ~$0.60 per 1M output tokens
- **Speed**: 0.5-2 seconds per response
- **Privacy**: Data sent to OpenAI

**Recommendation**: Develop with OpenAI (fast iteration), deploy with Ollama (no costs)

## Conversation Memory Enhancement

OntoSage 2.0 now includes **conversation memory** to understand follow-up queries.

### How It Works

The system maintains conversation history in Redis and includes the last 5 messages in agent prompts:

```python
# Automatically formatted for each query
Previous Conversation:
User: what temperature sensors are in room 5.01?
Assistant: I found a total of 34 temperature sensors in room 5.01...
```

### Features

1. **Follow-up Query Detection**
   - Recognizes phrases like: "all of them", "detailed list", "complete list", "show all"
   - Inherits intent from previous successful query (SPARQL, SQL, Analytics)

2. **Context-Aware Clarification**
   - When requesting clarification, the system references previous conversation
   - Example: "give me all" → System understands this refers to previous sensor list

3. **Enhanced SPARQL Generation**
   - LLM receives conversation history in prompts
   - Can generate queries based on previous results
   - Understands references like "those sensors", "the same room"

### Example Conversation Flow

```
User: what temperature sensors are in room 5.01?
Assistant: I found 34 temperature sensors in room 5.01...
         [Shows organized list by zones]

User: give me all detailed list
Assistant: [System detects follow-up, inherits SPARQL intent]
         Here's the complete list of all 34 sensors:
         - Air_Temperature_Sensor_5.01 (West Zone, UUID: abc123...)
         - Air_Temperature_Sensor_5.02 (West Zone, UUID: def456...)
         ...
```

### Configuration

Conversation memory is enabled by default. You can adjust the context window:

```python
# In dialogue_agent.py / sparql_agent.py
conversation_history = format_conversation_history(state.messages, max_messages=5)
```

- **max_messages=5**: Include last 5 messages (default)
- **max_messages=3**: Shorter context (faster, cheaper)
- **max_messages=10**: Longer context (better memory, more tokens)

### Implementation Details

**Files Modified**:
- `dialogue_agent.py`: Added `format_conversation_history()` helper
- `dialogue_agent.py`: Enhanced `request_clarification()` with conversation context
- `dialogue_agent.py`: Enhanced `detect_intent()` to recognize follow-up queries
- `sparql_agent.py`: Added conversation history to SPARQL generation prompts

**Key Functions**:
```python
def format_conversation_history(messages: List[Message], max_messages: int = 5) -> str:
    \"\"\"Format recent conversation for LLM context\"\"\"
    # Returns formatted string: "Previous Conversation:\nUser: ...\nAssistant: ..."

async def detect_intent(state: ConversationState) -> str:
    \"\"\"Detect intent with follow-up query awareness\"\"\"
    # Recognizes follow-ups and inherits intent from previous query

async def _generate_sparql(..., conversation_history: str = "") -> Dict[str, Any]:
    \"\"\"Generate SPARQL with conversation context\"\"\"
    # Includes history in prompt for context-aware query generation
```

### Testing Conversation Memory

**Manual Test via Frontend**:
1. Open http://localhost:3000 in browser
2. Ask: "what temperature sensors are in room 5.01?"
3. Wait for response with sensor list
4. Follow up: "can you give me all detailed list?"
5. System should understand and provide complete list without asking for clarification

**Expected Behavior**:
- ✅ System recognizes "detailed list" refers to previous query
- ✅ Generates appropriate SPARQL query for all sensors
- ✅ Returns complete formatted results
- ❌ Does NOT ask "what do you mean by detailed list?"

### Benefits

- **Better UX**: Natural conversation flow
- **Fewer Clarifications**: System understands context
- **Efficient**: No need to repeat full queries
- **Smart**: Inherits intent from previous interactions

