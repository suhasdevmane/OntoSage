"""
Whisper STT Service - Main FastAPI Application
Handles speech-to-text transcription
Supports both local (faster-whisper) and cloud (OpenAI Whisper API)
"""
import sys
sys.path.append('/app')

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import tempfile
import os

from shared.config import settings, validate_config
from shared.models import HealthResponse, TranscriptionResponse
from shared.utils import get_logger

logger = get_logger(__name__)

# Validate configuration
try:
    validate_config()
except ValueError as e:
    logger.warning(f"Configuration warning: {e}")

# Create FastAPI app
app = FastAPI(
    title="OntoSage Whisper STT",
    description="Speech-to-Text transcription service",
    version="2.0.0"
)

# Add CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize transcriber
transcriber = None

@app.on_event("startup")
async def startup_event():
    """Initialize transcription service with graceful fallback"""
    global transcriber
    logger.info("🚀 Starting Whisper STT Service")
    provider = settings.STT_PROVIDER
    logger.info(f"STT Provider (requested): {provider}")

    try:
        if provider == "openai":
            from transcribe import OpenAITranscriber
            transcriber = OpenAITranscriber()
            logger.info("✅ Initialized OpenAI transcriber")
        else:  # local requested
            try:
                from transcribe import LocalWhisperTranscriber
                transcriber = LocalWhisperTranscriber()
                logger.info("✅ Initialized local faster-whisper transcriber")
            except ModuleNotFoundError:
                logger.warning("faster-whisper not installed; falling back to OpenAI if available")
                if settings.OPENAI_API_KEY:
                    from transcribe import OpenAITranscriber
                    transcriber = OpenAITranscriber()
                    provider = "openai"
                    logger.info("✅ Fallback to OpenAI transcriber")
                else:
                    transcriber = None
                    provider = "none"
                    logger.warning("No STT provider available (missing faster-whisper and OPENAI_API_KEY)")
    except Exception as e:
        logger.error(f"Failed initializing STT provider: {e}")
        transcriber = None
        provider = "error"
    logger.info(f"Active STT provider: {provider}")

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    status = "healthy" if transcriber else "unhealthy"
    current = settings.STT_PROVIDER if transcriber else "none"
    model = (
        settings.WHISPER_MODEL_LOCAL if current == "local" else ("whisper-1" if current == "openai" else "unavailable")
    )
    return HealthResponse(
        status=status,
        service="whisper-stt",
        version="2.0.0",
        model_provider=current,
        details={"model": model}
    )

@app.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str = "en"
):
    """
    Transcribe audio file to text
    
    Args:
        file: Audio file (WAV, MP3, M4A, etc.)
        language: Language code (default: en)
        
    Returns:
        TranscriptionResponse with text
    """
    try:
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        logger.info(f"Transcribing file: {file.filename} ({len(content)} bytes)")
        
        # Transcribe
        result = await transcriber.transcribe(tmp_path, language)
        
        # Clean up
        os.unlink(tmp_path)
        
        logger.info(f"Transcription complete: {result.text[:100]}")
        
        return result
        
    except Exception as e:
        logger.error(f"Transcription error: {e}", exc_info=True)
        
        # Clean up on error
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8003,
        reload=True,
        log_level="info"
    )
