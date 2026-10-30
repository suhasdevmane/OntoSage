# Assistant B: settings

The settings with which Assistant B produced every study answer. Each value is read from the frozen code and the study's configuration; the run records confirm the mode, the model and the two hashes (`README.md`). Keys and endpoint addresses are left out.

| Setting | Value | Where it is set |
|---|---|---|
| Mode | Native tool calling on an OpenAI-compatible chat-completions endpoint; every run record says `native_tools` | `run.py` chooses this mode when the model is served by the hosted gateway |
| Model | `gpt-oss:20b`, served by the same gateway as OntoSage+ | the configuration's `HOSTED_LLM_MODEL`; recorded in every run record |
| Temperature | 0 on every call | `native.py`, `Provider` (`temperature = 0.0`) |
| Token budget | `max_tokens` = 4,096 per call. If the model's reasoning used the whole budget and it returned neither text nor a tool call, the call was repeated once with 8,192 | `HOSTED_LLM_MAX_TOKENS` (the code default; the configuration does not override it); `native.py`, `Provider.chat` |
| Reasoning effort | None set: no `reasoning_effort` parameter was sent, so the gateway's default applied | `native.py` sends it only if the configuration names one; the configuration named none |
| Tool calls | At most 8 per question. After the eighth, the model was called once more with tools disabled (`tool_choice` "none") and had to answer | `native.py`, `MAX_STEPS = 8` |
| Time limit | 300 s per question, checked before each model call; each request also had a client deadline of 660 s | `native.py`, `TIME_LIMIT_S`; the configuration's `HOSTED_LLM_TIMEOUT_S` |
| Tool results | Each result sent to the model as JSON, cut to 6,000 characters with the cut stated; a time-series query is capped at 400,000 rows, and reaching the cap is reported | `tools.py`, `RESULT_BUDGET`, `ROW_LIMIT` |
| Messages | System: `prompt.txt` with its last line replaced (`README.md`). User: "Today's date: " followed by the date, a blank line and the question | `native.py`, `answer` |
| Caches | OntoSage+'s four answer caches were flushed before every question, for both systems | `run.py`, `run_comparison.py` |
| Building | The same building, graph and stores as OntoSage+; namespace, building identifier and time zone come from OntoSage+'s settings | `tools.py`, `Toolbox.live` |
