"""
Code Sandbox - Safe Python Execution
Implements security restrictions and resource limits
"""
import sys
sys.path.append('/app')

import io
import time
import signal
import traceback
from types import ModuleType
from contextlib import redirect_stdout, redirect_stderr
from typing import Dict, Any, Optional
import asyncio

from shared.config import settings
from shared.models import CodeExecutionResult
from shared.utils import get_logger

logger = get_logger(__name__)

class TimeoutError(Exception):
    """Raised when code execution times out"""
    pass

def timeout_handler(signum, frame):
    """Signal handler for timeout"""
    raise TimeoutError("Code execution timed out")

class CodeSandbox:
    """
    Sandboxed Python code executor
    Implements multiple security layers
    """
    
    # Restricted builtins - only safe functions allowed
    # Original import preserved for wrapping
    _ORIGINAL_IMPORT = __import__

    def _limited_import(name, globals=None, locals=None, fromlist=(), level=0):
        """Controlled import: only allow whitelisted modules (including submodules)."""
        root_name = name.split('.')[0]
        allowed = CodeSandbox.ALLOWED_IMPORTS
        if name in allowed or root_name in {m.split('.')[0] for m in allowed}:
            return CodeSandbox._ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
        raise ImportError(f"Module '{name}' is not permitted in sandbox")

    SAFE_BUILTINS = {
        'abs': abs,
        'all': all,
        'any': any,
        'bool': bool,
        'dict': dict,
        'enumerate': enumerate,
        'filter': filter,
        'float': float,
        'int': int,
        'len': len,
        'list': list,
        'map': map,
        'max': max,
        'min': min,
        'print': print,
        'range': range,
        'round': round,
        'set': set,
        'sorted': sorted,
        'str': str,
        'sum': sum,
        'tuple': tuple,
        'type': type,
        'zip': zip,
        'isinstance': isinstance,
        'getattr': getattr,
        'hasattr': hasattr,
        'setattr': setattr,
        '__import__': _limited_import,
        # Exception classes needed for error handling
        'Exception': Exception,
        'KeyError': KeyError,
        'ValueError': ValueError,
        'TypeError': TypeError,
        'IndexError': IndexError,
        'AttributeError': AttributeError,
    }
    
    # Allowed imports - whitelist approach
    ALLOWED_IMPORTS = {
        'pandas',
        'numpy',
        'matplotlib',
        'matplotlib.pyplot',
        'seaborn',
        'plotly',
        'plotly.graph_objects',
        'plotly.express',
        'datetime',
        'json',
        'math',
        'time',
        'statistics',
        'collections',
        'itertools',
    }
    
    # Forbidden imports - blacklist (extra safety)
    FORBIDDEN_IMPORTS = {
        'os',
        'sys',
        'subprocess',
        'socket',
        'requests',
        'urllib',
        'pickle',
        'shelve',
        '__import__',
        'eval',
        'exec',
        'compile',
        'open',  # File I/O
        'file',
    }
    
    def __init__(self):
        """Initialize sandbox"""
        self.default_timeout = settings.CODE_EXECUTOR_TIMEOUT
    
    async def execute(
        self,
        code: str,
        timeout: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> CodeExecutionResult:
        """
        Execute Python code safely
        
        Args:
            code: Python code to execute
            timeout: Execution timeout in seconds
            context: Variables to inject into execution context
            
        Returns:
            CodeExecutionResult
        """
        if timeout is None:
            timeout = self.default_timeout
        
        # Validate code first
        if not self._validate_code(code):
            return CodeExecutionResult(
                success=False,
                stdout="",
                stderr="",
                error="Code contains forbidden operations",
                execution_time=0.0
            )
        
        # Run in subprocess with timeout
        try:
            # Use asyncio to run with timeout
            result = await asyncio.wait_for(
                self._execute_in_sandbox(code, context or {}),
                timeout=timeout
            )
            return result
            
        except asyncio.TimeoutError:
            logger.warning(f"Code execution timed out after {timeout}s")
            return CodeExecutionResult(
                success=False,
                stdout="",
                stderr="",
                error=f"Execution timed out after {timeout} seconds",
                execution_time=timeout
            )
        except Exception as e:
            logger.error(f"Sandbox execution error: {e}", exc_info=True)
            return CodeExecutionResult(
                success=False,
                stdout="",
                stderr="",
                error=str(e),
                execution_time=0.0
            )
    
    async def _execute_in_sandbox(
        self,
        code: str,
        context: Dict[str, Any]
    ) -> CodeExecutionResult:
        """
        Execute code in sandboxed environment
        This runs in a separate thread to allow timeout
        """
        import concurrent.futures
        
        # Run in thread pool executor
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            result = await loop.run_in_executor(
                executor,
                self._run_code,
                code,
                context
            )
        
        return result
    
    def _run_code(self, code: str, context: Dict[str, Any]) -> CodeExecutionResult:
        """
        Actually run the code (called in thread)
        """
        start_time = time.time()
        
        # Prepare execution environment
        # Restricted builtins
        safe_globals = {
            '__builtins__': self.SAFE_BUILTINS,
        }
        
        # Add allowed imports
        # Pre-import common libs (optional; failures are non-fatal)
        preimport_map = {
            'pandas': 'pd',
            'numpy': 'np',
            'matplotlib.pyplot': 'plt',
            'plotly.graph_objects': 'go',
            'plotly.express': 'px',
            'math': 'math',
            'statistics': 'stats'
        }
        for mod_name, alias in preimport_map.items():
            try:
                module = CodeSandbox._ORIGINAL_IMPORT(mod_name)
                safe_globals[alias] = module
            except Exception:
                continue
        
        # Inject context variables
        safe_globals.update(context)
        
        # Capture stdout and stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        
        result_value = None
        error_msg = None
        success = False
        
        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                # Compile code
                compiled_code = compile(code, '<sandbox>', 'exec')
                
                # Execute
                exec(compiled_code, safe_globals)
                
                # Try to get result from last expression or 'result' variable
                if 'result' in safe_globals:
                    result_value = safe_globals['result']
                
                success = True
                
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            logger.debug(f"Execution error: {error_msg}")
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        return CodeExecutionResult(
            success=success,
            stdout=stdout_capture.getvalue(),
            stderr=stderr_capture.getvalue(),
            result=result_value,
            error=error_msg,
            execution_time=execution_time
        )
    
    def _validate_code(self, code: str) -> bool:
        """
        Validate code for forbidden operations
        
        Args:
            code: Python code to validate
            
        Returns:
            True if code is safe, False otherwise
        """
        import re
        
        # Check for forbidden imports
        for forbidden in self.FORBIDDEN_IMPORTS:
            # Check for "import forbidden" or "from forbidden"
            # Use regex to match whole words only
            if re.search(rf'^\s*import\s+{re.escape(forbidden)}\b', code, re.MULTILINE) or \
               re.search(rf'^\s*from\s+{re.escape(forbidden)}\b', code, re.MULTILINE):
                logger.warning(f"Forbidden import detected: {forbidden}")
                return False
        
        # Check for forbidden builtins usage
        forbidden_patterns = [
            r'\b__import__\b',
            r'\beval\s*\(',
            r'\bexec\s*\(',
            r'\bcompile\s*\(',
            r'\bopen\s*\(',
            r'\bfile\s*\(',
        ]
        
        for pattern in forbidden_patterns:
            match = re.search(pattern, code)
            if match:
                logger.warning(f"Forbidden operation detected: {pattern} (Match: {match.group(0)})")
                return False
        
        return True
