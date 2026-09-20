"""
LLM Manager for OntoSage 2.0
Handles LLM interactions with support for Ollama and OpenAI
"""

import sys

sys.path.append("/app")

import asyncio
import contextvars
import json
import os
import re
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class TaskType(Enum):
    """Task type hint — routes to fast (gpt-4o-mini) or complex (gpt-5.4) model."""

    INTENT = "intent"
    GENERAL = "general"
    DISAMBIGUATION = "disambiguation"
    REWRITE = "rewrite"
    ANALYTICS = "analytics"
    SPARQL = "sparql"
    REPORT = "report"


# Task types that use the lightweight fast model.
_FAST_TASK_TYPES = {
    TaskType.INTENT,
    TaskType.GENERAL,
    TaskType.DISAMBIGUATION,
    TaskType.REWRITE,
    TaskType.SPARQL,
}

from orchestrator.services.circuit_breaker import circuit_breaker_for
from orchestrator.services.prompt_hygiene import strip_tracker_ids
from shared.config import get_llm_config, settings
from shared.utils import get_logger

logger = get_logger(__name__)

# Rate limiting for OpenAI
# gpt-4o-mini Tier-1: 500 RPM, Tier-2+: 5000 RPM
# Set conservatively at 1s; increase only if you hit 429 errors
OPENAI_RATE_LIMIT_DELAY = float(os.environ.get("OPENAI_RATE_LIMIT_DELAY", "1.0"))
OPENAI_RETRY_DELAY_S = float(os.environ.get("OPENAI_RETRY_DELAY_S", "20.0"))

# Retry / timeout configuration
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "3"))
LLM_TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "60"))
LLM_BACKOFF_BASE_S = float(os.environ.get("LLM_BACKOFF_BASE_S", "1.0"))
LLM_BACKOFF_FACTOR = float(os.environ.get("LLM_BACKOFF_FACTOR", "2.0"))


# How long to wait for a crashed LOCAL model runner to come back before retrying. Measured
# on this machine: llama-server reloads in 5.0-14.0s after a CUDA fault (CAVEAT-619).
LLM_RUNNER_RESTART_WAIT_S = float(os.environ.get("LLM_RUNNER_RESTART_WAIT_S", "10.0"))


#: The most tokens one LOCAL call may generate, reasoning included (CAVEAT-727).
#:
#: Unset, a local reasoning model that never reaches a stop token generates until the context
#: is full: measured 2026-09-17, 16,248 tokens in 161 s for a 136-token prompt, content EMPTY
#: (`truncated = 1`), and because the runner serves one request at a time the next user
#: waited 2m46s behind it. Over the 7,216 calls in the host log, 49 were such runaways and
#: only 6 real completions exceeded 8,192 tokens (p99 3,880), so the cap halves the stall and
#: hands the call to the retry path sooner while cutting almost nothing that finishes.
#: Hosted clients already carry max_tokens; this is the local equivalent. 0 = unlimited.
_OLLAMA_NUM_PREDICT_DEFAULT = 8192


def _ollama_generation_cap() -> Dict[str, int]:
    """num_predict for the local client from OLLAMA_NUM_PREDICT; empty when unlimited."""
    raw = os.environ.get("OLLAMA_NUM_PREDICT", "").strip()
    try:
        cap = int(raw) if raw else _OLLAMA_NUM_PREDICT_DEFAULT
    except ValueError:
        logger.warning(
            f"OLLAMA_NUM_PREDICT={raw!r} is not an integer; using {_OLLAMA_NUM_PREDICT_DEFAULT}"
        )
        cap = _OLLAMA_NUM_PREDICT_DEFAULT
    return {"num_predict": cap} if cap > 0 else {}


#: Characters per token used to size a prompt against the local model's window. Prose runs near
#: 4; sensor tables, identifiers and column lists run well below. 2.75 is the point at which the
#: one failure we measured (BUG-474: 45,573 characters against a 16k context) is caught while no
#: prompt that is known to work is touched.
_CHARS_PER_TOKEN = 2.75


def prompt_char_budget(num_ctx: Optional[int] = None) -> int:
    """The longest prompt, in characters, a local model with this window will actually read."""
    try:
        ctx = int(num_ctx or os.environ.get("OLLAMA_NUM_CTX", "8192") or 8192)
    except ValueError:
        ctx = 8192
    return int(ctx * _CHARS_PER_TOKEN)


