"""
Application settings loaded from environment variables.

Uses pydantic-settings so every env var is typed, validated, and has a
default (where appropriate). Settings are loaded once at startup via
get_settings() and cached.

Never log the full Settings object — it contains secrets. If you need to
debug, log individual non-sensitive fields.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All application settings, loaded from env or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ----- Core -----
    env: Literal["dev", "prod"] = "dev"
    app_version: str = "0.1.0"
    public_base_url: str = "http://localhost:8080"
    cors_origins: str = "http://localhost:8080"
    log_level: str = "INFO"

    # ----- Database -----
    database_url: str = "sqlite+aiosqlite:////data/app.db"

    # ----- Auth / Sessions -----
    jwt_secret: str = "changeme_generate_a_real_32_byte_hex_string"
    jwt_expiry_days: int = 30

    # ----- Google OAuth2 -----
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8080/api/auth/google/callback"

    # ----- SMTP (OTP email) -----
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@example.com"
    smtp_from_name: str = "AI Roadmap"
    smtp_use_tls: bool = False  # True for port 465 (SSL), False for port 587 (STARTTLS)

    # ----- AI Providers -----
    gemini_api_key: str = ""
    # Default flash model — 2.5 has materially stronger reasoning than 1.5 at
    # the same price. Used for discovery, generation, review, light refine.
    gemini_model: str = "gemini-2.5-flash"
    # Pro model reserved for deep refinement and hard reasoning tasks. ~15× more
    # expensive than flash per output token, but still ~1.5× cheaper than Claude
    # Sonnet and much smarter than flash on multi-constraint rewrites.
    gemini_pro_model: str = "gemini-2.5-pro"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    cerebras_api_key: str = ""
    cerebras_model: str = "llama3.1-8b"
    mistral_api_key: str = ""
    mistral_model: str = "mistral-small-latest"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    sambanova_api_key: str = ""
    sambanova_model: str = "Meta-Llama-3.3-70B-Instruct"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    topic_dedup_similarity_threshold: float = 0.88

    # Admin API keys — separate from regular API keys, used ONLY for the
    # provider-authoritative daily spend sync. Revoke independently if compromised.
    # Create at:
    #   OpenAI:    https://platform.openai.com/settings/organization/admin-keys
    #   Anthropic: https://platform.claude.com/settings/admin-keys
    #              (requires Organization account — individual accounts can't create admin keys)
    openai_admin_api_key: str = ""
    anthropic_admin_api_key: str = ""

    # How many days of raw ai_usage_log rows to keep. Older rows are archived
    # into ai_usage_log_archive (or deleted if archive disabled). Long-term
    # aggregates live in provider_daily_spend.
    ai_usage_log_retention_days: int = 90

    # ----- GitHub (optional) -----
    github_token: str = ""

    # ----- Maintainer -----
    maintainer_email: str = "you@example.com"

    # ----- Computed -----
    @property
    def cors_origins_list(self) -> list[str]:
        """Split comma-separated CORS origins."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    # ----- Validators -----
    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, v: str, info) -> str:
        """In prod, refuse to start with the default or a short secret."""
        # We can't access other fields here reliably in v2, so the env check
        # is done in _validate_prod_settings() below at startup time.
        if len(v) < 16:
            raise ValueError("jwt_secret must be at least 16 characters")
        return v

    def _validate_prod_settings(self) -> None:
        """Called after construction in prod to enforce stricter rules."""
        if not self.is_prod:
            return
        if self.jwt_secret == "changeme_generate_a_real_32_byte_hex_string":
            raise ValueError(
                "Refusing to start in prod with the default jwt_secret. "
                "Generate a real one: openssl rand -hex 32"
            )
        if len(self.jwt_secret) < 32:
            raise ValueError("In prod, jwt_secret must be at least 32 characters")
        if not self.google_client_id or not self.google_client_secret:
            raise ValueError("Google OAuth credentials are required in prod")
        # Claude Code: add more prod-required checks as features are added
        # (e.g. gemini_api_key once evaluation is wired)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor — call this everywhere instead of constructing Settings directly."""
    s = Settings()
    s._validate_prod_settings()
    return s
