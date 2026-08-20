"""
LLM Manager for OntoSage 2.0
Handles LLM interactions with support for Ollama and OpenAI
"""

import sys

sys.path.append("/app")

import asyncio
import contextvars
import os
import time
from enum import Enum
from typing import Any, Dict, List, Optional


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


class EmptyCompletionError(RuntimeError):
    """The provider answered successfully but produced no text."""


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
            )
            self.client_fast = self.client  # same model
            logger.info(f"Ollama options: keep_alive={_keep_alive} num_ctx={_num_ctx}")
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
    ) -> str:
        """
        Generate text from prompt with circuit breaker, retry, and timeout.

        Routes to the fast model (gpt-4o-mini) for intent/SPARQL/general tasks and
        to the complex model for analytics/reports.  Each client has its own
        rate-limit tracker so they don't block each other.

        Circuit breaker fast-fails when the LLM provider is unresponsive.
        Retries up to LLM_MAX_RETRIES times on transient errors (429, 5xx, connection
        errors) with exponential backoff. Each attempt is capped at LLM_TIMEOUT_S.
        """
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
                    self._generate_once(prompt, system_message, temperature, active_client),
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
    ) -> str:
        """Single LLM call without retry logic. Uses provided client or falls back to self.client."""
        active = client if client is not None else self.client

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
            response = await active.ainvoke(messages, **invoke_kwargs)
            return response.content

        else:  # ollama (local)
            full_prompt = f"System: {effective_system}\n\nUser: {prompt}"
            response = await active.ainvoke(full_prompt)
            return response

    async def astream_generate(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: Optional[float] = None,
        task_type: Optional[TaskType] = None,
    ):
        """Stream generated text. Routes to fast or complex client based on task_type."""
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
