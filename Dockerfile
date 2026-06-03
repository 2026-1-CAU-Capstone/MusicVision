FROM python:3.11

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    EASYOCR_MODULE_PATH=/models/easyocr \
    TORCH_HOME=/models/torch \
    POETRY_DYNAMIC_VERSIONING_BYPASS=0.1.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libxcb1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
COPY homr ./homr
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision \
    && pip install --no-cache-dir -r requirements.txt

ARG INSTALL_PADDLEOCR_RESCUE=false
RUN if [ "$INSTALL_PADDLEOCR_RESCUE" = "true" ]; then \
        python -m venv /opt/paddleocr-venv \
        && /opt/paddleocr-venv/bin/pip install --no-cache-dir --upgrade pip \
        && /opt/paddleocr-venv/bin/pip install --no-cache-dir paddleocr==3.6.0 paddlepaddle==3.3.1; \
    fi

COPY app ./app
COPY pipeline ./pipeline
COPY scripts ./scripts
COPY time_sig_cnn ./time_sig_cnn

ARG PRELOAD_HOMR_MODELS=true
ARG PRELOAD_EASYOCR_MODELS=false

RUN if [ "$PRELOAD_HOMR_MODELS" = "true" ]; then python -m homr.main --init; fi
RUN if [ "$PRELOAD_EASYOCR_MODELS" = "true" ]; then python -c "import easyocr; easyocr.Reader(['en'], gpu=False)"; fi

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/storage /models \
    && if [ -d /opt/paddleocr-venv ]; then chown -R appuser:appuser /opt/paddleocr-venv; fi \
    && chown -R appuser:appuser /app /models

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
