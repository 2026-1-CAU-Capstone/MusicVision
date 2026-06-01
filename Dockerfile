FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    EASYOCR_MODULE_PATH=/models/easyocr \
    TORCH_HOME=/models/torch \
    POETRY_DYNAMIC_VERSIONING_BYPASS=0.1.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
COPY homr ./homr
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY pipeline ./pipeline
COPY time_sig_cnn ./time_sig_cnn

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/storage /models \
    && chown -R appuser:appuser /app /models

USER appuser

ARG PRELOAD_HOMR_MODELS=true
ARG PRELOAD_EASYOCR_MODELS=false

RUN if [ "$PRELOAD_HOMR_MODELS" = "true" ]; then python -m homr.main --init; fi
RUN if [ "$PRELOAD_EASYOCR_MODELS" = "true" ]; then python -c "import easyocr; easyocr.Reader(['en'], gpu=False)"; fi

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
