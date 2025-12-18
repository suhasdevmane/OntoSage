"""
Context Manager Service
Handles conversation summarization, pruning, and title generation.
"""
import sys
sys.path.append('/app')

from typing import List, Optional
from shared.models import Message
from shared.utils import get_logger
from orchestrator.llm_manager import LLMManager

logger = get_logger(__name__)

class ContextManager:
    def __init__(self, llm_manager: LLMManager):
        self.llm = llm_manager
        
    async def summarize_history(self, messages: List[Message], existing_summary: Optional[str] = None) -> str:
        """
        Summarize conversation history into a concise paragraph.
        """
        if not messages:
            return existing_summary or ""
            
        # Convert messages to text format
        conversation_text = ""
        for msg in messages:
            role = "User" if msg.role == "user" else "Assistant"
            conversation_text += f"{role}: {msg.content}\n"
            
        prompt = f"""
        Summarize the following conversation into a concise paragraph that captures the key context, user intent, and important details.
        If an existing summary is provided, update it with the new information.
        
        Existing Summary: {existing_summary or "None"}
        
        New Conversation:
        {conversation_text}
        
        Updated Summary:
        """
        
        try:
            summary = await self.llm.generate(prompt, temperature=0.3)
            return summary.strip()
        except Exception as e:
            logger.error(f"Failed to summarize history: {e}")
            return existing_summary or ""

    async def generate_title(self, first_message: str) -> str:
        """
        Generate a short 3-5 word title for the conversation based on the first message.
        """
        prompt = f"""
        Generate a short, concise title (3-5 words) for a conversation that starts with this message:
        "{first_message}"
        
        Do not use quotes. Just the title.
        """
        
        try:
            title = await self.llm.generate(prompt, temperature=0.7)
            return title.strip().strip('"')
        except Exception as e:
            logger.error(f"Failed to generate title: {e}")
            return "New Conversation"

    def prune_messages(self, messages: List[Message], max_messages: int = 10) -> List[Message]:
        """
        Keep only the last N messages.
        """
        if len(messages) <= max_messages:
            return messages
        return messages[-max_messages:]
