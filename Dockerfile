FROM python:3.13-slim-bookworm

LABEL org.opencontainers.image.source="https://github.com/sandavdesigns/pdf-convert" \
      org.opencontainers.image.description="Self-hosted Outlook MSG to PDF converter" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates \
        fonts-dejavu-core \
        libffi8 \
        libharfbuzz-subset0 \
        libjpeg62-turbo \
        libopenjp2-7 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --requirement requirements.txt

COPY app ./app
COPY wsgi.py .

RUN addgroup --system app \
    && adduser --system --ingroup app --home /nonexistent --no-create-home app

USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"]

CMD ["gunicorn", "--bind=0.0.0.0:8080", "--workers=2", "--threads=2", "--timeout=120", "--access-logfile=-", "--error-logfile=-", "wsgi:app"]
