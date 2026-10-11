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
    max_excel_unzipped_mb: int = 100
    missing_threshold_drop: float = 0.9
    # Built React app to serve at "/", if present (see app/frontend.py).
    frontend_dist: str = str(BACKEND_DIR.parent / "frontend" / "dist")
    # Example file offered on the upload screen ("Try the sample sales data").
    sample_data_path: str = str(BACKEND_DIR.parent / "sample-data" / "sales_sample.csv")
    # SQLite file holding stored analyses; ":memory:" keeps them in memory only.
    database_path: str = str(BACKEND_DIR / "data" / "ada.sqlite3")
    session_ttl_minutes: int = 60
    max_sessions: int = 20
    # Requests allowed per visitor (IP address) per hour; 0 turns a limit off.
    uploads_per_hour: int = 10
    questions_per_hour: int = 30
    # Reverse proxies in front of the app that append to X-Forwarded-For (1 on most
    # hosts). 0 means the app is reached directly and the header is ignored, since
    # a visitor could otherwise write any address into it.
    trusted_proxy_hops: int = 0
    # A header the hosting edge overwrites with the visitor's address (e.g.
    # "true-client-ip" behind Render's Cloudflare edge). Takes priority when set
    # and present; leave empty when nothing in front of the app sets it.
    client_ip_header: str = ""
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
