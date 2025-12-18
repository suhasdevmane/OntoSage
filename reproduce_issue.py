import re

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

def _validate_code(code: str) -> bool:
    """
    Validate code for forbidden operations
    """
    
    # Check for forbidden imports
    for forbidden in FORBIDDEN_IMPORTS:
        # Check for "import forbidden" or "from forbidden"
        # Use regex to match whole words only
        if re.search(rf'^\s*import\s+{re.escape(forbidden)}\b', code, re.MULTILINE) or \
           re.search(rf'^\s*from\s+{re.escape(forbidden)}\b', code, re.MULTILINE):
            print(f"Forbidden import detected: {forbidden}")
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
        if re.search(pattern, code):
            print(f"Forbidden operation detected: {pattern}")
            return False
    
    return True

code_with_time = """
import pandas as pd
import time
import json

print("Hello")
"""

print(f"Validating code with time: {_validate_code(code_with_time)}")
