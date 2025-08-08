import uuid
import json
import time
import asyncio

from typing import Dict, List, Optional, Any

from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
    HTTPException,
    status,
)

from pydantic import BaseModel, Field

from backend.engine.fetch import (
    PESUAttendanceScraper,
    fetch_student_attendance,
    ConfigurationError,
    AuthenticationError,
    AttendanceScrapingError,
)
from backend.engine.chart import generate_graph
from backend.engine.attendance import AttendanceCalculator
from backend.engine.stream import app_logger, RequestLogHandler, request_logging_context
from backend.core import mappings, settings


# Router and storage initialization
router = APIRouter()

# In-memory storage for active connections and request data
# Using Dict type hints for better code clarity
active_connections: Dict[str, WebSocket] = {}
request_store: Dict[str, Dict[str, Any]] = {}


class AttendanceRequest(BaseModel):
    """Request model for attendance data retrieval."""

    username: str = Field(
        ..., min_length=1, description="Student username/SRN in PESU format"
    )
    password: str = Field(
        ..., min_length=1, description="Student password for authentication"
    )


class AttendanceResponse(BaseModel):
    """Response model for attendance data."""

    attendance_data: List[List[str]] = Field(
        ..., description="Raw attendance data as list of rows"
    )
    subject_mapping: Dict[str, str] = Field(
        ..., description="Subject code to name mapping for the student's branch"
    )


async def process_attendance_task(request_id: str) -> None:
    # Set up logging for this specific request
    log_handler = RequestLogHandler(request_id)
    log_handler.setFormatter(app_logger.handlers[0].formatter)
    log_handler.set_connections(active_connections, request_store)

    app_logger.addHandler(log_handler)

    # Initialize scraper as None to handle edge cases
    scraper: Optional[PESUAttendanceScraper] = None

    # Ensure all logs in this task carry the request_id
    async with request_logging_context(request_id):
        try:
            # Retrieve request data from storage - validate existence
            if request_id not in request_store:
                raise AttendanceScrapingError(f"Request {request_id} not found")

            request_data = request_store[request_id]
            srn = request_data.get("srn")
            password = request_data.get("password")

            # Validate required fields exist
            if not srn or not password:
                raise AttendanceScrapingError("Missing SRN or password in request")

            app_logger.info(f"Starting attendance processing for SRN: {srn[:10]}")

            # Initialize scraper for subject mapping access
            scraper = PESUAttendanceScraper(srn, password)

            # Fetch attendance data using convenience function
            attendance_data = fetch_student_attendance(srn, password)

            if not attendance_data:
                raise AttendanceScrapingError("No attendance data retrieved")

            app_logger.info("Generating attendance visualization")

            # Generate attendance graph - requires subject mapping from scraper
            graph = generate_graph(
                attendance_data, settings.BUNKABLE_THRESHOLD, scraper.subject_mapping
            )

            # Format attendance data for client consumption
            formatted_attendance = _format_attendance_data(
                attendance_data, scraper.subject_mapping
            )

            # Store successful results in request store
            request_store[request_id].update(
                {
                    "status": "complete",
                    "attendance": formatted_attendance,
                    "graph": graph,
                    "all_logs": log_handler.logs,
                }
            )

            # Send results via WebSocket if connection is active
            await _send_websocket_message(
                request_id,
                {
                    "type": "result",
                    "data": {
                        "status": "complete",
                        "attendance": formatted_attendance,
                        "graph": graph,
                    },
                },
            )

            app_logger.info("Attendance processing completed successfully")

        except (AuthenticationError, AttendanceScrapingError) as e:
            # Handle specific scraping errors with detailed logging
            error_msg = f"Attendance processing error: {str(e)}"
            await _handle_processing_error(request_id, error_msg, log_handler)

        except Exception as e:
            # Handle unexpected errors with comprehensive logging
            error_msg = f"Unexpected error during processing: {str(e)}"
            await _handle_processing_error(request_id, error_msg, log_handler)

        finally:
            # Clean up logging handler to prevent memory leaks
            app_logger.removeHandler(log_handler)

            # Perform periodic cleanup of old requests
            _cleanup_old_requests()


def _format_attendance_data(
    attendance_data: List[List[str]], subject_mapping: Dict[str, str]
) -> List[Dict[str, Any]]:
    formatted_attendance: List[Dict[str, Any]] = []

    for item in attendance_data:
        try:
            # Validate minimum required fields
            if len(item) < 3:
                app_logger.warning(f"Skipping incomplete record: {item}")
                continue

            # Parse attendance ratio (format: "attended/total")
            attendance_parts = item[2].split("/")
            if len(attendance_parts) != 2:
                app_logger.warning(f"Invalid attendance format: {item[2]}")
                continue

            attended, total = map(int, attendance_parts)

            # Calculate percentage with division by zero protection
            percentage = round((attended / total) * 100, 2) if total > 0 else 0

            # Calculate bunkable classes using the calculator
            bunkable = AttendanceCalculator.calculate_bunkable(
                total, attended, settings.BUNKABLE_THRESHOLD
            )

            formatted_attendance.append(
                {
                    "subject": subject_mapping.get(item[0], item[0]),
                    "attended": attended,
                    "total": total,
                    "percentage": percentage,
                    "bunkable": bunkable,
                }
            )

        except (ValueError, IndexError) as e:
            app_logger.warning(f"Skipping invalid attendance record {item}: {e}")
            continue

    return formatted_attendance


