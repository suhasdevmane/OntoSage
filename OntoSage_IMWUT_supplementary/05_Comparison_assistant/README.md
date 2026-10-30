# Comparison assistant (Assistant B)

Supports §5.3 (The comparison assistant). Assistant B answers a question about the building with the same model and gateway as OntoSage+ and with seven tools that wrap OntoSage+'s own services, but it receives the rules for using evidence only in its prompt, with no checks in code. We froze its prompt and code before the study; no participant used it.

## Files

| File | What it is |
|---|---|
| `prompt.txt` | The prompt with its nine rules, byte for byte as frozen (`prompts/v1.txt`). |
| `settings.md` | Model, temperature, token budget, reasoning effort, the limit of eight tool calls, and the other limits. |
| `tools/tool_definitions.json` | The seven tool definitions exactly as sent to the model. |
| `tools/README.md` | What each tool takes and returns, and which OntoSage+ service it wraps. |
| `code/instructed_baseline/` | The code as frozen: `tools.py` (the seven tools), `native.py` (the tool-calling loop that produced every study answer), `loop.py` (a step-by-step JSON loop that produced no study answer; `native.py` imports two constants from it), `run.py` (runs a batch of questions inside the OntoSage+ container), `launch.py` (starts `run.py` there from the host), `run_comparison.py` (asks both systems the same question back to back), `parity_check.py` (the pre-study check below), `__init__.py`. |

**The prompt as the model received it.** For every study answer, `native.py` sent `prompt.txt` as the system message with its last line, "Respond with one JSON object per step, as specified.", replaced by "Use the tools to look things up, then answer in plain text." The user message was "Today's date: " followed by the date, a blank line and the question.

## Checking that this is the code that ran

Each Assistant B answer in the offline runs records two hashes (`08_Data/post_development_study/offline_runs/runs/*.jsonl`, under `result`):

- `prompt_sha` = `f64a49224ed78a53`: the first 16 hexadecimal digits of the SHA-256 of the prompt text;
- `code_sha` = `f5a30640a5d07466`: the same over the bytes of `tools.py`, `loop.py`, `native.py` and `prompts/v1.txt`, in that order (`run.py`, `code_sha`).

Both values come out of the files in `code/instructed_baseline/`. From that folder:

```
python -c "import hashlib; h = hashlib.sha256(); [h.update(open(f, 'rb').read()) for f in ('tools.py', 'loop.py', 'native.py', 'prompts/v1.txt')]; print(h.hexdigest()[:16])"
python -c "import hashlib; print(hashlib.sha256(open('prompts/v1.txt', encoding='utf-8').read().encode('utf-8')).hexdigest()[:16])"
```

The first prints `code_sha`; the second prints `prompt_sha`, computed as `run.py` does on the text as Python reads it.

The four files keep the Windows line endings with which they ran; converting the line endings changes `code_sha`. The same files are in the repository at the frozen commit (`scripts/instructed_baseline/`), stored with Unix line endings, for which the first command prints `6cd2595c103f6da2`; a Windows checkout that converts line endings reproduces `f5a30640a5d07466`. The second command prints the same `prompt_sha` either way.

## Before the study: the parity check

`parity_check.py` asked whether Assistant B's tools retrieved every fact each of four development tasks needs, in at least two of three runs, whatever its final answer said. The facts are read from the development forms' keys in the frozen task bank. Assistant B passed on all four (§5.3).

## How the comparison was run

`run_comparison.py` here and the study's drivers in `06_Analysis_scripts/post_development_study/` (`make_e6_inputs.py` draws the question sets, `e6_run.py` runs them, `e6_rerun_pf.py` re-runs a provider failure once, `e6_aminus.py` runs A-minus) ask both systems the same question back to back, in a seeded order, with every cache flushed before each answer (§5.3). The answers are in `08_Data/post_development_study/offline_runs/`.

## Edits for anonymity

- `run_comparison.py`: the model name sent to OntoSage+'s chat endpoint, which was the chat interface's name for the assistant, became `[anonymised]`.
- `parity_check.py`: a folder name in the path to the task bank became `[anonymised]`.

No other file was changed; the four hashed files are byte-identical to those that ran. The comments in the code are as written at the time: "spec" and "tracker" refer to the authors' design notes, and "pre-registered" means the study plan approved before the first session, which was not registered publicly (§5).
