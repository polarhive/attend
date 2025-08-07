import uvicorn
from fastapi import FastAPI

from backend.core import settings
from backend.api import api_router
from fastapi.staticfiles import StaticFiles


app = FastAPI()

app.include_router(api_router, prefix="/api")
app.mount("/", StaticFiles(directory="frontend/web", html=True), name="frontend")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=True)
