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
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple


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

#: Log a completed LLM call at WARNING once it has taken this long (BUG-1191).
#:
#: A 3,239-second call was found by reading two adjacent log lines and subtracting their
#: timestamps by hand, because nothing recorded a duration. p50 on this stack is 4.5 s and
#: the slowest legitimate lane measured 83.6 s, so 60 s flags the tail without narrating
#: ordinary work.
LLM_SLOW_CALL_WARN_S = float(os.environ.get("LLM_SLOW_CALL_WARN_S", "60"))


def _transport_timeout_s() -> float:
    """Seconds after which the HTTP CLIENT abandons an LLM request, independent of asyncio.

    `generate` already wraps every attempt in `asyncio.wait_for(LLM_TIMEOUT_S)`. On
    2026-09-30 that bound did not bind: a single call ran 3,239 s with no TimeoutError and
    no retry, and the 420 s `WORKFLOW_TIMEOUT_S` wrapped around it was equally silent
    (BUG-1191). Two independent deadlines written in the same idiom failing on the same
    turn is not two bugs in `wait_for`; it is a loop that was not running its timer
    callbacks, on a process that was later measured at 40 GiB (BUG-1194).

    So a second deadline is set in a different place. The default deliberately OUTLASTS
    `LLM_TIMEOUT_S`, so under a healthy loop `wait_for` still fires first and every
    existing retry path behaves exactly as before; this one only acts when that one did
    not. It also covers `astream_generate`, which has no `wait_for` at all -- though that
    method has NO CALLERS today, checked rather than assumed, so that is future cover and
    not a hole being closed.

    MEASURED end to end on 2026-09-30, inside the running container, against a socket that
    accepts the connection and never writes a byte -- BUG-1191's exact shape:

        WITHOUT client_kwargs: still hanging at 40.0s, no deadline fired
        WITH    client_kwargs: ReadTimeout('') after 12.0s

    Note the empty message on that exception. It is why `_is_retryable` and
    `classify_llm_error` match these by TYPE NAME: a text check would have bucketed a
    transport timeout as "other" and refused to retry it.

    HONEST LIMIT, stated because the alternative is a false sense of cover: httpx
    implements its own timeouts with anyio, which on the asyncio backend is still an
    event-loop timer. This layer catches a silent provider on a healthy loop -- which is
    the shape actually observed, since the connection was open and nothing arrived for 54
    minutes. It does not survive a fully starved loop. The memory ceiling on the container
    is what covers that case.

    NOT THE HOSTED PROVIDER. This derivation is sized for a local call that generates
    and then answers; a hosted request can sit in the gateway's queue for minutes before
    the first byte, and 105 s would abandon it there. The hosted client takes
    HOSTED_LLM_TIMEOUT_S instead (see `LLMManager._initialize_hosted`).
    """
    raw = (os.environ.get("LLM_TRANSPORT_TIMEOUT_S") or "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            logger.warning(f"LLM_TRANSPORT_TIMEOUT_S={raw!r} is not a number; deriving instead")
    return LLM_TIMEOUT_S * 1.5 + 15.0


#: Seconds the outer `asyncio.wait_for` on a hosted attempt outlasts HOSTED_LLM_TIMEOUT_S.
#: The client's own deadline should fire first, as a typed and retryable error; the outer one
#: is the backstop for a loop that is not running its timers (BUG-1191).
_HOSTED_OUTER_MARGIN_S = 30.0


def _hosted_timeout_s() -> float:
    """The client deadline for one hosted request, queue time included (HOSTED_LLM_TIMEOUT_S)."""
    return float(settings.HOSTED_LLM_TIMEOUT_S)


def _hosted_budget(requested: Any = None) -> int:
    """max_tokens for a hosted call: the configured floor, or more if a caller asked for more.

    A reasoning model spends this budget on hidden reasoning before any visible text, so
    a value below the floor can return an empty answer with HTTP 200. Every hosted call is
    sized through here, and `_generate_once` is the one place a hosted call is sent.
    """
    try:
        asked = int(requested or 0)
    except (TypeError, ValueError):
        asked = 0
    return max(int(settings.HOSTED_LLM_MAX_TOKENS), asked)


def _ollama_client_kwargs() -> Dict[str, Any]:
    """`client_kwargs` for OllamaLLM that give its httpx clients a real deadline.

    MEASURED against the installed packages on 2026-09-30, not assumed: `ollama` 0.6.3's
    `BaseClient.__init__` types `timeout` as `Any` defaulting to **None** and hands it
    straight to httpx -- so out of the box an Ollama request has NO transport timeout at
    all. `langchain_ollama` 0.2.3 carries a `client_kwargs` field and does
    `Client(host=..., **client_kwargs)` / `AsyncClient(host=..., **client_kwargs)`, so a
    timeout set here reaches both.
    """
    total = _transport_timeout_s()
    timeout: Any = total
    try:
        import httpx

        # Connect must be short: a refused or unroutable model server is a fast failure,
        # and the long budget belongs to the read, where the 54-minute silence happened.
        timeout = httpx.Timeout(total, connect=min(10.0, total))
    except Exception:  # pragma: no cover - httpx is a hard dependency of the stack
        pass
    return {"timeout": timeout}


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


class HostedBudgetExhausted(EmptyCompletionError):
    """A hosted reasoning model spent its whole max_tokens budget before any visible text.

    Distinct from a provider fault: the call worked, the budget was too small for the
    reasoning it triggered. `_call_provider` retries it once at double the budget.
    """

    def __init__(self, budget: int) -> None:
        super().__init__(
            f"hosted model spent its max_tokens budget of {budget} on reasoning and returned "
            "no visible content (finish_reason=length)"
        )
        self.budget = budget


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

#: httpx's timeout exceptions, by NAME rather than by import.
#:
#: `str(httpx.ReadTimeout())` is frequently the EMPTY STRING — httpx re-raises whatever
#: message httpcore gave it, and that is often nothing. Every classifier here works on
#: `str(error).lower()`, so a transport timeout would fall through to "other" and, in
#: `_is_retryable`, to non-retryable. Matching the type name costs no import and cannot be
#: defeated by an empty message (BUG-1191).
_TRANSPORT_TIMEOUT_TYPES = frozenset(
    {
        "TimeoutException",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
    }
)


def classify_llm_error(error: BaseException) -> str:
    """Bucket an LLM failure into a cause a grader can act on."""
    text = str(error).lower()
    if any(m in text for m in RATE_LIMIT_MARKERS) or type(error).__name__ == "RateLimitError":
        return "rate_limit"
    if isinstance(error, EmptyCompletionError):
        return "empty_completion"
    if type(error).__name__ in _TRANSPORT_TIMEOUT_TYPES:
        return "timeout"
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
        elif self.provider == "hosted":
            self._initialize_hosted()
        else:  # ollama (local)
            self._initialize_ollama()

    def _initialize_openai(self):
        """Initialize OpenAI clients — complex model + fast model."""
        try:
            from langchain_openai import ChatOpenAI

            # `timeout` is the transport deadline (BUG-1191). NOTE, and it is a real
            # residual: the OpenAI SDK retries twice on its own, so the worst case on this
            # path is three transport timeouts, not one. `wait_for` still bounds it under a
            # healthy loop. Left alone because this is not the active provider and the
            # change is unmeasurable from here.
            _timeout_s = _transport_timeout_s()
            self.client = ChatOpenAI(
                model=self.config["model"],
                api_key=self.config["api_key"],
                temperature=self.config["temperature"],
                max_tokens=4096,
                timeout=_timeout_s,
            )
            fast_model = self.config.get("model_fast", "gpt-4o-mini")
            self.client_fast = ChatOpenAI(
                model=fast_model,
                api_key=self.config["api_key"],
                temperature=self.config["temperature"],
                max_tokens=2048,
                timeout=_timeout_s,
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
            # A transport-level deadline, because the asyncio one did not bind (BUG-1191).
            # If a future langchain-ollama drops the field, say so rather than losing the
            # protection silently -- an unbounded call is exactly what cost a day.
            _transport: Dict[str, Any] = {}
            if "client_kwargs" in getattr(OllamaLLM, "model_fields", {}):
                _transport = {"client_kwargs": _ollama_client_kwargs()}
            else:
                logger.warning(
                    "langchain-ollama has no `client_kwargs` field — the local LLM client "
                    "is running with NO transport timeout (BUG-1191 protection absent)"
                )
            self.client = OllamaLLM(
                base_url=self.config["base_url"],
                model=self.config["model"],
                temperature=self.config["temperature"],
                keep_alive=_keep_alive,
                num_ctx=_num_ctx,
                **_ollama_generation_cap(),
                **_transport,
            )
            self.client_fast = self.client  # same model
            logger.info(
                f"Ollama options: keep_alive={_keep_alive} num_ctx={_num_ctx} "
                f"num_predict={_ollama_generation_cap().get('num_predict', 'unlimited')} "
                f"transport_timeout={_transport_timeout_s():g}s"
            )
            logger.info(
                f"Initialized Ollama LLM: {self.config['model']} at {self.config['base_url']}"
            )
        except ImportError:
            logger.error("langchain-ollama not installed. Run: pip install langchain-ollama")
            raise

    def _initialize_hosted(self):
        """Initialize the hosted COMAT gateway client (OpenAI-compatible; HOSTED_LLM_BASE_URL)."""
        try:
            import httpx
            from langchain_openai import ChatOpenAI

            # The deadline is HOSTED_LLM_TIMEOUT_S, not `_transport_timeout_s()`: a queued
            # request is silent at the gateway for minutes, and the 1.5x derivation would
            # abandon it while it waits (BUG-1191's layer, sized for generation, not a queue).
            # Connect stays short: an unreachable gateway (VPN down) should fail fast.
            _total = _hosted_timeout_s()
            self.client = ChatOpenAI(
                base_url=self.config["base_url"],
                model=self.config["model"],
                api_key=self.config["api_key"]
                or "not-set",  # validate_config refuses a real deploy without it
                temperature=self.config["temperature"],
                max_tokens=_hosted_budget(),
                timeout=httpx.Timeout(_total, connect=min(10.0, _total)),
                # The OpenAI SDK would otherwise re-send a timed-out request into the same
                # gateway queue. Retries belong to `generate`, which can see them and log them.
                max_retries=0,
            )
            self.client_fast = self.client  # same model for the hosted gateway
            logger.info(
                f"Initialized hosted LLM: {self.config['model']} at {self.config['base_url']}"
            )
        except ImportError:
            logger.error("langchain-openai not installed. Run: pip install langchain-openai")
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
                timeout=_transport_timeout_s(),  # BUG-1191
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
        """Cap a prompt at the local model's window; remote providers manage their own windows."""
        if getattr(self, "provider", "") in ("openai", "hosted"):
            return prompt
        return fit_prompt(prompt, prompt_char_budget())

    def _is_retryable(self, error: Exception) -> bool:
        """Check if an error is transient and should be retried."""
        if isinstance(error, EmptyCompletionError):
            return True
        # A transport timeout is exactly as transient as an asyncio one, and its message
        # is often empty, so it must be matched by type before any text check (BUG-1191).
        if type(error).__name__ in _TRANSPORT_TIMEOUT_TYPES:
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
        errors) with exponential backoff. Each attempt is capped at `_attempt_timeout_s()`:
        LLM_TIMEOUT_S locally, HOSTED_LLM_TIMEOUT_S (+ margin) for the hosted gateway.

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
                if self.provider in ["openai", "ollama_cloud", "hosted"]:
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

                _limit = self._attempt_timeout_s()
                _started = time.monotonic()
                result = await self._call_provider(
                    prompt,
                    system_message,
                    temperature,
                    active_client,
                    provider_kwargs,
                    client_label,
                )
                _elapsed = time.monotonic() - _started
                # BUG-1191: a 3,239 s call was discovered by subtracting two log
                # timestamps by hand. Every call now states its own duration, and one
                # that outlasts the configured bound says so in the same line -- because
                # "elapsed 3239.0s > LLM_TIMEOUT_S 180.0s" is the entire diagnosis.
                if _elapsed >= LLM_SLOW_CALL_WARN_S:
                    _overran = (
                        f" — OVERRAN its {_limit:g}s deadline WITHOUT FIRING"
                        if _elapsed > _limit
                        else ""
                    )
                    logger.warning(
                        f"LLM [{client_label}] slow call: {_elapsed:.1f}s "
                        f"(prompt {len(prompt or '')} chars, "
                        f"completion {len(result or '')} chars){_overran}"
                    )
                else:
                    logger.debug(f"LLM [{client_label}] call took {_elapsed:.1f}s")
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
                _elapsed = time.monotonic() - _started
                last_error = TimeoutError(f"LLM [{client_label}] timed out after {_limit:g}s")
                logger.warning(
                    f"LLM [{client_label}] timeout after {_elapsed:.1f}s "
                    f"(limit {_limit:g}s, attempt {attempt}/{LLM_MAX_RETRIES})"
                )
                self._breaker.record_failure()
            except Exception as e:
                _elapsed = time.monotonic() - _started
                if _elapsed >= LLM_SLOW_CALL_WARN_S:
                    logger.warning(
                        f"LLM [{client_label}] failed after {_elapsed:.1f}s: "
                        f"{type(e).__name__}: {e}"
                    )
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
                if self.provider in ["openai", "ollama_cloud", "hosted"]:
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

    def _is_hosted(self) -> bool:
        """True for the hosted COMAT gateway (the only provider with a queue-aware deadline)."""
        return getattr(self, "provider", "") == "hosted"

    def _attempt_timeout_s(self) -> float:
        """The outer deadline on one provider attempt.

        Hosted: HOSTED_LLM_TIMEOUT_S plus a margin, so the client's own timeout fires first.
        Everything else keeps LLM_TIMEOUT_S, exactly as before.
        """
        if self._is_hosted():
            return _hosted_timeout_s() + _HOSTED_OUTER_MARGIN_S
        return LLM_TIMEOUT_S

    #: One gate per process, created on first hosted use. Created lazily because LLMManager is
    #: built at import time, before any event loop exists.
    _hosted_sem: Optional[asyncio.Semaphore] = None

    def _hosted_semaphore(self) -> asyncio.Semaphore:
        """The hosted request gate, shared by the fast and complex clients (same gateway)."""
        if self._hosted_sem is None:
            self._hosted_sem = asyncio.Semaphore(int(settings.HOSTED_LLM_MAX_CONCURRENCY))
        return self._hosted_sem

    @asynccontextmanager
    async def _hosted_slot(self, label: str) -> AsyncIterator[None]:
        """Hold one of HOSTED_LLM_MAX_CONCURRENCY slots for the length of a hosted call.

        Requests beyond the cap wait HERE, in this process, and the wait is logged. The
        gateway would queue them anyway; holding them locally keeps the queue visible.
        """
        if not self._is_hosted():
            yield
            return
        sem = self._hosted_semaphore()
        cap = int(settings.HOSTED_LLM_MAX_CONCURRENCY)
        if sem.locked():
            logger.info(f"[hosted] all {cap} slots busy — {label} call waiting in this process")
        _waiting_since = time.monotonic()
        async with sem:
            _waited = time.monotonic() - _waiting_since
            if _waited >= 0.5:
                logger.info(f"[hosted] {label} call waited {_waited:.1f}s for one of {cap} slots")
            yield

    async def _call_provider(
        self,
        prompt: str,
        system_message: Optional[str],
        temperature: Optional[float],
        client,
        provider_kwargs: Optional[Dict[str, Any]],
        client_label: str,
    ) -> str:
        """One provider call under the attempt deadline. Hosted calls also hold a slot.

        The slot is taken BEFORE the deadline starts, so time waiting for a free slot in this
        process is not charged to the request. Time in the gateway's own queue IS charged,
        which is why the hosted deadline is measured in minutes.

        A hosted reasoning model can spend its whole max_tokens budget on hidden reasoning and
        return empty content with finish_reason=length. That is a budget shortfall, not a
        provider fault, so it is retried ONCE at double the budget before the failure is
        allowed to count as an empty completion.
        """
        if not self._is_hosted():
            return await asyncio.wait_for(
                self._generate_once(
                    prompt, system_message, temperature, client, provider_kwargs=provider_kwargs
                ),
                timeout=self._attempt_timeout_s(),
            )

        budget = _hosted_budget((provider_kwargs or {}).get("max_tokens"))
        for budget_try in (1, 2):
            kwargs = dict(provider_kwargs or {})
            kwargs["max_tokens"] = budget
            async with self._hosted_slot(client_label):
                try:
                    return await asyncio.wait_for(
                        self._generate_once(
                            prompt, system_message, temperature, client, provider_kwargs=kwargs
                        ),
                        timeout=self._attempt_timeout_s(),
                    )
                except HostedBudgetExhausted as exc:
                    if budget_try == 2:
                        logger.error(
                            f"[hosted] {client_label} call still returned no visible content at "
                            f"max_tokens={exc.budget} (finish_reason=length) — giving up"
                        )
                        raise
                    logger.warning(
                        f"[hosted] {client_label} call returned no visible content: max_tokens="
                        f"{exc.budget} was spent on reasoning (finish_reason=length). Retrying "
                        f"once with max_tokens={exc.budget * 2}"
                    )
                    budget = exc.budget * 2
        raise AssertionError("unreachable: the budget loop returns or raises")  # pragma: no cover

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

        if self.provider in ["openai", "ollama_cloud", "hosted"]:
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
            if not self._is_hosted():
                response = await active.ainvoke(messages, **invoke_kwargs)
                return response.content

            # Hosted: the floor is applied here, the one place a hosted call is sent.
            invoke_kwargs["max_tokens"] = _hosted_budget(invoke_kwargs.get("max_tokens"))
            # agenerate, not ainvoke: in this langchain-openai version `finish_reason` lives on
            # the generation's `generation_info`, and ainvoke returns only the message, so the
            # one signal that separates "budget spent on reasoning" from "model said nothing"
            # would be discarded.
            result = await active.agenerate([messages], **invoke_kwargs)
            generation = result.generations[0][0]
            text = generation.message.content
            blank = not text or (isinstance(text, str) and not text.strip())
            if blank:
                finish = (generation.generation_info or {}).get("finish_reason")
                if finish == "length":
                    raise HostedBudgetExhausted(int(invoke_kwargs["max_tokens"]))
            return text

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
        if self.provider in ("openai", "ollama_cloud", "hosted"):
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

            if self.provider in ["openai", "ollama_cloud", "hosted"]:
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
                if self._is_hosted():
                    stream_kwargs["max_tokens"] = _hosted_budget()  # the same floor as generate
                async with self._hosted_slot("stream"):
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
