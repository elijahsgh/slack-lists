"""Data models and cell serialization helpers for Slack Lists."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SelectChoice(BaseModel):
    """A single option in a Slack List `select` column."""

    value: str
    label: str
    color: str | None = None


class ColumnSchema(BaseModel):
    """Definition of a column in `list_metadata.schema`."""

    id: str
    name: str
    key: str | None = None
    type: str = "text"
    is_primary_column: bool = False
    choices: list[SelectChoice] = Field(default_factory=list)

    @classmethod
    def from_slack(cls, raw: dict[str, Any]) -> ColumnSchema:
        options = raw.get("options") or {}
        raw_choices = options.get("choices") or []
        choices: list[SelectChoice] = []
        for ch in raw_choices:
            if isinstance(ch, dict):
                value = str(ch.get("value") or ch.get("id") or ch.get("label") or "")
                label = str(ch.get("label") or ch.get("name") or value)
                if value:
                    choices.append(SelectChoice(value=value, label=label, color=ch.get("color")))
            elif isinstance(ch, str):
                choices.append(SelectChoice(value=ch, label=ch))

        return cls(
            id=str(raw["id"]),
            name=str(raw.get("name") or raw.get("key") or raw["id"]),
            key=raw.get("key"),
            type=str(raw.get("type") or "text"),
            is_primary_column=bool(raw.get("is_primary_column", False)),
            choices=choices,
        )


class ListSchema(BaseModel):
    """Schema metadata for a Slack List."""

    list_id: str
    title: str = "Slack List"
    columns: list[ColumnSchema] = Field(default_factory=list)

    @classmethod
    def from_slack_list(cls, list_obj: dict[str, Any], list_id: str | None = None) -> ListSchema:
        metadata = list_obj.get("list_metadata") or {}
        raw_schema = metadata.get("schema") or []
        columns = [ColumnSchema.from_slack(col) for col in raw_schema if "id" in col]
        return cls(
            list_id=str(list_obj.get("id") or list_id or ""),
            title=str(list_obj.get("title") or list_obj.get("name") or "Slack List"),
            columns=columns,
        )

    @property
    def primary_column(self) -> ColumnSchema | None:
        for col in self.columns:
            if col.is_primary_column:
                return col
        return self.columns[0] if self.columns else None

    def column_by_id(self, column_id: str) -> ColumnSchema | None:
        for col in self.columns:
            if col.id == column_id:
                return col
        return None

    def find_column(self, name_or_id: str) -> ColumnSchema | None:
        target = name_or_id.strip().lower()
        for col in self.columns:
            if col.id.lower() == target:
                return col
        for col in self.columns:
            if col.name.lower() == target or (col.key and col.key.lower() == target):
                return col
        return None

    def find_status_column(self, preferred_name: str = "Status") -> ColumnSchema | None:
        preferred = self.find_column(preferred_name)
        if preferred is not None and preferred.type == "select":
            return preferred
        for col in self.columns:
            if col.type == "select":
                return col
        return None

    def resolve_select_value(self, col: ColumnSchema, user_input: str) -> str:
        """Map a user-supplied label or option value to the underlying Slack select value."""
        needle = user_input.strip().lower()
        for choice in col.choices:
            if choice.value.lower() == needle or choice.label.lower() == needle:
                return choice.value
        if col.choices:
            valid = ", ".join(f"{c.label!r}" for c in col.choices)
            raise ValueError(
                f"Unknown option {user_input!r} for column {col.name!r}. Valid options: {valid}"
            )
        return user_input.strip()

    def format_select_value(self, col: ColumnSchema, raw_value: str) -> str:
        """Map an underlying Slack select value (e.g. Opt...) to its display label."""
        for choice in col.choices:
            if choice.value == raw_value or choice.label == raw_value:
                return choice.label
        return raw_value


class ListComment(BaseModel):
    """A comment posted in a Slack List item's thread."""

    ts: str
    user: str
    text: str


class ListItem(BaseModel):
    """A single row/card in a Slack List."""

    id: str
    raw_fields: list[dict[str, Any]] = Field(default_factory=list)
    date_created: int | None = None
    is_archived: bool = False

    @classmethod
    def from_slack(cls, raw: dict[str, Any]) -> ListItem:
        return cls(
            id=str(raw["id"]),
            raw_fields=list(raw.get("fields") or []),
            date_created=raw.get("date_created"),
            is_archived=bool(raw.get("is_archived", False)),
        )

    def get_raw_field(self, column_id: str) -> dict[str, Any] | None:
        for field in self.raw_fields:
            if field.get("column_id") == column_id:
                return field
        return None


