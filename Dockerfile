# ==============================================================================
# Dockerfile — ClipForge AI Backend & Workers
# Multi-purpose container for FastAPI Application & Distributed Celery Workers
# ==============================================================================

# 1. Base Image: Official lightweight Python 3.11 Debian image
FROM python:3.11-slim

# 2. Environment Configurations:
# - PYTHONDONTWRITEBYTECODE: Prevents Python from creating .pyc files inside the image
# - PYTHONUNBUFFERED: Flushes stdout and stderr immediately (essential for docker logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 3. Set standard working directory
WORKDIR /app

# 4. Install OS-level system dependencies:
#    - ffmpeg & ffprobe: Video processing, audio extraction, transcoding, filtergraphs
#    - fontconfig & fonts-dejavu-core: Required by FFmpeg for ASS subtitle rendering
#    - curl: Used for container healthchecks
#    - build-essential: Compilers for native Python wheels (ctranslate2, rapidfuzz, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fontconfig \
    fonts-dejavu-core \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 5. Dependency Layer Caching:
# Copy ONLY requirements.txt first. Docker caches this layer, so changing code
# in app/ will NOT trigger a slow reinstall of all Python packages.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 6. Copy application code and database migration files
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .

# 7. Ensure media directories exist inside container
RUN mkdir -p data/uploads data/outputs data/proxies

# 8. Expose HTTP port for FastAPI
EXPOSE 8000

# 9. Default command runs FastAPI with Uvicorn.
# (Note: In docker-compose.yml, Celery worker services override this command)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
