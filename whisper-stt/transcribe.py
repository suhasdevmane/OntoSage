"""
Transcription implementations for Whisper STT
Supports both local (faster-whisper) and cloud (OpenAI)
"""
import sys
sys.path.append('/app')

from abc import ABC, abstractmethod
from typing import Optional

from shared.config import settings
from shared.models import TranscriptionResponse
from shared.utils import get_logger

logger = get_logger(__name__)

class BaseTranscriber(ABC):
    """Base transcriber interface"""
    
    @abstractmethod
    async def transcribe(self, audio_path: str, language: str = "en") -> TranscriptionResponse:
        """Transcribe audio file"""
        pass

class OpenAITranscriber(BaseTranscriber):
    """OpenAI Whisper API transcriber"""
    
    def __init__(self):
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
            logger.info("Initialized OpenAI Whisper transcriber")
        except ImportError:
            logger.error("openai package not installed")
            raise
    
    async def transcribe(self, audio_path: str, language: str = "en") -> TranscriptionResponse:
        """
        Transcribe using OpenAI Whisper API
        
        Args:
            audio_path: Path to audio file
            language: Language code
            
        Returns:
            TranscriptionResponse
        """
        try:
            with open(audio_path, "rb") as audio_file:
                transcript = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language=language
                )
            
            return TranscriptionResponse(
                text=transcript.text,
                language=language,
                confidence=None  # OpenAI doesn't provide confidence
            )
            
        except Exception as e:
            logger.error(f"OpenAI transcription error: {e}")
            raise

class LocalWhisperTranscriber(BaseTranscriber):
    """Local faster-whisper transcriber"""
    
    def __init__(self):
        try:
            from faster_whisper import WhisperModel
            
            model_size = settings.WHISPER_MODEL_LOCAL
            logger.info(f"Loading faster-whisper model: {model_size}")
            
            # Use CPU by default (can be changed to "cuda" if GPU available)
            self.model = WhisperModel(
                model_size,
                device="cpu",
                compute_type="int8"  # Quantization for faster CPU inference
            )
            
            logger.info("Initialized local Whisper transcriber")
            
        except ImportError:
            logger.error("faster-whisper not installed. Run: pip install faster-whisper")
            raise
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            raise
    
    async def transcribe(self, audio_path: str, language: str = "en") -> TranscriptionResponse:
        """
        Transcribe using local faster-whisper
        
        Args:
            audio_path: Path to audio file
            language: Language code
            
        Returns:
            TranscriptionResponse
        """
        try:
            # Transcribe
            segments, info = self.model.transcribe(
                audio_path,
                language=language,
                beam_size=5
            )
            
            # Combine all segments
            text = " ".join([segment.text for segment in segments])
            
            return TranscriptionResponse(
                text=text.strip(),
                language=info.language,
                confidence=info.language_probability
            )
            
        except Exception as e:
            logger.error(f"Local transcription error: {e}")
            raise
