from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import APP_NAME, APP_VERSION


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Minimal OMR microservice used by the Jazzify Spring Boot backend.",
)

app.include_router(api_router)