def fit_prompt(prompt: Any, budget: int) -> Any:
    """Keep a prompt inside the model's window without losing either end of it.

    2026-09-18: a 64,436-character narration prompt went to a 16,384-token model. Ollama drops the
    FRONT of an overflowing prompt, so the instructions and the question vanished and the model
    saw only the tail — it answered with a developer ticket id, then with "I'm ready to help". An
    overflow never produces a worse answer, it produces a different question.

    Instructions sit at the start of every builder's prompt and the closing rules and "Response:"
    at the end; the bulk in between is data. So the MIDDLE is cut, and the cut says so in plain
    words, which is the one part of this that a model can act on. Prompts within budget — every
    one known to work — are returned unchanged (the same object).
    """
    if not isinstance(prompt, str) or budget <= 0 or len(prompt) <= budget:
        return prompt
    head = int(budget * 0.45)
    tail = int(budget * 0.45)
    omitted = len(prompt) - head - tail
    logger.warning(
        f"LLM prompt of {len(prompt):,} characters exceeds the {budget:,}-character budget for this "
        f"context; {omitted:,} characters of the middle are being omitted"
    )
    marker = (
        f"\n\n[... {omitted:,} characters of data were left out here to fit the model's context. "
        "Answer only from what is shown, and say the data was cut short ...]\n\n"
    )
    return prompt[:head] + marker + prompt[len(prompt) - tail :]


#: "User Query:" (or "Question:") with nothing after it before the next line. The prompt
#: builders all render the question under a label like this, so an empty one is detectable
#: without knowing which builder produced it.
_EMPTY_QUESTION_SLOT_RE = re.compile(
    r"^[ \t]*(?:user\s+query|question|user\s+question)\s*:[ \t]*$", re.IGNORECASE | re.MULTILINE
)


class EmptyCompletionError(RuntimeError):
    """The provider answered successfully but produced no text."""


def _looks_like_a_dead_local_runner(error: Optional[BaseException]) -> bool:
    """True when the error says the local runner process is gone, not merely slow.

    A refused connection to the provider's own loopback port means the model runner
    crashed and is being respawned — a different failure from a busy or slow server,
    and one that needs a longer wait rather than a faster retry.
    """
    if error is None:
        return False
    text = str(error).lower()
    return any(
        marker in text
        for marker in (
            "connection refused",
            "connectionrefused",
            "actively refused",  # the Windows wording of the same refusal
            "llama runner",
            "model runner has unexpectedly stopped",
        )
    )


# ── LLM degradation trace (V5-BUG-177) ───────────────────────────────────────
# When the provider refuses a call — a quota 429, a timeout, an open circuit —
# every caller falls back to a generic answer.  That answer looks like an
# ordinary reply, so an offline grader scores it as a BEHAVIOURAL result and the
# run reports a coverage/leak number that measures the outage, not the system.
# The per-request trace below lets the API mark such turns as faulted so graders
# can quarantine them instead of grading them.  Failures are appended to a
# mutable list held in a ContextVar: child asyncio tasks inherit the same list
# object, so nested node calls report into the request that spawned them.
_llm_failures: contextvars.ContextVar[Optional[List[Dict[str, Any]]]] = contextvars.ContextVar(
    "ontosage_llm_failures", default=None
)

RATE_LIMIT_MARKERS = ("429", "rate limit", "quota", "too many requests", "requires a subscription")


def classify_llm_error(error: BaseException) -> str:
    """Bucket an LLM failure into a cause a grader can act on."""
    text = str(error).lower()
    if any(m in text for m in RATE_LIMIT_MARKERS) or type(error).__name__ == "RateLimitError":
        return "rate_limit"
    if isinstance(error, EmptyCompletionError):
        return "empty_completion"
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)) or "timed out" in text:
        return "timeout"
    if "circuit breaker" in text:
        return "circuit_open"
    if "connection" in text:
        return "connection"
    return "other"


def begin_llm_trace() -> None:
    """Start recording LLM failures for the current request."""
    _llm_failures.set([])


