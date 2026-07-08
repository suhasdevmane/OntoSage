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
import multiprocessing as mp
import pickle
import queue as _queue

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
        # Core types
        'abs': abs,
        'all': all,
        'any': any,
        'bool': bool,
        'bytes': bytes,
        'chr': chr,
        'dict': dict,
        'enumerate': enumerate,
        'filter': filter,
        'float': float,
        'format': format,
        'frozenset': frozenset,
        'hash': hash,
        'hex': hex,
        'int': int,
        'iter': iter,
        'len': len,
        'list': list,
        'map': map,
        'max': max,
        'min': min,
        'next': next,
        'oct': oct,
        'ord': ord,
        'print': print,
        'range': range,
        'repr': repr,
        'reversed': reversed,
        'round': round,
        'set': set,
        'slice': slice,
        'sorted': sorted,
        'str': str,
        'sum': sum,
        'tuple': tuple,
        'type': type,
        'zip': zip,
        'isinstance': isinstance,
        'issubclass': issubclass,
        'hasattr': hasattr,
        # SECURITY: getattr / setattr / vars are intentionally NOT exposed.
        # Dynamic, string-built attribute access (getattr(x, '__glo'+'bals__'))
        # is a primary sandbox-escape primitive and would defeat the source-level
        # dunder guard in _validate_code(). hasattr is a safe read-only check.
        '__import__': _limited_import,
        # Exception classes needed for analytics error handling
        'Exception': Exception,
        'KeyError': KeyError,
        'ValueError': ValueError,
        'TypeError': TypeError,
        'IndexError': IndexError,
        'AttributeError': AttributeError,
        'RuntimeError': RuntimeError,
        'StopIteration': StopIteration,
        'ZeroDivisionError': ZeroDivisionError,
        'OverflowError': OverflowError,
        'NameError': NameError,
        'ImportError': ImportError,
        'FileNotFoundError': FileNotFoundError,
        'IOError': IOError,
        'AssertionError': AssertionError,
        'NotImplementedError': NotImplementedError,
        'Warning': Warning,
        'UserWarning': UserWarning,
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
        'base64',  # needed for chart image encoding
        'io',
        'BytesIO',
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
        
        # Run in a separate PROCESS so a runaway can be forcibly KILLED on timeout.
        try:
            return await self._execute_in_sandbox(code, context or {}, timeout)
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
        context: Dict[str, Any],
        timeout: int,
    ) -> CodeExecutionResult:
        """
        Execute code in a separate PROCESS (not a thread).

        A thread cannot be forcibly stopped, so the previous thread-based timeout
        merely abandoned the await while the runaway thread kept consuming a worker
        forever. A child process CAN be killed, giving a real, enforceable timeout.
        The blocking process management runs in the default executor so the event
        loop is never blocked.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._run_in_process, code, context, timeout
        )

    def _run_in_process(
        self, code: str, context: Dict[str, Any], timeout: int
    ) -> CodeExecutionResult:
        """Spawn a child process for the exec, killing it if it overruns `timeout`."""
        ctx = mp.get_context("spawn")  # portable; avoids fork-after-threads hazards
        result_q: Any = ctx.Queue()
        proc = ctx.Process(
            target=_sandbox_process_worker,
            args=(result_q, code, context),
            daemon=True,
        )
        start = time.time()
        proc.start()
        try:
            # get() with a deadline avoids the classic join()-before-get() deadlock
            # on large results, and doubles as the timeout wait.
            payload = result_q.get(timeout=timeout)
        except _queue.Empty:
            # Child overran the deadline — terminate, then hard-kill if it ignores it.
            proc.terminate()
            proc.join(2)
            if proc.is_alive():
                proc.kill()
                proc.join()
            logger.warning(f"Code execution timed out after {timeout}s — process killed")
            return CodeExecutionResult(
                success=False,
                stdout="",
                stderr="",
                error=f"Execution timed out after {timeout} seconds",
                execution_time=time.time() - start,
            )
        proc.join(2)
        if proc.is_alive():
            proc.terminate()
        payload.setdefault("execution_time", time.time() - start)
        return CodeExecutionResult(**payload)
    
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
        
        # Check for forbidden builtins usage.
        # NOTE: this blacklist is DEFENCE-IN-DEPTH, not the security boundary — an
        # in-process restricted-builtins sandbox is not a hard boundary. The real
        # isolation is container-level (no secrets in env, dropped caps, no network).
        forbidden_patterns = [
            r'\b__import__\b',
            r'\beval\s*\(',
            r'\bexec\s*\(',
            r'\bcompile\s*\(',
            r'\bopen\s*\(',
            r'\bfile\s*\(',
            # Escape primitives: dunder attribute access (x.__class__ / __globals__
            # / __subclasses__ / __mro__ …) and dunder item access (x['__builtins__'])
            # are how restricted-builtins sandboxes get broken out of.
            r'\.\s*__\w+__',  # .__globals__, .__class__, .__bases__, …
            r'\[\s*[\'"]__\w+__',  # ['__builtins__'], ["__globals__"], …
            r'\bgetattr\s*\(',  # dynamic attribute access (also removed from builtins)
            r'\bsetattr\s*\(',
            r'\bvars\s*\(',
        ]
        
        for pattern in forbidden_patterns:
            match = re.search(pattern, code)
            if match:
                logger.warning(f"Forbidden operation detected: {pattern} (Match: {match.group(0)})")
                return False

        return True


def _sandbox_process_worker(result_q: Any, code: str, context: Dict[str, Any]) -> None:
    """Child-process entrypoint: run the code and put a result dict on result_q.

    Module-level (not a bound method) so it is importable under the 'spawn' start
    method used on Windows/macOS. Result serialization is guarded — a user 'result'
    value that can't be pickled (e.g. a Figure) is coerced to its repr so the queue
    put can never hang or silently drop the message.
    """
    try:
        res = CodeSandbox()._run_code(code, context)
        payload = {
            "success": res.success,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "result": res.result,
            "error": res.error,
            "execution_time": res.execution_time,
        }
        try:
            pickle.dumps(payload["result"])
        except Exception:
            payload["result"] = repr(payload["result"])
        result_q.put(payload)
    except Exception as e:
        result_q.put(
            {
                "success": False,
                "stdout": "",
                "stderr": "",
                "result": None,
                "error": f"sandbox worker error: {e}",
                "execution_time": 0.0,
            }
        )
