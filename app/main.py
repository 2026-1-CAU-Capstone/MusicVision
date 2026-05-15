from fastapi import FastAPI

from app.config import APP_NAME, APP_VERSION
from app.routes import router


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Minimal OMR microservice used by the Jazzify Spring Boot backend.",
)

app.include_router(router)
