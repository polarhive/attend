# main.py

import os
import shutil
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from backend.api.api import router as api_router
from fastapi.staticfiles import StaticFiles

if not os.path.isfile(".env"):
    print(".env file missing. Copying from .env.example...")
    shutil.copy(".env.example", ".env")

load_dotenv()

app = FastAPI()

app.include_router(api_router, prefix="/api")

app.mount("/", StaticFiles(directory="frontend/web", html=True), name="frontend")


if __name__ == "__main__":
    port = int(os.getenv("PORT"))
    uvicorn.run(app, host="0.0.0.0", port=port)
