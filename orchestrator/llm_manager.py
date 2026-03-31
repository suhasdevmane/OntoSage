"""
LLM Manager for OntoSage 2.0
Handles LLM interactions with support for Ollama and OpenAI
"""
import sys
sys.path.append('/app')

import asyncio
import os
import time
from typing import List, Dict, Any, Optional
from shared.config import settings, get_llm_config
from shared.utils import get_logger
from orchestrator.services.circuit_breaker import circuit_breaker_for

logger = get_logger(__name__)

# Rate limiting for OpenAI
# gpt-4o-mini Tier-1: 500 RPM, Tier-2+: 5000 RPM
# Set conservatively at 1s; increase only if you hit 429 errors
OPENAI_RATE_LIMIT_DELAY = float(os.environ.get('OPENAI_RATE_LIMIT_DELAY', '1.0'))

# Retry / timeout configuration
LLM_MAX_RETRIES = int(os.environ.get('LLM_MAX_RETRIES', '3'))
LLM_TIMEOUT_S = float(os.environ.get('LLM_TIMEOUT_S', '60'))
LLM_BACKOFF_BASE_S = float(os.environ.get('LLM_BACKOFF_BASE_S', '1.0'))
LLM_BACKOFF_FACTOR = float(os.environ.get('LLM_BACKOFF_FACTOR', '2.0'))