def text_to_rich_text(text: str) -> list[dict[str, Any]]:
    """Wrap a plain string in Slack Block Kit rich_text format."""
    return [
        {
            "type": "rich_text",
            "elements": [
                {
                    "type": "rich_text_section",
                    "elements": [{"type": "text", "text": text}],
                }
            ],
        }
    ]


def _extract_rich_text(blocks: Any) -> str:
    """Flatten Slack Block Kit rich_text blocks into plain text."""
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        for section in block.get("elements") or []:
            if not isinstance(section, dict):
                continue
            for elem in section.get("elements") or []:
                if not isinstance(elem, dict):
                    continue
                if "text" in elem:
                    parts.append(str(elem["text"]))
                elif "url" in elem:
                    parts.append(str(elem["url"]))
                elif "user_id" in elem:
                    parts.append(f"<@{elem['user_id']}>")
    return "".join(parts).strip()


def extract_field_display(
    field: dict[str, Any] | None,
    col: ColumnSchema | None = None,
    schema: ListSchema | None = None,
    user_map: dict[str, str] | None = None,
) -> str:
    """Extract a human-readable string from a Slack List item field."""
    if not field:
        return ""

    col_type = col.type if col else ""

    if col_type == "select" or "select" in field:
        selected = field.get("select")
        if selected is None:
            val = field.get("value")
            selected = val if isinstance(val, list) else ([val] if val else [])
        if isinstance(selected, list):
            formatted = [
                schema.format_select_value(col, str(v)) if (schema and col) else str(v)
                for v in selected
                if v
            ]
            return ", ".join(formatted)
        return str(selected)

    if col_type in {"user", "todo_assignee"} or "user" in field:
        users = field.get("user") or field.get("value") or []
        if isinstance(users, str):
            users = [users]
        if isinstance(users, list):
            resolved = [user_map.get(str(u), str(u)) if user_map else str(u) for u in users if u]
            return ", ".join(resolved)
        return str(users)

    if col_type in {"checkbox", "todo_completed"} or "checkbox" in field:
        checked = field.get("checkbox")
        if checked is None:
            checked = field.get("value")
        return "✓" if checked else ""

    if col_type in {"date", "todo_due_date"} or "date" in field:
        dates = field.get("date") or field.get("value") or ""
        if isinstance(dates, list):
            return ", ".join(str(d) for d in dates if d)
        return str(dates)

    if col_type == "rating" or "rating" in field:
        rating = field.get("rating")
        if rating is None:
            rating = field.get("value")
        if isinstance(rating, list):
            return ", ".join(str(r) for r in rating)
        return "" if rating is None else str(rating)

    if col_type == "number" or "number" in field:
        num = field.get("number")
        if num is None:
            num = field.get("value")
        if isinstance(num, list):
            return ", ".join(str(n) for n in num)
        return "" if num is None else str(num)

    if "text" in field and isinstance(field["text"], str) and field["text"]:
        return field["text"]

    if "rich_text" in field:
        extracted = _extract_rich_text(field["rich_text"])
        if extracted:
            return extracted

    val = field.get("value")
    if val is None:
        return ""
    if isinstance(val, list):
        return ", ".join(str(v) for v in val if v)
    return str(val)


def build_cell_payload(
    col: ColumnSchema,
    value: str,
    schema: ListSchema,
    row_id: str | None = None,
    user_lookup: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a typed cell dict for `slackLists.items.create` or `slackLists.items.update`."""
    cell: dict[str, Any] = {"column_id": col.id}
    if row_id is not None:
        cell["row_id"] = row_id

    col_type = col.type.lower()
    if col_type == "select":
        resolved = [
            schema.resolve_select_value(col, part) for part in value.split(",") if part.strip()
        ]
        cell["select"] = resolved
    elif col_type in {"checkbox", "todo_completed"}:
        cell["checkbox"] = value.strip().lower() in {"1", "true", "yes", "y", "on", "x", "✓"}
    elif col_type in {"date", "todo_due_date"}:
        cell["date"] = [value.strip()]
    elif col_type == "rating":
        cell["rating"] = [int(value.strip())]
    elif col_type == "number":
        num_val: int | float = float(value) if "." in value else int(value)
        cell["number"] = [num_val]
    elif col_type in {"user", "todo_assignee"}:
        raw_users = [u.strip().lstrip("@") for u in value.split(",") if u.strip()]
        resolved_users: list[str] = []
        for u in raw_users:
            if user_lookup and u.lower() in user_lookup:
                resolved_users.append(user_lookup[u.lower()])
            else:
                resolved_users.append(u)
        cell["user"] = resolved_users
    elif col_type == "email":
        cell["email"] = [value.strip()]
    elif col_type == "phone":
        cell["phone"] = [value.strip()]
    elif col_type == "link":
        cell["link"] = [{"original_url": value.strip()}]
    else:
        cell["rich_text"] = text_to_rich_text(value)

    return cell
