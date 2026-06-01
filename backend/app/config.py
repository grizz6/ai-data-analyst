from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "AI Data Analyst Agent"
    upload_dir: Path = Path(__file__).resolve().parent.parent / "uploads"
    max_upload_mb: int = 500
    missing_threshold_drop: float = 0.9
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    class Config:
        env_prefix = "ADA_"


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
