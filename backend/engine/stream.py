import os
import logging
import asyncio
from typing import List, Dict, Optional
from logging import StreamHandler

# Configure default logging level from environment
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
default_format = "%(asctime)s - %(levelname)s - %(message)s"

def setup_logger(name=None, level=None, format_str=None):
    """Set up and return a logger with the specified configuration"""
    logger = logging.getLogger(name)
    logger.setLevel(level or log_level)
    
    # Clear existing handlers to avoid duplicates
    if logger.hasHandlers():
        logger.handlers.clear()
    
    # Add console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(format_str or default_format))
    logger.addHandler(console_handler)
    
    return logger

# Default application logger
app_logger = setup_logger()

class RequestLogHandler(StreamHandler):
    """Custom log handler that captures logs and can broadcast to WebSockets"""
    
    def __init__(self, request_id=None):
        self.logs: List[str] = []
        self.request_id = request_id
        self.active_connections: Dict[str, any] = {}
        self.request_store: Dict[str, Dict] = {}
        super().__init__()
        
    def set_connections(self, connections, store):
        """Set the active connections and request store references"""
        self.active_connections = connections
        self.request_store = store
        
    def emit(self, record):
        log_entry = self.format(record)
        self.logs.append(log_entry)
        
        if self.request_id and self.request_id in self.request_store:
            self.request_store[self.request_id]["logs"] = log_entry
            self.request_store[self.request_id]["all_logs"] = self.logs
            
            # Broadcast log to WebSocket if connected
            if self.request_id in self.active_connections:
                asyncio.create_task(self.broadcast_log(log_entry))
    
    async def broadcast_log(self, log_entry):
        if self.request_id in self.active_connections:
            try:
                await self.active_connections[self.request_id].send_json({
                    "type": "log", 
                    "data": log_entry
                })
            except Exception:
                # If sending fails, connection might be closed
                if self.request_id in self.active_connections:
                    del self.active_connections[self.request_id]