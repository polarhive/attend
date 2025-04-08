import os
import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from backend.engine.fetch import PESUAttendanceScraper
from backend.engine.chart import generate_graph
from backend.engine.attendance import AttendanceCalculator

load_dotenv()

BUNKABLE_THRESHOLD = int(os.getenv("BUNKABLE_THRESHOLD", "75"))

router = APIRouter()

@router.post("/attendance")
async def get_attendance(request: Request):
    data = await request.json()
    srn = data.get("srn")
    password = data.get("password")

    if not srn or not password:
        return JSONResponse(status_code=400, content={"detail": "Missing SRN or password"})

    try:
        scraper = PESUAttendanceScraper(srn, password)
        scraper.login()
        attendance_data = PESUAttendanceScraper.fetch_attendance(scraper)        
        scraper.logout()

        if not attendance_data:
            return JSONResponse(status_code=404, content={"detail": "Attendance data not found"})

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

        return {
            "logs": "Attendance fetched successfully",
            "attendance": formatted_attendance,
            "graph": graph
        }
    except Exception as e:
        logging.error(f"Error occurred: {str(e)}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@router.get("/healthcheck")
async def healthcheck():
    return {"message": "Pong"}
