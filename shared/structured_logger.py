import logging
import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional

class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        # Add extra fields if available
        if hasattr(record, "extra_fields"):
            log_record.update(record.extra_fields)
            
        return json.dumps(log_record)

class ConsoleFormatter(logging.Formatter):
    """Human readable formatter for console"""
    def format(self, record: logging.LogRecord) -> str:
        # Simple format: [TIME] [LEVEL] [LOGGER] Message
        time_str = datetime.fromtimestamp(record.created).strftime('%H:%M:%S')
        return f"[{time_str}] [{record.levelname}] [{record.name}] {record.getMessage()}"

def setup_structured_logging(log_file: Optional[str] = None):
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    # Console Handler (Human Readable)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ConsoleFormatter())
    root_logger.addHandler(console_handler)
    
    # File Handler (JSON)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(StructuredFormatter())
        root_logger.addHandler(file_handler)

def get_structured_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
