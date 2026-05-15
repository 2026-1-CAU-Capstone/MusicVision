import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
STORAGE_DIR = BASE_DIR / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
JOBS_DIR = STORAGE_DIR / "jobs"
OUTPUTS_DIR = STORAGE_DIR / "outputs"

APP_NAME = os.getenv("APP_NAME", "MusicVision OMR Service")
APP_VERSION = os.getenv("APP_VERSION", "0.1.0")

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}


for directory in (UPLOADS_DIR, JOBS_DIR, OUTPUTS_DIR):
    directory.mkdir(parents=True, exist_ok=True)
