import logging

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import APP_NAME, APP_VERSION


def _configure_application_logging() -> None:
    logger = logging.getLogger("musicvision")

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        logger.addHandler(handler)

    logger.setLevel(logging.INFO)
    logger.propagate = False


_configure_application_logging()


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Minimal OMR microservice used by the Jazzify Spring Boot backend.",
)

app.include_router(api_router)
