import os
import uuid
import time
import asyncio
import io
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from typing import Dict
from pydantic import BaseModel

from backend.engine.fetch import PESUAttendanceScraper
from backend.engine.chart import generate_graph
from backend.engine.attendance import AttendanceCalculator
from backend.engine.stream import app_logger, RequestLogHandler

load_dotenv()

BUNKABLE_THRESHOLD = int(os.getenv("BUNKABLE_THRESHOLD", "75"))

router = APIRouter()

# In-memory storage for active connections and request data
active_connections: Dict[str, WebSocket] = {}
request_store = {}

class AttendanceRequest(BaseModel):
    srn: str
    password: str

# Process attendance data in background
async def process_attendance_task(request_id):
    log_handler = RequestLogHandler(request_id)
    log_handler.setFormatter(app_logger.handlers[0].formatter)
    log_handler.set_connections(active_connections, request_store)
    
    # Use the app_logger instead of creating a new one
    app_logger.addHandler(log_handler)
    
    try:
        request_data = request_store[request_id]
        srn = request_data["srn"]
        password = request_data["password"]
        
        scraper = PESUAttendanceScraper(srn, password)
        scraper.login()
        attendance_data = scraper.fetch_attendance()
        app_logger.info("Generating attendance graph")
        graph = generate_graph(attendance_data, BUNKABLE_THRESHOLD, scraper.subject_mapping)

        formatted_attendance = []
        for item in attendance_data:
            attended, total = map(int, item[2].split("/"))
            formatted_attendance.append({
                "subject": scraper.subject_mapping.get(item[0], item[0]),
                "attended": attended,
                "total": total,
                "percentage": round((attended / total) * 100, 2),
                "bunkable": AttendanceCalculator.calculate_bunkable(
                    total, attended, BUNKABLE_THRESHOLD
                )
            })
        
        scraper.logout()
        
        # Store results
        request_store[request_id].update({
            "status": "complete",
            "attendance": formatted_attendance,
            "graph": graph,
            "all_logs": log_handler.logs
        })
        
        # Send results via WebSocket
        if request_id in active_connections:
            try:
                await active_connections[request_id].send_json({
                    "type": "result",
                    "data": {
                        "status": "complete",
                        "attendance": formatted_attendance,
                        "graph": graph
                    }
                })
            except Exception:
                pass  # Connection might be closed already
        
    except Exception as e:
        error_msg = f"Error processing request: {str(e)}"
        app_logger.error(error_msg)
        
        request_store[request_id].update({
            "status": "error",
            "detail": error_msg,
            "all_logs": log_handler.logs
        })
        
        # Send error via WebSocket
        if request_id in active_connections:
            try:
                await active_connections[request_id].send_json({
                    "type": "error",
                    "data": error_msg
                })
            except Exception:
                pass  # Connection might be closed already
    finally:
        app_logger.removeHandler(log_handler)
        
        # Clean up old requests periodically
        current_time = time.time()
        for req_id in list(request_store.keys()):
            if current_time - request_store[req_id]["timestamp"] > 120:  # 2 minutes timeout
                if req_id in request_store:
                    del request_store[req_id]

# Main WebSocket endpoint for all communication
@router.websocket("/ws/attendance")
async def websocket_attendance(websocket: WebSocket):
    await websocket.accept()
    request_id = None
    
    try:
        # First message should be authentication
        auth_message = await websocket.receive_json()
        
        # Handle initial authentication
        if auth_message.get("type") == "auth":
            data = auth_message.get("data", {})
            srn = data.get("srn")
            password = data.get("password")
            
            if not srn or not password:
                await websocket.send_json({
                    "type": "error",
                    "data": "Missing SRN or password"
                })
                return
            
            # Generate request ID and store connection
            request_id = str(uuid.uuid4())
            active_connections[request_id] = websocket
            
            # Store request data
            request_store[request_id] = {
                "status": "processing",
                "logs": "Request received. Starting process...",
                "all_logs": ["Request received. Starting process..."],
                "srn": srn,
                "password": password,
                "timestamp": time.time()
            }
            
            # Send acknowledgment with request ID
            await websocket.send_json({
                "type": "auth_success",
                "data": {
                    "requestId": request_id,
                    "message": "Authentication process started. Please wait for results."
                }
            })
            
            # Start background task to process attendance
            asyncio.create_task(process_attendance_task(request_id))
            
            # Keep connection alive and handle ping/pong
            while True:
                try:
                    # Wait for messages with a timeout
                    message = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=30.0
                    )
                    
                    # Handle ping messages
                    if message == "ping":
                        await websocket.send_json({"type": "pong"})
                    
                except asyncio.TimeoutError:
                    # Send a ping to check if client is still connected
                    try:
                        await websocket.send_json({"type": "ping"})
                    except:
                        # If sending fails, client is disconnected
                        break
                    
        else:
            # Invalid initial message
            await websocket.send_json({
                "type": "error",
                "data": "Please login with your SRN and password"
            })
            
    except WebSocketDisconnect:
        # Client disconnected
        pass
    except Exception as e:
        # Send error if possible
        try:
            await websocket.send_json({
                "type": "error",
                "data": f"WebSocket error: {str(e)}"
            })
        except:
            pass
    finally:
        # Clean up on disconnect
        if request_id and request_id in active_connections:
            del active_connections[request_id]

@router.get("/healthcheck")
async def healthcheck():
    return {"message": "Pong"}
