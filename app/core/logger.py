import logging
import json
from datetime import datetime, timezone
from contextvars import ContextVar

# A global context variable to store the request_id for the current async context
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        
        # Include stack trace if exception info is present
        if record.exc_info:
            log_record["stack_trace"] = self.formatException(record.exc_info)
            
        # Add any extra attributes added via `logger.info("msg", extra={"extra_data": {...}})`
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            for key, value in record.extra_data.items():
                log_record[key] = value

        return json.dumps(log_record)

def setup_logging():
    """Initialize logging to use the JSON formatter globally."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Remove any existing handlers to prevent duplicate logs
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    formatter = JSONFormatter()
    
    # File handler for app.log
    file_handler = logging.FileHandler("app.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    
    # Stream handler for console
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)
    
    # Ensure uvicorn and fastapi loggers also use our formatter
    for logger_name in ("uvicorn", "uvicorn.access", "fastapi"):
        l = logging.getLogger(logger_name)
        l.handlers = [] # clear their default handlers
        l.propagate = True # let the root logger handle it
