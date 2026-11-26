"""Application settings loaded from environment variables or a .env file."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

GLOBAL_ENV_FILE = Path.home() / ".config" / "slack-lists" / ".env"


class Settings(BaseSettings):
    """Configuration for slack-lists.

    Precedence (highest to lowest):
    1. Environment variables
    2. Local `.env` in current working directory
    3. Global `~/.config/slack-lists/.env`
    """

    model_config = SettingsConfigDict(
        env_file=(GLOBAL_ENV_FILE, ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    slack_token: SecretStr | None = Field(
        default=None,
        description="Slack User Token (xoxp-...) or Bot Token (xoxb-...).",
    )
    slack_app_token: SecretStr | None = Field(
        default=None,
        description="Optional Slack App-Level Token (xapp-...).",
    )
    slack_list_id: str | None = Field(
        default=None,
        description="Default Slack List ID (F0...) from the Slack List URL.",
    )
    slack_status_column: str = Field(
        default="Status",
        description="Name of the select column used to group Kanban columns.",
    )

    def require_token(self) -> str:
        """Return the Slack token string or raise a helpful ValueError."""
        if self.slack_token is None or not self.slack_token.get_secret_value().strip():
            raise ValueError(
                "Missing SLACK_TOKEN. Set the SLACK_TOKEN environment variable or add it to .env."
            )
        return self.slack_token.get_secret_value().strip()

    def require_list_id(self, override: str | None = None) -> str:
        """Return the list ID (preferring CLI override) or raise a helpful ValueError."""
        list_id = (override or self.slack_list_id or "").strip()
        if not list_id:
            raise ValueError(
                "Missing SLACK_LIST_ID. Pass --list-id, set SLACK_LIST_ID in your environment, "
                "or add it to .env."
            )
        return list_id


def load_settings(env_file: Path | None = None) -> Settings:
    """Load settings from environment variables and an optional .env file."""
    if env_file is not None:
        return Settings(_env_file=env_file)  # type: ignore[call-arg]
    return Settings()
