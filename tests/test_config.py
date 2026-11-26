"""Tests for pydantic-settings configuration loading (.env and env vars)."""

from __future__ import annotations

from pathlib import Path

import pytest

from slack_lists.config import load_settings


def test_loads_from_dotenv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_LIST_ID", raising=False)
    monkeypatch.delenv("SLACK_STATUS_COLUMN", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "SLACK_TOKEN=xoxp-from-dotenv\nSLACK_LIST_ID=F0DOTENV123\nSLACK_STATUS_COLUMN=Stage\n",
        encoding="utf-8",
    )

    settings = load_settings(env_file=env_file)
    assert settings.require_token() == "xoxp-from-dotenv"
    assert settings.require_list_id() == "F0DOTENV123"
    assert settings.slack_status_column == "Stage"


def test_env_var_takes_precedence_over_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SLACK_TOKEN=xoxp-from-dotenv\nSLACK_LIST_ID=F0DOTENV123\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SLACK_TOKEN", "xoxp-from-env")
    monkeypatch.setenv("SLACK_LIST_ID", "F0ENV999")

    settings = load_settings(env_file=env_file)
    assert settings.require_token() == "xoxp-from-env"
    assert settings.require_list_id() == "F0ENV999"
    assert settings.require_list_id(override="F0CLI777") == "F0CLI777"


def test_missing_token_raises_helpful_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    empty_env = tmp_path / ".env"
    empty_env.write_text("", encoding="utf-8")

    settings = load_settings(env_file=empty_env)
    with pytest.raises(ValueError, match="SLACK_TOKEN"):
        settings.require_token()