class LLMManager:
    """Manages LLM interactions with multiple providers"""
    
    def __init__(self):
        self.config = get_llm_config()
        self.provider = self.config["provider"]
        self.client = None
        self.last_request_time = 0.0
        self._breaker = circuit_breaker_for("llm", failure_threshold=5, recovery_timeout=30.0)
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize LLM client based on provider"""
        if self.provider == "openai":
            self._initialize_openai()
        elif self.provider == "ollama_cloud":
            self._initialize_ollama_cloud()
        else:  # ollama
            self._initialize_ollama()
    
    def _initialize_openai(self):
        """Initialize OpenAI client"""
        try:
            from langchain_openai import ChatOpenAI
            
            self.client = ChatOpenAI(
                model=self.config["model"],
                api_key=self.config["api_key"],
                temperature=self.config["temperature"],
                max_tokens=4096  # Increased token limit
            )
            logger.info(f"Initialized OpenAI LLM: {self.config['model']}")
        except ImportError:
            logger.error("langchain-openai not installed. Run: pip install langchain-openai")
            raise
    
    def _initialize_ollama(self):
        """Initialize Ollama client"""
        try:
            from langchain_ollama import OllamaLLM
            
            self.client = OllamaLLM(
                base_url=self.config["base_url"],
                model=self.config["model"],
                temperature=self.config["temperature"]
            )
            logger.info(f"Initialized Ollama LLM: {self.config['model']} at {self.config['base_url']}")
        except ImportError:
            logger.error("langchain-ollama not installed. Run: pip install langchain-ollama")
            raise
    
    def _initialize_ollama_cloud(self):
        """Initialize Ollama Cloud client (OpenAI-compatible API)"""
        try:
            from langchain_openai import ChatOpenAI
            
            # Ollama Cloud uses OpenAI-compatible API
            self.client = ChatOpenAI(
                base_url=self.config["base_url"],
                model=self.config["model"],
                api_key=self.config["api_key"],
                temperature=self.config["temperature"],
                max_tokens=4096  # Increased token limit
            )
            logger.info(f"Initialized Ollama Cloud LLM: {self.config['model']} at {self.config['base_url']}")
        except ImportError:
            logger.error("langchain-openai not installed. Run: pip install langchain-openai")
            raise
    
    def _is_retryable(self, error: Exception) -> bool:
        """Check if an error is transient and should be retried."""
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
        if error_type in ("RateLimitError", "APIConnectionError", "InternalServerError", "ServiceUnavailableError"):
            return True
        return False

    async def generate(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> str:
        """
        Generate text from prompt with circuit breaker, retry, and timeout.

        Circuit breaker fast-fails when the LLM provider is unresponsive.
        Retries up to LLM_MAX_RETRIES times on transient errors (429, 5xx, connection errors)
        with exponential backoff. Each attempt is capped at LLM_TIMEOUT_S seconds.
        """
        # Circuit breaker: fast-fail if LLM is known to be down
        if not self._breaker.allow_request():
            raise RuntimeError(
                f"LLM circuit breaker is OPEN — the {self.provider} provider "
                f"has been unresponsive. Requests will resume automatically in "
                f"~{self._breaker.recovery_timeout:.0f}s."
            )

        last_error = None

        for attempt in range(1, LLM_MAX_RETRIES + 1):
            try:
                # Rate limiting for OpenAI
                if self.provider in ["openai", "ollama_cloud"]:
                    current_time = time.time()
                    elapsed = current_time - self.last_request_time
                    if elapsed < OPENAI_RATE_LIMIT_DELAY:
                        wait_time = OPENAI_RATE_LIMIT_DELAY - elapsed
                        await asyncio.sleep(wait_time)
                    self.last_request_time = time.time()

                result = await asyncio.wait_for(
                    self._generate_once(prompt, system_message, temperature),
                    timeout=LLM_TIMEOUT_S,
                )
                self._breaker.record_success()
                return result

            except asyncio.TimeoutError:
                last_error = TimeoutError(f"LLM call timed out after {LLM_TIMEOUT_S}s")
                logger.warning(f"LLM timeout (attempt {attempt}/{LLM_MAX_RETRIES})")
                self._breaker.record_failure()
            except Exception as e:
                last_error = e
                self._breaker.record_failure()
                if not self._is_retryable(e) or attempt == LLM_MAX_RETRIES:
                    logger.error(f"LLM generation error (attempt {attempt}, non-retryable): {e}", exc_info=True)
                    raise
                logger.warning(f"LLM retryable error (attempt {attempt}/{LLM_MAX_RETRIES}): {e}")

            # Exponential backoff before retry
            if attempt < LLM_MAX_RETRIES:
                backoff = LLM_BACKOFF_BASE_S * (LLM_BACKOFF_FACTOR ** (attempt - 1))
                logger.info(f"LLM retry backoff: {backoff:.1f}s")
                await asyncio.sleep(backoff)

        raise last_error or RuntimeError("LLM generation failed after all retries")

    async def _generate_once(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Single LLM call without retry logic."""
        if self.provider in ["openai", "ollama_cloud"]:
            try:
                from langchain.schema import SystemMessage as SysMsg, HumanMessage as HumMsg
            except ImportError:
                from langchain_core.messages import SystemMessage as SysMsg, HumanMessage as HumMsg

            messages = []
            if system_message:
                messages.append(SysMsg(content=system_message))
            messages.append(HumMsg(content=prompt))

            invoke_kwargs = {}
            if temperature is not None:
                invoke_kwargs["temperature"] = temperature

            response = await self.client.ainvoke(messages, **invoke_kwargs)
            return response.content

        else:  # ollama (local)
            full_prompt = prompt
            if system_message:
                full_prompt = f"System: {system_message}\n\nUser: {prompt}"
            response = await self.client.ainvoke(full_prompt)
            return response
    
    async def astream_generate(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: Optional[float] = None
    ):
        """
        Stream generated text from prompt.

        Note: temperature is passed via invoke kwargs to avoid mutating shared client state.
        """
        try:
            if self.provider in ["openai", "ollama_cloud"]:
                try:
                    from langchain.schema import SystemMessage as SysMsg, HumanMessage as HumMsg
                except ImportError:
                    from langchain_core.messages import SystemMessage as SysMsg, HumanMessage as HumMsg

                messages = []
                if system_message:
                    messages.append(SysMsg(content=system_message))
                messages.append(HumMsg(content=prompt))

                stream_kwargs = {}
                if temperature is not None:
                    stream_kwargs["temperature"] = temperature

                async for chunk in self.client.astream(messages, **stream_kwargs):
                    yield chunk.content

            else:  # ollama (local)
                full_prompt = prompt
                if system_message:
                    full_prompt = f"System: {system_message}\n\nUser: {prompt}"

                async for chunk in self.client.astream(full_prompt):
                    yield chunk

        except Exception as e:
            logger.error(f"LLM streaming generation failed: {e}")
            yield f"Error: {str(e)}"

    async def generate_with_examples(
        self,
        prompt: str,
        examples: List[Dict[str, str]],
        system_message: Optional[str] = None
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
            "base_url": self.config.get("base_url"),
            "temperature": self.config.get("temperature")
        }

# Global instance
llm_manager = LLMManager()
