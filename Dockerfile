# KTR Kiosk Backend — production image
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app
COPY run.py .

# Gunicorn + Uvicorn workers (same stack as many FastAPI production setups)
ENV WEB_CONCURRENCY=2
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/ || exit 1

# shell form so WEB_CONCURRENCY from `docker run -e` / compose is applied at runtime
CMD ["/bin/sh", "-c", "exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8080 --workers ${WEB_CONCURRENCY} --access-logfile - --error-logfile -"]
