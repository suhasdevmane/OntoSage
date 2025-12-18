"""
LLM Manager for OntoSage 2.0
Handles LLM interactions with support for Ollama and OpenAI
"""
import sys
sys.path.append('/app')

import asyncio
import time
from typing import List, Dict, Any, Optional
from shared.config import settings, get_llm_config
from shared.utils import get_logger

logger = get_logger(__name__)

# Rate limiting for OpenAI (3 RPM = 1 request every 20s)
OPENAI_RATE_LIMIT_DELAY = 21.0

class LLMManager:
    """Manages LLM interactions with multiple providers"""
    
    def __init__(self):
        self.config = get_llm_config()
        self.provider = self.config["provider"]
        self.client = None
        self.last_request_time = 0.0
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
    
    async def generate(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> str:
        """
        Generate text from prompt
        
        Args:
            prompt: User prompt
            system_message: Optional system message
            temperature: Override default temperature
            
        Returns:
            Generated text
        """
        try:
            # Rate limiting for OpenAI
            if self.provider in ["openai", "ollama_cloud"]:
                current_time = time.time()
                elapsed = current_time - self.last_request_time
                if elapsed < OPENAI_RATE_LIMIT_DELAY:
                    wait_time = OPENAI_RATE_LIMIT_DELAY - elapsed
                    logger.warning(f"Rate limiting: Waiting {wait_time:.2f}s before next OpenAI request...")
                    await asyncio.sleep(wait_time)
                
                self.last_request_time = time.time()

            if self.provider in ["openai", "ollama_cloud"]:
                try:
                    from langchain.schema import SystemMessage, HumanMessage
                except ImportError:
                    from langchain_core.messages import SystemMessage, HumanMessage
                
                messages = []
                if system_message:
                    messages.append(SystemMessage(content=system_message))
                messages.append(HumanMessage(content=prompt))
                
                if temperature is not None:
                    self.client.temperature = temperature
                
                response = await self.client.ainvoke(messages)
                return response.content
                
            else:  # ollama (local)
                full_prompt = prompt
                if system_message:
                    full_prompt = f"System: {system_message}\n\nUser: {prompt}"
                
                if temperature is not None:
                    self.client.temperature = temperature
                
                response = await self.client.ainvoke(full_prompt)
                return response
                
        except Exception as e:
            logger.error(f"LLM generation error: {e}", exc_info=True)
            raise
    
    async def astream_generate(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: Optional[float] = None
    ):
        """
        Stream generated text from prompt
        
        Args:
            prompt: User prompt
            system_message: Optional system message
            temperature: Override default temperature
            
        Yields:
            Chunks of generated text
        """
        try:
            if self.provider in ["openai", "ollama_cloud"]:
                try:
                    from langchain.schema import SystemMessage, HumanMessage
                except ImportError:
                    from langchain_core.messages import SystemMessage, HumanMessage
                
                messages = []
                if system_message:
                    messages.append(SystemMessage(content=system_message))
                messages.append(HumanMessage(content=prompt))
                
                if temperature is not None:
                    self.client.temperature = temperature
                
                async for chunk in self.client.astream(messages):
                    yield chunk.content
                    
            else:  # ollama (local)
                full_prompt = prompt
                if system_message:
                    full_prompt = f"System: {system_message}\n\nUser: {prompt}"
                
                if temperature is not None:
                    self.client.temperature = temperature
                
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
