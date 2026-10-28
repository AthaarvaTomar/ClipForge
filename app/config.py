from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "ClipForge AI"
    API_V1_PREFIX: str = "/api"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "sqlite:///./clipforge.db"

    # Redis & Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    CELERY_TASK_ALWAYS_EAGER: bool = False

    # AI & Stock Services
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"
    PEXELS_API_KEY: str = ""
    PIXABAY_API_KEY: str = ""

    # Security & Access
    API_KEY: str | None = None
    CORS_ORIGINS: list[str] = ["*"]

    # Observability & Limits
    LOG_LEVEL: str = "INFO"
    RENDER_CONCURRENCY_LIMIT: int = 2
    FFMPEG_TIMEOUT_SECONDS: float = 600.0
    AI_TIMEOUT_SECONDS: float = 60.0
    TIMELINE_SNAPSHOT_INTERVAL: int = 10

    # Storage paths and abstraction
    STORAGE_BACKEND: str = "local"  # "local" or "minio"
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "clipforge"
    MINIO_SECURE: bool = False

    UPLOAD_DIR: Path = Path("./data/uploads")
    OUTPUT_DIR: Path = Path("./data/outputs")
    PROXY_DIR: Path = Path("./data/proxies")
    MAX_UPLOAD_SIZE_MB: int = 500

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
