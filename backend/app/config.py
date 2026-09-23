from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Loaded from ADA_* environment variables, or backend/.env if present."""

    model_config = SettingsConfigDict(
        env_prefix="ADA_",
        env_file=BACKEND_DIR / ".env",
        extra="ignore",
    )

    app_name: str = "AI Data Analyst Agent"
    max_upload_mb: int = 10
    missing_threshold_drop: float = 0.9
    session_ttl_minutes: int = 60
    max_sessions: int = 20
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Language model used only to explain results. Any OpenAI-compatible
    # chat completions endpoint works; empty key means rule-based text.
    llm_api_key: str = ""
    llm_base_url: str = "https://api.groq.com/openai/v1"
    # Llama 4 Scout was retired on Groq on 2026-07-17; Llama 3.3 70B is still in production there.
    llm_model: str = "llama-3.3-70b-versatile"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key.strip())


settings = Settings()