async def _handle_processing_error(
    request_id: str, error_msg: str, log_handler: RequestLogHandler
) -> None:
    app_logger.error(error_msg)

    # Update request store with error information
    if request_id in request_store:
        request_store[request_id].update(
            {"status": "error", "detail": error_msg, "all_logs": log_handler.logs}
        )

    # Send error via WebSocket if connection is active
    await _send_websocket_message(request_id, {"type": "error", "data": error_msg})


async def _send_websocket_message(request_id: str, message: Dict[str, Any]) -> None:
    if request_id in active_connections:
        try:
            await active_connections[request_id].send_json(message)
        except Exception as e:
            app_logger.warning(f"Failed to send WebSocket message: {e}")


def _cleanup_old_requests() -> None:
    current_time = time.time()
    expired_requests: List[str] = []

    # Identify expired requests
    for req_id, request_data in request_store.items():
        request_timestamp = request_data.get("timestamp", 0)
        if current_time - request_timestamp > settings.REQUEST_TIMEOUT_SECONDS:
            expired_requests.append(req_id)

    # Remove expired requests safely
    for req_id in expired_requests:
        if req_id in request_store:
            del request_store[req_id]
            app_logger.debug(f"Cleaned up expired request: {req_id}")


@router.websocket("/ws/attendance")
async def websocket_attendance(websocket: WebSocket) -> None:
    await websocket.accept()
    request_id: Optional[str] = None

    try:
        # Wait for initial authentication message
        auth_message = await websocket.receive_json()

        # Process authentication request
        if auth_message.get("type") == "auth":
            request_id = await _handle_authentication(websocket, auth_message)

            if request_id:
                # Start background processing task
                asyncio.create_task(process_attendance_task(request_id))

                # Keep connection alive with ping/pong mechanism
                await _maintain_websocket_connection(websocket)
        else:
            # Invalid initial message type
            await websocket.send_json(
                {
                    "type": "error",
                    "data": "Please authenticate with your SRN and password",
                }
            )

    except WebSocketDisconnect:
        app_logger.info(f"WebSocket client disconnected: {request_id}")

    except Exception as e:
        app_logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json(
                {"type": "error", "data": f"WebSocket error: {str(e)}"}
            )
        except Exception:
            # Connection might already be closed, silently handle
            pass

    finally:
        # Clean up connection on disconnect
        if request_id and request_id in active_connections:
            del active_connections[request_id]
            app_logger.debug(f"Cleaned up WebSocket connection: {request_id}")


async def _handle_authentication(
    websocket: WebSocket, auth_message: Dict[str, Any]
) -> Optional[str]:
    data = auth_message.get("data", {})
    srn = data.get("srn")
    password = data.get("password")

    # Validate required credentials
    if not srn or not password:
        await websocket.send_json({"type": "error", "data": "Missing SRN or password"})
        return None

    # Generate unique request ID and store connection
    request_id = str(uuid.uuid4())
    active_connections[request_id] = websocket

    # Initialize request data storage
    request_store[request_id] = {
        "status": "processing",
        "logs": "Request received. Starting process...",
        "all_logs": ["Request received. Starting process..."],
        "srn": srn,
        "password": password,
        "timestamp": time.time(),
    }

    # Send authentication success response
    await websocket.send_json(
        {
            "type": "auth_success",
            "data": {
                "requestId": request_id,
                "message": "Authentication successful. Processing attendance data...",
            },
        }
    )

    app_logger.info(f"WebSocket authentication successful for SRN: {srn[:10]}")
    return request_id


async def _maintain_websocket_connection(websocket: WebSocket) -> None:
    while True:
        try:
            # Wait for client messages with timeout
            message = await asyncio.wait_for(
                websocket.receive_text(), timeout=settings.WEBSOCKET_PING_TIMEOUT
            )

            # Handle client ping messages (support both raw and JSON)
            if message == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                try:
                    parsed = json.loads(message)
                    if isinstance(parsed, dict) and parsed.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except json.JSONDecodeError:
                    # Ignore non-JSON, non-ping messages in keepalive
                    pass

        except asyncio.TimeoutError:
            # Send ping to check if client is still connected
            try:
                await websocket.send_json({"type": "ping"})
            except Exception:
                # If sending fails, client is disconnected
                break

        except WebSocketDisconnect:
            # Client disconnected gracefully
            break


@router.get("/healthcheck")
async def healthcheck() -> Dict[str, str]:
    return {"message": "Service is healthy", "status": "ok"}


@router.post("/attendance", response_model=AttendanceResponse)
async def get_attendance(request: AttendanceRequest) -> AttendanceResponse:
    try:
        # Fetch attendance data asynchronously to avoid blocking
        attendance_data = await asyncio.get_event_loop().run_in_executor(
            None, fetch_student_attendance, request.username, request.password
        )

        if attendance_data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No attendance data found for the provided credentials. "
                "Please verify your SRN and password.",
            )

        return AttendanceResponse(
            attendance_data=attendance_data, subject_mapping=mappings.SUBJECT_MAPPING
        )

    except ConfigurationError as error:
        app_logger.error(f"Configuration error: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Configuration error: {str(error)}",
        )
    except AuthenticationError as error:
        app_logger.warning(f"Authentication failed: {error}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {str(error)}",
        )
    except AttendanceScrapingError as error:
        app_logger.error(f"Scraping error: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve attendance data: {str(error)}",
        )
    except Exception as error:
        app_logger.error(f"Unexpected error: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {str(error)}",
        )
