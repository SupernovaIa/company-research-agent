"""Application settings loaded from the repo-root .env (pydantic-settings, ADR-001).

The .env file lives at the repository root (one level above ``backend/``), not
inside ``backend/``. This module resolves the path relative to its own location
so the settings work from any working directory — ``cd backend && uv run …`` or
``uv run --project backend …`` both find the same file.

Precedence (highest to lowest):
  1. Environment variables already exported in the shell.
  2. The .env file at the repo root.
  3. The default values defined below.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root is two directories above this file:
#   backend/app/config.py → backend/app → backend → <repo-root>
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        # pydantic-settings maps UPPER_CASE env vars to lower_snake_case fields
        # automatically, so no aliases needed.
    )

    # --- Anthropic ---------------------------------------------------------
    anthropic_api_key: str = ""

    # --- Langfuse (optional) -----------------------------------------------
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    # Primary: LANGFUSE_BASE_URL (used in new Langfuse SDK and the .env template).
    # Fallback: LANGFUSE_HOST (legacy name still accepted by the old SDK).
    langfuse_base_url: str = ""
    langfuse_host: str = ""  # legacy fallback; prefer langfuse_base_url

    @property
    def langfuse_effective_host(self) -> str:
        """Return the Langfuse host, preferring LANGFUSE_BASE_URL over LANGFUSE_HOST."""
        return (
            self.langfuse_base_url
            or self.langfuse_host
            or "https://cloud.langfuse.com"
        )

    # --- Agent loop limits (ADR-007) ----------------------------------------
    # Provisional values for block-C; recalibrated against the eval set in block-E.
    agent_max_turns: int = 20    # hard limit; recalibrate against eval set in block-H
    agent_budget_usd: float = 0.50  # ADR-007 range 0.30–0.80; provisional for block-E
    agent_timeout_s: int = 120   # Anthropic client timeout per request (seconds)

    # --- Serving ---------------------------------------------------------------
    rate_limit_per_minute: int = 10


settings = Settings()
