import os
import logging
import asyncio
import contextvars
from contextlib import asynccontextmanager
from typing import List, Dict, Optional
from logging import StreamHandler

# Configure default logging level from environment
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
# Include request_id in the log format; filled by RequestContextFilter
default_format = "%(asctime)s - %(levelname)s - [%(request_id)s] - %(message)s"

# Context variable carrying the current request id (per task)
current_request_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)


class RequestContextFilter(logging.Filter):
    """Injects request_id from contextvar into every record."""

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        req_id = current_request_id.get()
        # Always set attribute to avoid KeyError in formatters
        record.request_id = req_id or "-"  # type: ignore[attr-defined]
        return True


class RequestIDFilter(logging.Filter):
    """Allows only records matching a specific request_id."""

    def __init__(self, request_id: Optional[str]):
        super().__init__()
        self.request_id = request_id

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        # record.request_id is injected by RequestContextFilter
        record_req = getattr(record, "request_id", None)
        if self.request_id is None:
            return False
        return record_req == self.request_id


def setup_logger(name=None, level=None, format_str=None):
    logger = logging.getLogger(name)
    logger.setLevel(level or log_level)

    # Clear existing handlers to avoid duplicates
    if logger.hasHandlers():
        logger.handlers.clear()

    # Add console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(format_str or default_format))
    logger.addHandler(console_handler)

    # Ensure request_id is available on all records
    logger.addFilter(RequestContextFilter())

    # Prevent propagation to root to avoid duplicate logs
    logger.propagate = False

    return logger


# Default application logger
app_logger = setup_logger()


class RequestLogHandler(StreamHandler):
    def __init__(self, request_id: Optional[str] = None):
        self.logs: List[str] = []
        self.request_id = request_id
        self.active_connections: Dict[str, any] = {}  # pyright: ignore[reportGeneralTypeIssues]
        self.request_store: Dict[str, Dict] = {}
        super().__init__()
        self.addFilter(RequestIDFilter(request_id))

    def set_connections(self, connections, store):
        self.active_connections = connections
        self.request_store = store

    def emit(self, record):
        # Only called for matching request_id due to RequestIDFilter
        log_entry = self.format(record)
        self.logs.append(log_entry)

        if self.request_id and self.request_id in self.request_store:
            self.request_store[self.request_id]["logs"] = log_entry
            self.request_store[self.request_id]["all_logs"] = self.logs

            # Broadcast log to WebSocket if connected
            if self.request_id in self.active_connections:
                # Schedule send without blocking
                asyncio.create_task(self.broadcast_log(log_entry))

    async def broadcast_log(self, log_entry):
        if self.request_id in self.active_connections:
            try:
                await self.active_connections[self.request_id].send_json(
                    {"type": "log", "data": log_entry}
                )
            except Exception:
                # If sending fails, connection might be closed
                if self.request_id in self.active_connections:
                    del self.active_connections[self.request_id]


@asynccontextmanager
async def request_logging_context(request_id: str):
    """Async context manager to scope logs to a specific request.

    All logs within this context will carry request_id and will be streamed only
    to the matching WebSocket via RequestLogHandler.
    """
    token = current_request_id.set(request_id)
    try:
        yield
    finally:
        current_request_id.reset(token)