def record_llm_failure(error: BaseException, client_label: str = "") -> None:
    """Note a terminal LLM failure against the in-flight request, if traced."""
    failures = _llm_failures.get()
    if failures is None:
        return  # untraced caller (script, test) — nothing to report
    failures.append(
        {
            "cause": classify_llm_error(error),
            "client": client_label,
            "detail": str(error)[:200],
        }
    )


def llm_degradation() -> Optional[Dict[str, Any]]:
    """Summarise this request's LLM failures, or None when the LLM behaved."""
    failures = _llm_failures.get()
    if not failures:
        return None
    causes = sorted({f["cause"] for f in failures})
    return {
        "failed_calls": len(failures),
        "causes": causes,
        # A quota refusal is the one cause the operator must act on, so name it.
        "rate_limited": "rate_limit" in causes,
        "detail": failures[0]["detail"],
    }


# ── Structured generation (ARCH-A1) ──────────────────────────────────────────
# Every lane that wants JSON from the model currently asks in prose, slices the
# first `{`..`}` out of whatever came back, and repairs what it finds. BUG-631 is
# the worst thing that shape produces: a malformed generation was rejected, a
# fallback answered about a different floor with a plausible number, and three
# verification layers saw nothing.
#
# The alternative is to hand the provider the schema and let IT constrain the
# generation, then validate what comes back and FAIL TYPED when it does not
# match. A typed failure is visible; a repair is not.


class StructuredGenerationError(RuntimeError):
    """A structured call could not produce an object matching its schema.

    ``stage`` says which half failed, because the two need different responses:

    * ``provider``  — the call itself never returned (timeout, quota, breaker).
                      An availability problem; the lane degrades as it always has.
    * ``decode``    — text came back and it was not JSON.
    * ``schema``    — JSON came back and it did not match the contract.

    The last two are the ones this component exists to make visible. They are
    raised, never repaired, so the caller's own honest-failure path runs instead
    of a plausible answer built from a half-understood object.
    """

    def __init__(
        self,
        schema_name: str,
        stage: str,
        detail: str,
        raw: str = "",
        attempts: int = 1,
    ) -> None:
        super().__init__(
            f"structured[{schema_name}] failed at {stage} after {attempts} attempt(s): {detail}"
        )
        self.schema_name = schema_name
        self.stage = stage
        self.detail = detail
        #: Truncated deliberately: this reaches logs, and a whole generation there is noise.
        self.raw = (raw or "")[:500]
        self.attempts = attempts


#: Per-schema tallies so "structured output helped" is a measurement, not a claim.
#:
#: calls / valid_first_try / retried / failed, plus `stripped_envelope` — the count of
#: responses that were only parseable after the surrounding prose was removed. That last
#: one is the honest measure of whether the provider is really constraining generation or
#: whether we are still doing what this component was built to stop.
_structured_stats: Dict[str, Dict[str, int]] = {}

_STRUCTURED_COUNTERS = ("calls", "valid_first_try", "retried", "failed", "stripped_envelope")


def _record_structured(schema_name: str, **counters: int) -> None:
    row = _structured_stats.setdefault(schema_name, {k: 0 for k in _STRUCTURED_COUNTERS})
    for key, value in counters.items():
        row[key] = row.get(key, 0) + int(value)


def structured_metrics() -> Dict[str, Dict[str, int]]:
    """A snapshot of the per-schema tallies. Copied, so a reader cannot mutate them."""
    return {name: dict(row) for name, row in _structured_stats.items()}


def reset_structured_metrics() -> None:
    """Clear the tallies (a harness measures one run, not the process lifetime)."""
    _structured_stats.clear()


#: The outermost brace-delimited span, used only when a strict parse fails.
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")


def _decode_json_object(text: str) -> Tuple[Optional[Dict[str, Any]], bool]:
    """(object, stripped_envelope) — or (None, …) when the text holds no JSON object.

    A strict parse is tried first. Only if that fails is the outermost ``{...}`` span
    taken, and that fact is REPORTED rather than absorbed: a provider that is really
    honouring the schema never needs it, so a rising `stripped_envelope` count is the
    signal that the schema is not reaching the provider at all.

    Nothing here rewrites, coerces or fills a field. That is the difference between
    decoding a response and repairing one.
    """
    raw = (text or "").strip()
    if not raw:
        return None, False
    try:
        parsed = json.loads(raw)
        return (parsed if isinstance(parsed, dict) else None), False
    except (json.JSONDecodeError, TypeError):
        pass
    match = _JSON_OBJECT_RE.search(raw)
    if not match:
        return None, False
    try:
        parsed = json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError):
        return None, True
    return (parsed if isinstance(parsed, dict) else None), True


