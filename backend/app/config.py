"""Environment settings. Missing credentials never stop the app: the affected
connector reports itself as mock/disabled (spec Section 12 / 23)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent
DATA_DIR = Path(__file__).resolve().parent / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(ROOT_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    public_base_url: str = "http://localhost:8000"
    frontend_origin: str = "http://localhost:8000"  # web app is served by the backend
    jwt_secret: str = "change-me"
    jwt_expiry_hours: int = 24
    token_encryption_key: str = ""
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'lifeline.db').as_posix()}"
    connector_mode: str = "mock"  # live | mock
    llm_mode: str = "mock"  # live | mock
    timezone: str = "Asia/Kolkata"
    enable_scheduler: bool = True
    # Serverless hosting (e.g. Vercel) keeps the SQLite file in /tmp, which can be reset between
    # cold starts. When true, a valid session whose account vanished gets a fresh judge account.
    ephemeral_db: bool = False

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/sources/gmail/callback"
    google_login_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"
    gmail_poll_minutes: int = 15
    gmail_query: str = (
        '(due OR invoice OR renewal OR bill OR debited OR premium '
        'OR subscription OR receipt OR "payment")'
    )
    gmail_first_sync_days: int = 14  # how far back the first check of a newly connected inbox looks
    cron_secret: str = ""  # Vercel Cron sends "Authorization: Bearer <CRON_SECRET>"

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = "whatsapp:+14155238886"
    twilio_sandbox_join_code: str = ""  # e.g. "join bright-tiger" (Twilio console → Sandbox)

    anthropic_api_key: str = ""
    anthropic_model: str = ""
    llm_timeout_seconds: float = 20.0

    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:you@example.com"

    reminder_tick_minutes: int = 5
    reminder_repeat_cap: int = 3
    early_discount_min_pct: float = 2.0

    rate_limit_auth: str = "10/minute"
    rate_limit_ingest: str = "60/minute"

    # --- derived status helpers -------------------------------------------------
    @property
    def gmail_live(self) -> bool:
        return self.connector_mode == "live" and bool(
            self.google_client_id and self.google_client_secret and self.token_encryption_key
        )

    @property
    def google_login_live(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def twilio_live(self) -> bool:
        return self.connector_mode == "live" and bool(
            self.twilio_account_sid and self.twilio_auth_token
        )

    @property
    def llm_live(self) -> bool:
        return self.llm_mode == "live" and bool(self.anthropic_api_key and self.anthropic_model)

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)

    def front_url(self, path: str) -> str:
        """Where to send the browser in the web app. When the backend serves the app
        itself (judge setup), use a relative path so any port works."""
        if self.frontend_origin.rstrip("/") == self.public_base_url.rstrip("/"):
            return path
        return self.frontend_origin.rstrip("/") + path

    def missing_variables(self) -> dict[str, list[str]]:
        missing: dict[str, list[str]] = {}

        def need(group: str, names: list[str]) -> None:
            absent = [n for n in names if not getattr(self, n.lower())]
            if absent:
                missing[group] = absent

        if self.connector_mode == "live":
            need("gmail", ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "TOKEN_ENCRYPTION_KEY"])
            need("whatsapp", ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM"])
        if self.llm_mode == "live":
            need("llm", ["ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"])
        if self.jwt_secret == "change-me":
            missing.setdefault("app", []).append("JWT_SECRET (using insecure default)")
        return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()
