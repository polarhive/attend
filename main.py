# main.py

import os
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from backend.api.api import router as api_router

load_dotenv()

app = FastAPI()

app.include_router(api_router, prefix="/api")

@app.get("/")
async def serve_index():
    return FileResponse("frontend/web/index.html")

@app.get("/favicon.ico")
async def serve_index():
    return FileResponse("frontend/web/favicon.ico")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

