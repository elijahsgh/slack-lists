"""End-to-end CLI tests with a mocked Slack WebClient."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from typer.testing import CliRunner

from slack_lists import cli
from slack_lists.client import SlackListsClient

runner = CliRunner()

SAMPLE_SCHEMA_LIST = {
    "id": "F0BOARD1234",
    "title": "Q4 Roadmap",
    "list_metadata": {
        "schema": [
            {
                "id": "ColTitle001",
                "name": "Title",
                "key": "title",
                "type": "text",
                "is_primary_column": True,
            },
            {
                "id": "ColStatus01",
                "name": "Status",
                "key": "status",
                "type": "select",
                "options": {
                    "choices": [
                        {"value": "OptTodo", "label": "To Do"},
                        {"value": "OptProg", "label": "In Progress"},
                        {"value": "OptDone", "label": "Done"},
                    ]
                },
            },
            {
                "id": "ColOwner001",
                "name": "Assignee",
                "key": "assignee",
                "type": "todo_assignee",
            },
        ]
    },
}

SAMPLE_ITEMS = [
    {
        "id": "Rec00000001",
        "fields": [
            {"column_id": "ColTitle001", "text": "Write README"},
            {"column_id": "ColStatus01", "select": ["OptDone"]},
        ],
    },
    {
        "id": "Rec00000002",
        "fields": [
            {"column_id": "ColTitle001", "text": "Build CLI"},
            {"column_id": "ColStatus01", "select": ["OptTodo"]},
            {"column_id": "ColOwner001", "user": ["U012345"]},
        ],
    },
]


def _make_mock_web_client() -> MagicMock:
    web = MagicMock()
    web.slackLists_items_list.return_value = {
        "ok": True,
        "items": SAMPLE_ITEMS,
        "response_metadata": {},
    }
    web.slackLists_items_info.return_value = {
        "ok": True,
        "list": SAMPLE_SCHEMA_LIST,
        "record": SAMPLE_ITEMS[0],
    }
    web.slackLists_items_create.return_value = {
        "ok": True,
        "item": {"id": "Rec00000003", "fields": []},
    }
    web.slackLists_items_update.return_value = MagicMock(data={"ok": True})
    web.slackLists_items_delete.return_value = MagicMock(data={"ok": True})
    web.users_list.return_value = {
        "ok": True,
        "members": [{"id": "U012345", "name": "alice", "profile": {"display_name": "Alice"}}],
        "response_metadata": {},
    }
    web.conversations_history.return_value = {
        "ok": True,
        "messages": [
            {
                "ts": "1795558562.511359",
                "subtype": "list_record_comment",
                "slack_list": {"list_id": "F0BOARD1234", "list_record_id": "Rec00000002"},
                "reply_count": 1,
            }
        ],
        "response_metadata": {},
    }
    web.conversations_replies.return_value = {
        "ok": True,
        "messages": [
            {"ts": "1795558562.511359", "user": "USLACKBOT", "text": "A comment was added"},
            {"ts": "1795558904.428919", "user": "U012345", "text": "Looks great!"},
        ],
        "response_metadata": {},
    }
    return web


@pytest.fixture
def mocked_cli(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    web = _make_mock_web_client()
    monkeypatch.setenv("SLACK_TOKEN", "xoxp-test-token")
    monkeypatch.setenv("SLACK_LIST_ID", "F0BOARD1234")

    def fake_client_factory(token: str, web_client: Any = None) -> SlackListsClient:
        return SlackListsClient(token=token, web_client=web)

    monkeypatch.setattr(cli, "SlackListsClient", fake_client_factory)
    return web


def test_board_command_renders_lanes(mocked_cli: MagicMock) -> None:
    result = runner.invoke(cli.app, ["board"])
    assert result.exit_code == 0
    assert "Q4 Roadmap" in result.stdout
    assert "To Do (1)" in result.stdout
    assert "Done (1)" in result.stdout
    assert "Build CLI" in result.stdout
    assert "(1) comment" in result.stdout
    assert "Assignee: @Alice" in result.stdout
    assert "Assignee: Unassigned" in result.stdout


def test_schema_command(mocked_cli: MagicMock) -> None:
    result = runner.invoke(cli.app, ["schema"])
    assert result.exit_code == 0
    assert "ColStatus01" in result.stdout
    assert "In Progress" in result.stdout


def test_add_command(mocked_cli: MagicMock) -> None:
    result = runner.invoke(cli.app, ["add", "Ship v1", "--status", "To Do"])
    assert result.exit_code == 0
    assert "Rec00000003" in result.stdout
    mocked_cli.slackLists_items_create.assert_called_once()
    kwargs = mocked_cli.slackLists_items_create.call_args.kwargs
    assert kwargs["list_id"] == "F0BOARD1234"
    assert kwargs["initial_fields"][1] == {"column_id": "ColStatus01", "select": ["OptTodo"]}


def test_move_command_by_index(mocked_cli: MagicMock) -> None:
    result = runner.invoke(cli.app, ["move", "2", "In Progress"])
    assert result.exit_code == 0
    assert "In Progress" in result.stdout
    mocked_cli.slackLists_items_update.assert_called_once_with(
        list_id="F0BOARD1234",
        cells=[{"column_id": "ColStatus01", "row_id": "Rec00000002", "select": ["OptProg"]}],
    )


def test_show_command_includes_comments(mocked_cli: MagicMock) -> None:
    result = runner.invoke(cli.app, ["show", "2"])
    assert result.exit_code == 0
    assert "Build CLI" in result.stdout
    assert "(1) comment" in result.stdout
    assert "@Alice" in result.stdout
    assert "Looks great!" in result.stdout


def test_show_json_and_yaml(mocked_cli: MagicMock) -> None:
    res_json = runner.invoke(cli.app, ["show", "2", "--json"])
    assert res_json.exit_code == 0
    data = json.loads(res_json.stdout)
    assert data["id"] == "Rec00000002"
    assert data["comment_count"] == 1
    assert data["comments"][0]["text"] == "Looks great!"

    res_yaml = runner.invoke(cli.app, ["show", "2", "--yaml"])
    assert res_yaml.exit_code == 0
    ydata = yaml.safe_load(res_yaml.stdout)
    assert ydata["id"] == "Rec00000002"
    assert ydata["comments"][0]["author"] == "@Alice"


def test_board_yaml_and_mutually_exclusive_flags(mocked_cli: MagicMock) -> None:
    res_yaml = runner.invoke(cli.app, ["board", "--yaml"])
    assert res_yaml.exit_code == 0
    ydata = yaml.safe_load(res_yaml.stdout)
    assert ydata["list_id"] == "F0BOARD1234"
    assert len(ydata["items"]) == 2
    assert ydata["items"][0]["comment_count"] == 0
    assert ydata["items"][0]["comments"] == []
    assert ydata["items"][1]["comment_count"] == 1
    assert ydata["items"][1]["comments"][0]["author"] == "@Alice"
    assert ydata["items"][1]["comments"][0]["text"] == "Looks great!"

    res_both = runner.invoke(cli.app, ["board", "--json", "--yaml"])
    assert res_both.exit_code == 1


def test_rm_command_with_yes(mocked_cli: MagicMock) -> None:
    result = runner.invoke(cli.app, ["rm", "1", "--yes"])
    assert result.exit_code == 0
    mocked_cli.slackLists_items_delete.assert_called_once_with(
        list_id="F0BOARD1234",
        id="Rec00000001",
    )