def _schema_violation(instance: Dict[str, Any], schema: Dict[str, Any]) -> Optional[str]:
    """The first schema violation as a sentence, or None when the object conforms."""
    try:
        from jsonschema import Draft202012Validator
    except ImportError:  # pragma: no cover - jsonschema is a hard dependency
        logger.warning("jsonschema is not installed — structured output cannot be validated")
        return None
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    if not errors:
        return None
    first = errors[0]
    where = "/".join(str(p) for p in first.absolute_path) or "(root)"
    return f"at {where}: {first.message}"


class LLMManager:
    """Manages LLM interactions with multiple providers.

    Maintains two clients when MODEL_PROVIDER=openai:
      - client_fast: gpt-4o-mini for intent, SPARQL, general, rewrite, disambiguation
      - client:      primary model (e.g. gpt-5.4) for analytics, reports, compliance
    For local/cloud Ollama both point to the same model.
    """

    def __init__(self):
        self.config = get_llm_config()
        self.provider = self.config["provider"]
        self.client = None
        self.client_fast = None
        self.last_request_time = 0.0  # rate-limit tracker for complex model
        self.last_request_time_fast = 0.0  # rate-limit tracker for fast model
        self._breaker = circuit_breaker_for("llm", failure_threshold=5, recovery_timeout=30.0)
        self._initialize_client()

    def _initialize_client(self):
        """Initialize LLM client(s) based on provider."""
        if self.provider == "openai":
            self._initialize_openai()
        elif self.provider == "ollama_cloud":
            self._initialize_ollama_cloud()
        else:  # ollama
            self._initialize_ollama()

    def _initialize_openai(self):
        """Initialize OpenAI clients — complex model + fast model."""
        try:
            from langchain_openai import ChatOpenAI

            self.client = ChatOpenAI(
                model=self.config["model"],
                api_key=self.config["api_key"],
                temperature=self.config["temperature"],
                max_tokens=4096,
            )
            fast_model = self.config.get("model_fast", "gpt-4o-mini")
            self.client_fast = ChatOpenAI(
                model=fast_model,
                api_key=self.config["api_key"],
                temperature=self.config["temperature"],
                max_tokens=2048,
            )
            logger.info(
                f"Initialized OpenAI LLMs: complex={self.config['model']}, fast={fast_model}"
            )
        except ImportError:
            logger.error("langchain-openai not installed. Run: pip install langchain-openai")
            raise

    def _initialize_ollama(self):
        """Initialize Ollama client (single model for both fast and complex)."""
        try:
            from langchain_ollama import OllamaLLM

            # keep_alive keeps the model resident so it doesn't cold-reload (~16s) between
            # requests; num_ctx sets the context window. Both env-driven (building-agnostic).
            _keep_alive = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")
            _num_ctx = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))
            self.client = OllamaLLM(
                base_url=self.config["base_url"],
                model=self.config["model"],
                temperature=self.config["temperature"],
                keep_alive=_keep_alive,
                num_ctx=_num_ctx,
                **_ollama_generation_cap(),
            )
            self.client_fast = self.client  # same model
            logger.info(
                f"Ollama options: keep_alive={_keep_alive} num_ctx={_num_ctx} "
                f"num_predict={_ollama_generation_cap().get('num_predict', 'unlimited')}"
            )
            logger.info(
                f"Initialized Ollama LLM: {self.config['model']} at {self.config['base_url']}"
            )
        except ImportError:
            logger.error("langchain-ollama not installed. Run: pip install langchain-ollama")
            raise

    def _initialize_ollama_cloud(self):
        """Initialize Ollama Cloud client (OpenAI-compatible API, single model)."""
        try:
            from langchain_openai import ChatOpenAI

            self.client = ChatOpenAI(
                base_url=self.config["base_url"],
                model=self.config["model"],
                api_key=self.config["api_key"],
                temperature=self.config["temperature"],
                max_tokens=4096,
                **self._reasoning_kwargs(),
            )
            self.client_fast = self.client  # same model for cloud Ollama
            effort = self.config.get("reasoning_effort") or "provider default"
            logger.info(
                f"Initialized Ollama Cloud LLM: {self.config['model']} "
                f"at {self.config['base_url']} (thinking: {effort})"
            )
        except ImportError:
            logger.error("langchain-openai not installed. Run: pip install langchain-openai")
            raise

    def _reasoning_kwargs(self) -> Dict[str, Any]:
        """Thinking-depth kwargs for hosted models, empty when unconfigured.

        Reasoning models (gpt-oss, nemotron, minimax) keep their trace in a
        separate ``reasoning`` field, so raising the effort deepens deliberation
        without leaking chain-of-thought into the answer. Models that do not
        speak the parameter reject it outright, hence opt-in only.
        """
        effort = self.config.get("reasoning_effort") or ""
        return {"reasoning_effort": effort} if effort else {}

    def _pick_client(self, task_type: Optional[TaskType]):
        """Return (client, is_fast) based on task type."""
        use_fast = task_type in _FAST_TASK_TYPES
        return (self.client_fast, True) if use_fast else (self.client, False)

    def _fit_to_context(self, prompt: Any) -> Any:
        """Cap a prompt at the local model's window; a hosted provider's window is not ours to guess."""
        if getattr(self, "provider", "") == "openai":
            return prompt
        return fit_prompt(prompt, prompt_char_budget())

    def _is_retryable(self, error: Exception) -> bool:
        """Check if an error is transient and should be retried."""
        if isinstance(error, EmptyCompletionError):
            return True
        error_str = str(error).lower()
        # OpenAI rate limit (429) or server errors (500/502/503)
        if "rate limit" in error_str or "429" in error_str:
            return True
        if any(code in error_str for code in ["500", "502", "503", "server error", "overloaded"]):
            return True
        if "connection" in error_str or "timeout" in error_str:
            return True
        # Check for specific exception types
        error_type = type(error).__name__
        if error_type in (
            "RateLimitError",
            "APIConnectionError",
            "InternalServerError",
            "ServiceUnavailableError",
        ):
            return True
        return False

    async def generate(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: Optional[float] = None,
        task_type: Optional[TaskType] = None,
        provider_kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generate text from prompt with circuit breaker, retry, and timeout.

        Routes to the fast model (gpt-4o-mini) for intent/SPARQL/general tasks and
        to the complex model for analytics/reports.  Each client has its own
        rate-limit tracker so they don't block each other.

        Circuit breaker fast-fails when the LLM provider is unresponsive.
        Retries up to LLM_MAX_RETRIES times on transient errors (429, 5xx, connection
        errors) with exponential backoff. Each attempt is capped at LLM_TIMEOUT_S.

        ``provider_kwargs`` are passed straight to the underlying client call — the
        route by which `generate_structured` hands the provider a JSON schema. Empty
        (the default) leaves every existing caller byte-for-byte unchanged.
        """
        # A developer's pointer to the fix behind a rule ("...and stop (BUG-606)") must never
        # reach the model: it was echoed back as the whole answer to "How busy is the building
        # right now?". Every prompt built anywhere crosses this method, so it is stripped once,
        # here; the source keeps its citations, the model never sees them.
        prompt = strip_tracker_ids(prompt)
        system_message = strip_tracker_ids(system_message)
        prompt = self._fit_to_context(prompt)
        if not self._breaker.allow_request():
            open_err = RuntimeError(
                f"LLM circuit breaker is OPEN — the {self.provider} provider "
                f"has been unresponsive. Requests will resume automatically in "
                f"~{self._breaker.recovery_timeout:.0f}s."
            )
            record_llm_failure(open_err, "breaker")
            raise open_err

        active_client, is_fast = self._pick_client(task_type)
        client_label = "fast" if is_fast else "complex"

        # A PROMPT THAT LOST ITS QUESTION (BUG-630). "Is it too warm anywhere right now?"
        # came back, after 116 seconds, as "No question was provided." — the model's own
        # words, because the prompt it was handed carried an empty `User Query:` slot. That
        # is unreproducible after the fact and invisible in every log we keep: the lane logs
        # the query it RECEIVED, not the one it rendered.
        #
        # Every prompt passes through here, so the check lives here once rather than at each
        # of the seven builders. It only warns: a caller with a genuine reason to ask without
        # a question keeps working, and the next occurrence names itself.
        if _EMPTY_QUESTION_SLOT_RE.search(prompt or ""):
            import traceback

            _caller = "".join(traceback.format_stack(limit=4)[:2]).strip().replace("\n", " ")
            logger.warning(
                f"LLM [{client_label}] prompt carries an EMPTY question slot "
                f"({len(prompt or '')} chars) — the answer will say so. Called from: {_caller}"
            )

        last_error = None

        for attempt in range(1, LLM_MAX_RETRIES + 1):
            try:
                # Per-client rate limiting
                if self.provider in ["openai", "ollama_cloud"]:
                    current_time = time.time()
                    if is_fast:
                        elapsed = current_time - self.last_request_time_fast
                        if elapsed < OPENAI_RATE_LIMIT_DELAY:
                            await asyncio.sleep(OPENAI_RATE_LIMIT_DELAY - elapsed)
                        self.last_request_time_fast = time.time()
                    else:
                        elapsed = current_time - self.last_request_time
                        if elapsed < OPENAI_RATE_LIMIT_DELAY:
                            await asyncio.sleep(OPENAI_RATE_LIMIT_DELAY - elapsed)
                        self.last_request_time = time.time()

                result = await asyncio.wait_for(
                    self._generate_once(
                        prompt,
                        system_message,
                        temperature,
                        active_client,
                        provider_kwargs=provider_kwargs,
                    ),
                    timeout=LLM_TIMEOUT_S,
                )
                if not (result or "").strip():
                    # A local model that spends its whole budget on reasoning, or one
                    # whose prompt crowds out the context window, returns an empty
                    # completion with HTTP 200.  Callers parse that as a failed
                    # response and fall back to a generic answer, so treat it as the
                    # transient failure it is rather than a valid result.
                    raise EmptyCompletionError(
                        f"LLM [{client_label}] returned an empty completion "
                        f"(prompt was {len(prompt)} chars)"
                    )
                self._breaker.record_success()
                return result

            except asyncio.TimeoutError:
                last_error = TimeoutError(f"LLM [{client_label}] timed out after {LLM_TIMEOUT_S}s")
                logger.warning(
                    f"LLM [{client_label}] timeout (attempt {attempt}/{LLM_MAX_RETRIES})"
                )
                self._breaker.record_failure()
            except Exception as e:
                last_error = e
                self._breaker.record_failure()
                if not self._is_retryable(e) or attempt == LLM_MAX_RETRIES:
                    logger.error(
                        f"LLM [{client_label}] error (attempt {attempt}, non-retryable): {e}",
                        exc_info=True,
                    )
                    record_llm_failure(e, client_label)
                    raise
                logger.warning(
                    f"LLM [{client_label}] retryable error (attempt {attempt}/{LLM_MAX_RETRIES}): {e}"
                )

            if attempt < LLM_MAX_RETRIES:
                backoff = LLM_BACKOFF_BASE_S * (LLM_BACKOFF_FACTOR ** (attempt - 1))
                if self.provider in ["openai", "ollama_cloud"]:
                    backoff = max(backoff, OPENAI_RETRY_DELAY_S)
                elif _looks_like_a_dead_local_runner(last_error):
                    # The local model runner DIED and is reloading (CAVEAT-619). Ollama
                    # spawns a fresh llama-server on a new port and takes ~5-14s to answer
                    # again; 1s and 2s backoffs all land inside that window, so all three
                    # attempts fail and a correct register answer degrades to "I couldn't
                    # summarise them". Wait out the restart instead of racing it.
                    backoff = max(backoff, LLM_RUNNER_RESTART_WAIT_S)
                logger.info(f"LLM [{client_label}] retry backoff: {backoff:.1f}s")
                await asyncio.sleep(backoff)

        final_error = last_error or RuntimeError("LLM generation failed after all retries")
        record_llm_failure(final_error, client_label)
        raise final_error

    # Injected into every LLM call to prevent language drift
    _LANGUAGE_INSTRUCTION = "Always respond in English, regardless of the language used in the user's message or any prior context."

    async def _generate_once(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: Optional[float] = None,
        client=None,
        provider_kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Single LLM call without retry logic. Uses provided client or falls back to self.client."""
        active = client if client is not None else self.client
        extra = dict(provider_kwargs or {})

        if system_message:
            effective_system = f"{self._LANGUAGE_INSTRUCTION}\n\n{system_message}"
        else:
            effective_system = self._LANGUAGE_INSTRUCTION

        if self.provider in ["openai", "ollama_cloud"]:
            try:
                from langchain.schema import HumanMessage as HumMsg
                from langchain.schema import SystemMessage as SysMsg
            except ImportError:
                from langchain_core.messages import HumanMessage as HumMsg
                from langchain_core.messages import SystemMessage as SysMsg

            messages = [SysMsg(content=effective_system), HumMsg(content=prompt)]
            invoke_kwargs = {}
            if temperature is not None:
                invoke_kwargs["temperature"] = temperature
            invoke_kwargs.update(extra)
            response = await active.ainvoke(messages, **invoke_kwargs)
            return response.content

        else:  # ollama (local)
            full_prompt = f"System: {effective_system}\n\nUser: {prompt}"
            response = await active.ainvoke(full_prompt, **extra)
            return response

    def _structured_provider_kwargs(
        self, schema: Dict[str, Any], schema_name: str
    ) -> Dict[str, Any]:
        """The kwargs that make THIS provider constrain its generation to ``schema``.

        Measured against the installed clients on 2026-09-17, not assumed:

        * **local Ollama** — `ollama` 0.6.1 types `generate(format=...)` as
          ``Union[Literal['', 'json'], JsonSchemaValue]``, so a schema dict is accepted.
          `langchain-ollama` 0.2.3 still types its own `format` FIELD as
          ``Literal['', 'json']``, so the schema cannot be set on the client — but
          `OllamaLLM._generate_params` does ``kwargs.pop("format", self.format)``, and a
          per-call kwarg reaches it through `ainvoke`. Hence a per-call kwarg, not a
          constructor argument.
        * **openai / ollama_cloud** — `langchain-openai` 0.2.14 forwards unknown invoke
          kwargs into the request payload, and supports the
          ``{"type": "json_schema", "json_schema": {...}}`` response format.

        An empty dict (an unrecognised provider) is not an error: the call still runs
        and validation still decides. The schema is then advisory rather than enforced,
        which is exactly what the `stripped_envelope` tally makes visible.
        """
        if self.provider in ("openai", "ollama_cloud"):
            return {
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "schema": schema,
                        # `strict` demands a closed schema (every property required,
                        # additionalProperties false). Ours are deliberately permissive
                        # so the flag can only ADD guarantees, never reject a response
                        # the current path would have accepted.
                        "strict": False,
                    },
                }
            }
        return {"format": schema}

    async def generate_structured(
        self,
        prompt: str,
        schema: Dict[str, Any],
        *,
        schema_name: str = "unnamed",
        system_message: Optional[str] = None,
        temperature: Optional[float] = None,
        task_type: Optional[TaskType] = None,
    ) -> Dict[str, Any]:
        """Ask the provider for an object matching ``schema``; validate it; never repair it.

        One retry, and only one: the validation error is appended to the prompt so the
        model is told what was wrong with its own answer. A second failure raises
        `StructuredGenerationError` — the caller then runs its honest-failure path
        instead of building an answer out of a half-understood object.

        Returns the validated object. Records per call: schema name, valid-first-try,
        retried, failed (see `structured_metrics`).
        """
        prompt = strip_tracker_ids(prompt)  # see `generate`: tracker ids never reach the model
        system_message = strip_tracker_ids(system_message)
        prompt = self._fit_to_context(prompt)
        provider_kwargs = self._structured_provider_kwargs(schema, schema_name)
        _record_structured(schema_name, calls=1)

        attempt_prompt = prompt
        last_detail = ""
        last_raw = ""
        for attempt in (1, 2):
            try:
                raw = await self.generate(
                    attempt_prompt,
                    system_message=system_message,
                    temperature=temperature,
                    task_type=task_type,
                    provider_kwargs=provider_kwargs,
                )
            except Exception as exc:
                # An availability failure is NOT a schema failure and must not be
                # counted as one — `generate` has already retried and traced it.
                _record_structured(schema_name, failed=1)
                raise StructuredGenerationError(
                    schema_name, "provider", str(exc), attempts=attempt
                ) from exc

            last_raw = raw
            obj, stripped = _decode_json_object(raw)
            if stripped:
                _record_structured(schema_name, stripped_envelope=1)
            if obj is None:
                stage, last_detail = "decode", "response contained no JSON object"
            else:
                violation = _schema_violation(obj, schema)
                if violation is None:
                    if attempt == 1:
                        _record_structured(schema_name, valid_first_try=1)
                    return obj
                stage, last_detail = "schema", violation

            if attempt == 1:
                _record_structured(schema_name, retried=1)
                logger.warning(
                    f"[structured:{schema_name}] {stage} failure — retrying once: {last_detail}"
                )
                attempt_prompt = (
                    f"{prompt}\n\nYour previous answer was rejected — {last_detail}.\n"
                    f"Return ONLY a JSON object that satisfies the required shape."
                )
                continue

            _record_structured(schema_name, failed=1)
            logger.error(
                f"[structured:{schema_name}] {stage} failure after one retry: {last_detail}"
            )
            raise StructuredGenerationError(
                schema_name, stage, last_detail, raw=last_raw, attempts=2
            )

        # Unreachable: the loop either returns or raises on attempt 2.
        raise StructuredGenerationError(
            schema_name, "schema", last_detail, raw=last_raw, attempts=2
        )

    async def astream_generate(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: Optional[float] = None,
        task_type: Optional[TaskType] = None,
    ):
        """Stream generated text. Routes to fast or complex client based on task_type."""
        prompt = strip_tracker_ids(prompt)  # see `generate`: tracker ids never reach the model
        system_message = strip_tracker_ids(system_message)
        prompt = self._fit_to_context(prompt)
        try:
            active_client, _ = self._pick_client(task_type)

            if system_message:
                effective_system = f"{self._LANGUAGE_INSTRUCTION}\n\n{system_message}"
            else:
                effective_system = self._LANGUAGE_INSTRUCTION

            if self.provider in ["openai", "ollama_cloud"]:
                try:
                    from langchain.schema import HumanMessage as HumMsg
                    from langchain.schema import SystemMessage as SysMsg
                except ImportError:
                    from langchain_core.messages import HumanMessage as HumMsg
                    from langchain_core.messages import SystemMessage as SysMsg

                messages = [SysMsg(content=effective_system), HumMsg(content=prompt)]
                stream_kwargs = {}
                if temperature is not None:
                    stream_kwargs["temperature"] = temperature
                async for chunk in active_client.astream(messages, **stream_kwargs):
                    yield chunk.content

            else:  # ollama (local)
                full_prompt = f"System: {effective_system}\n\nUser: {prompt}"
                async for chunk in active_client.astream(full_prompt):
                    yield chunk

        except Exception as e:
            logger.error(f"LLM streaming generation failed: {e}")
            yield f"Error: {str(e)}"

    async def generate_with_examples(
        self, prompt: str, examples: List[Dict[str, str]], system_message: Optional[str] = None
    ) -> str:
        """
        Generate with few-shot examples

        Args:
            prompt: User prompt
            examples: List of {"input": ..., "output": ...} examples
            system_message: Optional system message

        Returns:
            Generated text
        """
        # Build few-shot prompt
        few_shot_prompt = ""

        if system_message:
            few_shot_prompt += f"{system_message}\n\n"

        few_shot_prompt += "Examples:\n\n"

        for i, example in enumerate(examples, 1):
            few_shot_prompt += f"Example {i}:\n"
            few_shot_prompt += f"Input: {example['input']}\n"
            few_shot_prompt += f"Output: {example['output']}\n\n"

        few_shot_prompt += f"Now, for the following input:\n{prompt}\n\nOutput:"

        return await self.generate(few_shot_prompt)

    def get_client(self):
        """Get underlying LangChain client"""
        return self.client

    def get_info(self) -> Dict[str, Any]:
        """Get LLM information"""
        return {
            "provider": self.provider,
            "model": self.config.get("model"),
            "model_fast": self.config.get("model_fast"),
            "base_url": self.config.get("base_url"),
            "temperature": self.config.get("temperature"),
        }


# Global instance
llm_manager = LLMManager()
