"""Tests for Slack Lists schema, models, and cell payload builders."""

from __future__ import annotations

import pytest

from slack_lists.models import (
    ListItem,
    ListSchema,
    build_cell_payload,
    extract_field_display,
)

SAMPLE_LIST_OBJ = {
    "id": "F0123456789",
    "title": "Project Tracker",
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
                        {"value": "OptTodo", "label": "To Do", "color": "blue"},
                        {"value": "OptProg", "label": "In Progress", "color": "yellow"},
                        {"value": "OptDone", "label": "Done", "color": "green"},
                    ]
                },
            },
            {
                "id": "ColOwner001",
                "name": "Assignee",
                "key": "assignee",
                "type": "todo_assignee",
            },
            {
                "id": "ColDone001",
                "name": "Completed",
                "key": "todo_completed",
                "type": "todo_completed",
            },
            {
                "id": "ColDue001",
                "name": "Due date",
                "key": "todo_due_date",
                "type": "todo_due_date",
            },
            {
                "id": "ColPrio001",
                "name": "Priority",
                "key": "rating",
                "type": "rating",
            },
        ]
    },
}


def test_schema_parsing_and_select_resolution() -> None:
    schema = ListSchema.from_slack_list(SAMPLE_LIST_OBJ)
    assert schema.title == "Project Tracker"
    assert schema.primary_column is not None
    assert schema.primary_column.id == "ColTitle001"

    status_col = schema.find_status_column("Status")
    assert status_col is not None
    assert schema.resolve_select_value(status_col, "in progress") == "OptProg"
    assert schema.resolve_select_value(status_col, "OptDone") == "OptDone"
    assert schema.format_select_value(status_col, "OptTodo") == "To Do"

    with pytest.raises(ValueError, match="Valid options"):
        schema.resolve_select_value(status_col, "Nonexistent")


def test_build_cell_payload_types() -> None:
    schema = ListSchema.from_slack_list(SAMPLE_LIST_OBJ)
    title_col = schema.find_column("Title")
    status_col = schema.find_column("Status")
    owner_col = schema.find_column("Assignee")
    assert title_col and status_col and owner_col

    title_cell = build_cell_payload(title_col, "Ship CLI", schema)
    assert title_cell["column_id"] == "ColTitle001"
    assert title_cell["rich_text"][0]["elements"][0]["elements"][0]["text"] == "Ship CLI"

    status_cell = build_cell_payload(status_col, "In Progress", schema, row_id="Rec00000001")
    assert status_cell == {
        "column_id": "ColStatus01",
        "row_id": "Rec00000001",
        "select": ["OptProg"],
    }

    user_cell = build_cell_payload(owner_col, "@alice", schema, user_lookup={"alice": "U012345"})
    assert user_cell == {"column_id": "ColOwner001", "user": ["U012345"]}

    done_col = schema.find_column("Completed")
    due_col = schema.find_column("Due date")
    prio_col = schema.find_column("Priority")
    assert done_col and due_col and prio_col
    assert build_cell_payload(done_col, "true", schema) == {
        "column_id": "ColDone001",
        "checkbox": True,
    }
    assert build_cell_payload(due_col, "2026-12-01", schema) == {
        "column_id": "ColDue001",
        "date": ["2026-12-01"],
    }
    assert build_cell_payload(prio_col, "3", schema) == {
        "column_id": "ColPrio001",
        "rating": [3],
    }


def test_extract_field_display() -> None:
    schema = ListSchema.from_slack_list(SAMPLE_LIST_OBJ)
    item = ListItem.from_slack(
        {
            "id": "Rec00000001",
            "fields": [
                {
                    "column_id": "ColTitle001",
                    "rich_text": [
                        {
                            "type": "rich_text",
                            "elements": [
                                {
                                    "type": "rich_text_section",
                                    "elements": [{"type": "text", "text": "Build Kanban CLI"}],
                                }
                            ],
                        }
                    ],
                },
                {"column_id": "ColStatus01", "select": ["OptProg"]},
                {"column_id": "ColOwner001", "user": ["U012345"]},
            ],
        }
    )

    assert (
        extract_field_display(
            item.get_raw_field("ColTitle001"), schema.find_column("Title"), schema
        )
        == "Build Kanban CLI"
    )
    assert (
        extract_field_display(
            item.get_raw_field("ColStatus01"), schema.find_column("Status"), schema
        )
        == "In Progress"
    )
    assert (
        extract_field_display(
            item.get_raw_field("ColOwner001"),
            schema.find_column("Assignee"),
            schema,
            user_map={"U012345": "@alice"},
        )
        == "@alice"
    )
