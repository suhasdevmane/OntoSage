"""
Code Executor Service - Main FastAPI Application
Safely executes Python code in a sandboxed environment
"""
import sys
sys.path.append('/app')

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from shared.config import settings
from shared.models import (
    HealthResponse,
    CodeExecutionRequest,
    CodeExecutionResult
)
from shared.utils import get_logger

from sandbox import CodeSandbox

logger = get_logger(__name__)

# Create FastAPI app
app = FastAPI(
    title="OntoSage Code Executor",
    description="Sandboxed Python code execution service",
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

# Initialize sandbox
sandbox = CodeSandbox()

@app.on_event("startup")
async def startup_event():
    """Initialize service"""
    logger.info("🚀 Starting Code Executor Service")
    logger.info(f"Timeout: {settings.CODE_EXECUTOR_TIMEOUT}s")
    logger.info(f"Memory Limit: {settings.CODE_EXECUTOR_MEMORY_LIMIT}")
    logger.info(f"CPU Limit: {settings.CODE_EXECUTOR_CPU_LIMIT}")

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        service="code-executor",
        version="2.0.0",
        details={
            "timeout": settings.CODE_EXECUTOR_TIMEOUT,
            "memory_limit": settings.CODE_EXECUTOR_MEMORY_LIMIT,
            "cpu_limit": settings.CODE_EXECUTOR_CPU_LIMIT
        }
    )

@app.post("/execute", response_model=CodeExecutionResult)
async def execute_code(request: CodeExecutionRequest):
    """
    Execute Python code in sandbox
    
    Args:
        request: CodeExecutionRequest with code, timeout, context
        
    Returns:
        CodeExecutionResult with success, stdout, stderr, result, error
    """
    try:
        logger.info(f"Executing code ({len(request.code)} chars)")
        logger.debug(f"Code:\n{request.code}")
        
        result = await sandbox.execute(
            code=request.code,
            timeout=request.timeout,
            context=request.context or {}
        )
        
        if result.success:
            logger.info(f"Execution succeeded in {result.execution_time:.2f}s")
        else:
            logger.warning(f"Execution failed: {result.error}")
        
        return result
        
    except Exception as e:
        logger.error(f"Execution error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/validate")
async def validate_code(code: str):
    """
    Validate Python code syntax without executing
    
    Args:
        code: Python code to validate
        
    Returns:
        Validation result
    """
    try:
        import ast
        ast.parse(code)
        return {
            "valid": True,
            "message": "Code syntax is valid"
        }
    except SyntaxError as e:
        return {
            "valid": False,
            "message": f"Syntax error: {e.msg}",
            "line": e.lineno,
            "offset": e.offset
        }
    except Exception as e:
        return {
            "valid": False,
            "message": str(e)
        }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8002,
        reload=True,
        log_level="info"
    )
