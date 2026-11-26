"""Typer CLI for managing a Slack Lists Kanban board."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from slack_lists.client import SlackListsClient, SlackListsError
from slack_lists.config import Settings, load_settings
from slack_lists.models import (
    ColumnSchema,
    ListItem,
    ListSchema,
    build_cell_payload,
    extract_field_display,
)

app = typer.Typer(
    name="slist",
    help="Manage a Slack Lists Kanban board / project tracker from the terminal.",
    no_args_is_help=True,
)
console = Console()
err_console = Console(stderr=True)

ListIdOpt = Annotated[
    str | None,
    typer.Option("--list-id", "-l", help="Slack List ID (F0...). Overrides SLACK_LIST_ID."),
]
EnvFileOpt = Annotated[
    Path | None,
    typer.Option("--env-file", help="Path to a .env file (defaults to .env in current directory)."),
]
StatusColOpt = Annotated[
    str | None,
    typer.Option("--status-col", help="Select column used for Kanban lanes (default: Status)."),
]
JsonOpt = Annotated[bool, typer.Option("--json", help="Output result as JSON.")]
YamlOpt = Annotated[bool, typer.Option("--yaml", help="Output result as YAML.")]


def _validate_output_format(as_json: bool, as_yaml: bool) -> None:
    if as_json and as_yaml:
        err_console.print("[bold red]Cannot pass both --json and --yaml.[/bold red]")
        raise typer.Exit(code=1)


def _emit_structured(data: Any, as_json: bool, as_yaml: bool) -> bool:
    """Emit JSON or YAML if requested and return True; otherwise return False."""
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return True
    if as_yaml:
        typer.echo(yaml.safe_dump(data, sort_keys=False, allow_unicode=True).rstrip())
        return True
    return False


def _init_context(
    list_id: str | None,
    env_file: Path | None,
) -> tuple[Settings, SlackListsClient, str]:
    try:
        settings = load_settings(env_file=env_file)
        token = settings.require_token()
        resolved_list_id = settings.require_list_id(override=list_id)
    except ValueError as exc:
        err_console.print(f"[bold red]Configuration error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    return settings, SlackListsClient(token=token), resolved_list_id


def _resolve_item(items: list[ListItem], item_ref: str) -> ListItem:
    """Resolve either a 1-based board index (e.g. '2') or a Slack row ID ('Rec...')."""
    ref = item_ref.strip()
    if ref.isdigit():
        idx = int(ref)
        if 1 <= idx <= len(items):
            return items[idx - 1]
        raise ValueError(f"Item #{idx} out of range (board has {len(items)} items).")

    for item in items:
        if item.id.lower() == ref.lower():
            return item
    raise ValueError(
        f"Item {item_ref!r} not found. Use a #index from `slist board` or a Rec... ID."
    )


def _parse_key_value_fields(fields: list[str] | None) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    for raw in fields or []:
        if "=" not in raw:
            raise ValueError(f"Invalid --field {raw!r}. Expected format: 'Column Name=Value'.")
        name, value = raw.split("=", 1)
        parsed.append((name.strip(), value.strip()))
    return parsed


def _item_title(item: ListItem, schema: ListSchema) -> str:
    primary = schema.primary_column
    if primary is None:
        return item.id
    return extract_field_display(item.get_raw_field(primary.id), primary, schema) or "(untitled)"


def _format_comment_count(count: int) -> str:
    noun = "comment" if count == 1 else "comments"
    return f"({count}) {noun}"


def _format_card_text(
    index: int,
    item: ListItem,
    schema: ListSchema,
    status_col: ColumnSchema | None,
    user_map: dict[str, str],
    comment_count: int = 0,
) -> Text:
    primary = schema.primary_column
    title = _item_title(item, schema)
    card = Text()
    card.append(f"#{index} ", style="bold cyan")
    card.append(title, style="bold")
    if comment_count > 0:
        card.append(f"  {_format_comment_count(comment_count)}", style="yellow")
    card.append(f"\n   {item.id}", style="dim")

    assignee_cols = [c for c in schema.columns if c.type in {"user", "todo_assignee"}]
    assignee_col_ids = {c.id for c in assignee_cols}
    for col in assignee_cols:
        val = extract_field_display(item.get_raw_field(col.id), col, schema, user_map)
        card.append(f"\n   {col.name}: ", style="dim")
        if val:
            card.append(val, style="bold green")
        else:
            card.append("Unassigned", style="dim italic")

    meta_parts: list[str] = []
    for col in schema.columns:
        if (
            (primary and col.id == primary.id)
            or (status_col and col.id == status_col.id)
            or col.id in assignee_col_ids
        ):
            continue
        val = extract_field_display(item.get_raw_field(col.id), col, schema, user_map)
        if val:
            meta_parts.append(f"{col.name}: {val}")
    if meta_parts:
        card.append("\n   " + " · ".join(meta_parts), style="dim white")
    return card


@app.command()
def board(
    list_id: ListIdOpt = None,
    status_col: StatusColOpt = None,
    archived: Annotated[bool, typer.Option("--archived", help="Include archived items.")] = False,
    as_json: JsonOpt = False,
    as_yaml: YamlOpt = False,
    env_file: EnvFileOpt = None,
) -> None:
    """Display the Slack List as a Kanban board grouped by status."""
    _validate_output_format(as_json, as_yaml)
    settings, client, resolved_list_id = _init_context(list_id, env_file)
    try:
        schema, items = client.get_board(resolved_list_id, include_archived=archived)
    except SlackListsError as exc:
        err_console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=1) from exc

    user_map, _ = client.get_user_maps()
    preferred_status = status_col or settings.slack_status_column
    lane_col = schema.find_status_column(preferred_status)

    if as_json or as_yaml:
        all_comments = client.get_all_item_comments(resolved_list_id)
        payload: list[dict[str, Any]] = []
        for idx, item in enumerate(items, start=1):
            item_comments = all_comments.get(item.id, [])
            row: dict[str, Any] = {
                "index": idx,
                "id": item.id,
            }
            for col in schema.columns:
                row[col.name] = extract_field_display(
                    item.get_raw_field(col.id), col, schema, user_map
                )
            row["comment_count"] = len(item_comments)
            row["comments"] = [
                {
                    "ts": c.ts,
                    "user": c.user,
                    "author": user_map.get(c.user, c.user),
                    "text": c.text,
                }
                for c in item_comments
            ]
            payload.append(row)
        _emit_structured(
            {"list_id": schema.list_id, "title": schema.title, "items": payload},
            as_json=as_json,
            as_yaml=as_yaml,
        )
        return

    comment_counts = client.get_comment_counts(resolved_list_id)

    if not items:
        console.print(f"[dim]Board '{schema.title}' ({schema.list_id}) has no items.[/dim]")
        return

    if lane_col is None:
        # Fallback: simple table if the list has no select column
        table = Table(title=f"{schema.title} ({schema.list_id})")
        table.add_column("#", style="cyan", no_wrap=True)
        table.add_column("ID", style="dim", no_wrap=True)
        for col in schema.columns:
            table.add_column(col.name)
        for idx, item in enumerate(items, start=1):
            row_vals = [
                extract_field_display(item.get_raw_field(col.id), col, schema, user_map)
                for col in schema.columns
            ]
            table.add_row(str(idx), item.id, *row_vals)
        console.print(table)
        return

    # Group cards into Kanban lanes preserving schema choice order
    lanes: dict[str, list[tuple[int, ListItem]]] = {c.label: [] for c in lane_col.choices}
    uncategorized = "Unassigned"

    for idx, item in enumerate(items, start=1):
        status_val = extract_field_display(
            item.get_raw_field(lane_col.id), lane_col, schema, user_map
        )
        lane_name = status_val or uncategorized
        lanes.setdefault(lane_name, []).append((idx, item))

    table = Table(
        title=f"{schema.title} ({schema.list_id})",
        show_lines=True,
        expand=True,
    )
    lane_names = list(lanes.keys())
    for name in lane_names:
        count = len(lanes[name])
        table.add_column(f"{name} ({count})", vertical="top")

    max_rows = max((len(v) for v in lanes.values()), default=0)
    for row_idx in range(max_rows):
        row_cells: list[Text | str] = []
        for name in lane_names:
            lane_items = lanes[name]
            if row_idx < len(lane_items):
                idx, item = lane_items[row_idx]
                row_cells.append(
                    _format_card_text(
                        idx,
                        item,
                        schema,
                        lane_col,
                        user_map,
                        comment_count=comment_counts.get(item.id, 0),
                    )
                )
            else:
                row_cells.append("")
        table.add_row(*row_cells)

    console.print(table)


@app.command()
def schema(
    list_id: ListIdOpt = None,
    as_json: JsonOpt = False,
    as_yaml: YamlOpt = False,
    env_file: EnvFileOpt = None,
) -> None:
    """Inspect the columns, types, and select options of the Slack List."""
    _validate_output_format(as_json, as_yaml)
    _, client, resolved_list_id = _init_context(list_id, env_file)
    try:
        list_schema = client.get_schema(resolved_list_id)
    except SlackListsError as exc:
        err_console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=1) from exc

    if _emit_structured(list_schema.model_dump(), as_json=as_json, as_yaml=as_yaml):
        return

    table = Table(title=f"Schema: {list_schema.title} ({list_schema.list_id})")
    table.add_column("Column", style="bold")
    table.add_column("ID", style="dim")
    table.add_column("Type", style="cyan")
    table.add_column("Primary")
    table.add_column("Options")

    for col in list_schema.columns:
        opts = ", ".join(c.label for c in col.choices) if col.choices else ""
        table.add_row(
            col.name,
            col.id,
            col.type,
            "✓" if col.is_primary_column else "",
            opts,
        )
    console.print(table)


@app.command()
def add(
    title: Annotated[str, typer.Argument(help="Title / primary column value for the new card.")],
    status: Annotated[
        str | None, typer.Option("--status", "-s", help="Initial Kanban status.")
    ] = None,
    field: Annotated[
        list[str] | None,
        typer.Option("--field", "-f", help="Extra column value as 'Column=Value'. Repeatable."),
    ] = None,
    list_id: ListIdOpt = None,
    status_col: StatusColOpt = None,
    as_json: JsonOpt = False,
    as_yaml: YamlOpt = False,
    env_file: EnvFileOpt = None,
) -> None:
    """Add a new card to the Slack List."""
    _validate_output_format(as_json, as_yaml)
    settings, client, resolved_list_id = _init_context(list_id, env_file)
    try:
        list_schema = client.get_schema(resolved_list_id)
        _, name_to_id = client.get_user_maps()

        primary = list_schema.primary_column
        if primary is None:
            raise ValueError("Could not determine the primary column for this Slack List.")

        initial_fields: list[dict[str, Any]] = [
            build_cell_payload(primary, title, list_schema, user_lookup=name_to_id)
        ]

        if status:
            lane_col = list_schema.find_status_column(status_col or settings.slack_status_column)
            if lane_col is None:
                raise ValueError("No select/status column found in this list.")
            initial_fields.append(
                build_cell_payload(lane_col, status, list_schema, user_lookup=name_to_id)
            )

        for col_name, col_val in _parse_key_value_fields(field):
            col = list_schema.find_column(col_name)
            if col is None:
                raise ValueError(f"Unknown column {col_name!r}. Run `slist schema` to see columns.")
            initial_fields.append(
                build_cell_payload(col, col_val, list_schema, user_lookup=name_to_id)
            )

        created = client.create_item(resolved_list_id, initial_fields=initial_fields)
    except (ValueError, SlackListsError) as exc:
        err_console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=1) from exc

    if _emit_structured(
        {"id": created.id, "title": title, "list_id": resolved_list_id},
        as_json=as_json,
        as_yaml=as_yaml,
    ):
        return
    console.print(f"[green]Created card[/green] [bold]{title}[/bold] ([dim]{created.id}[/dim])")


@app.command()
def move(
    item_ref: Annotated[str, typer.Argument(help="Card #index from `slist board` or Rec... ID.")],
    status: Annotated[str, typer.Argument(help="Target Kanban column / status label.")],
    list_id: ListIdOpt = None,
    status_col: StatusColOpt = None,
    as_json: JsonOpt = False,
    as_yaml: YamlOpt = False,
    env_file: EnvFileOpt = None,
) -> None:
    """Move a card to a different Kanban column."""
    _validate_output_format(as_json, as_yaml)
    settings, client, resolved_list_id = _init_context(list_id, env_file)
    try:
        list_schema, items = client.get_board(resolved_list_id)
        item = _resolve_item(items, item_ref)
        lane_col = list_schema.find_status_column(status_col or settings.slack_status_column)
        if lane_col is None:
            raise ValueError("No select/status column found in this list.")

        cell = build_cell_payload(lane_col, status, list_schema, row_id=item.id)
        client.update_cells(resolved_list_id, cells=[cell])
        resolved_label = list_schema.format_select_value(lane_col, cell["select"][0])
    except (ValueError, SlackListsError) as exc:
        err_console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=1) from exc

    title = _item_title(item, list_schema)
    if _emit_structured(
        {"id": item.id, "title": title, "status": resolved_label, "list_id": resolved_list_id},
        as_json=as_json,
        as_yaml=as_yaml,
    ):
        return
    console.print(
        f"[green]Moved[/green] [bold]{title}[/bold] ([dim]{item.id}[/dim]) → "
        f"[bold cyan]{resolved_label}[/bold cyan]"
    )


@app.command()
def edit(
    item_ref: Annotated[str, typer.Argument(help="Card #index from `slist board` or Rec... ID.")],
    title: Annotated[str | None, typer.Option("--title", "-t", help="New card title.")] = None,
    status: Annotated[str | None, typer.Option("--status", "-s", help="New Kanban status.")] = None,
    field: Annotated[
        list[str] | None,
        typer.Option("--field", "-f", help="Update column as 'Column=Value'. Repeatable."),
    ] = None,
    list_id: ListIdOpt = None,
    status_col: StatusColOpt = None,
    as_json: JsonOpt = False,
    as_yaml: YamlOpt = False,
    env_file: EnvFileOpt = None,
) -> None:
    """Edit one or more fields on an existing card."""
    _validate_output_format(as_json, as_yaml)
    settings, client, resolved_list_id = _init_context(list_id, env_file)
    try:
        list_schema, items = client.get_board(resolved_list_id)
        item = _resolve_item(items, item_ref)
        _, name_to_id = client.get_user_maps()

        cells: list[dict[str, Any]] = []
        if title is not None:
            primary = list_schema.primary_column
            if primary is None:
                raise ValueError("Could not determine the primary column for this Slack List.")
            cells.append(
                build_cell_payload(
                    primary, title, list_schema, row_id=item.id, user_lookup=name_to_id
                )
            )

        if status is not None:
            lane_col = list_schema.find_status_column(status_col or settings.slack_status_column)
            if lane_col is None:
                raise ValueError("No select/status column found in this list.")
            cells.append(
                build_cell_payload(
                    lane_col, status, list_schema, row_id=item.id, user_lookup=name_to_id
                )
            )

        for col_name, col_val in _parse_key_value_fields(field):
            col = list_schema.find_column(col_name)
            if col is None:
                raise ValueError(f"Unknown column {col_name!r}. Run `slist schema` to see columns.")
            cells.append(
                build_cell_payload(
                    col, col_val, list_schema, row_id=item.id, user_lookup=name_to_id
                )
            )

        if not cells:
            raise ValueError("Nothing to update. Provide --title, --status, or --field.")

        client.update_cells(resolved_list_id, cells=cells)
    except (ValueError, SlackListsError) as exc:
        err_console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=1) from exc

    if _emit_structured(
        {"id": item.id, "list_id": resolved_list_id, "updated_fields": len(cells)},
        as_json=as_json,
        as_yaml=as_yaml,
    ):
        return
    console.print(f"[green]Updated card[/green] [dim]{item.id}[/dim] ({len(cells)} field(s))")


@app.command()
def show(
    item_ref: Annotated[str, typer.Argument(help="Card #index from `slist board` or Rec... ID.")],
    list_id: ListIdOpt = None,
    as_json: JsonOpt = False,
    as_yaml: YamlOpt = False,
    env_file: EnvFileOpt = None,
) -> None:
    """Show all fields and comments for a single card."""
    _validate_output_format(as_json, as_yaml)
    _, client, resolved_list_id = _init_context(list_id, env_file)
    try:
        list_schema, items = client.get_board(resolved_list_id)
        item = _resolve_item(items, item_ref)
    except (ValueError, SlackListsError) as exc:
        err_console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=1) from exc

    user_map, _ = client.get_user_maps()
    comments = client.get_item_comments(resolved_list_id, item.id)
    title = _item_title(item, list_schema)

    if as_json or as_yaml:
        fields_data = {
            col.name: extract_field_display(item.get_raw_field(col.id), col, list_schema, user_map)
            for col in list_schema.columns
        }
        comments_data = [
            {
                "ts": c.ts,
                "user": c.user,
                "author": user_map.get(c.user, c.user),
                "text": c.text,
            }
            for c in comments
        ]
        _emit_structured(
            {
                "id": item.id,
                "list_id": resolved_list_id,
                "title": title,
                "fields": fields_data,
                "comment_count": len(comments),
                "comments": comments_data,
            },
            as_json=as_json,
            as_yaml=as_yaml,
        )
        return

    table = Table(show_header=False, box=None)
    table.add_column("Field", style="bold cyan")
    table.add_column("Value")
    table.add_row("ID", item.id)
    for col in list_schema.columns:
        val = extract_field_display(item.get_raw_field(col.id), col, list_schema, user_map)
        table.add_row(col.name, val or "[dim]—[/dim]")
    table.add_row(
        "Comments",
        f"[yellow]{_format_comment_count(len(comments))}[/yellow]"
        if comments
        else "[dim](0) comments[/dim]",
    )

    console.print(Panel(table, title=title, expand=False))

    if comments:
        comment_table = Table(show_header=False, box=None, padding=(0, 1))
        comment_table.add_column("Author", style="bold cyan", no_wrap=True)
        comment_table.add_column("Comment")
        for c in comments:
            author = user_map.get(c.user, c.user)
            try:
                ts_str = datetime.fromtimestamp(float(c.ts)).strftime("%Y-%m-%d %H:%M")
            except (ValueError, OSError):
                ts_str = c.ts
            comment_table.add_row(f"{author}\n[dim]{ts_str}[/dim]", c.text)
        console.print(
            Panel(comment_table, title=_format_comment_count(len(comments)), expand=False)
        )


@app.command()
def rm(
    item_ref: Annotated[str, typer.Argument(help="Card #index from `slist board` or Rec... ID.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")] = False,
    list_id: ListIdOpt = None,
    as_json: JsonOpt = False,
    as_yaml: YamlOpt = False,
    env_file: EnvFileOpt = None,
) -> None:
    """Delete a card from the Slack List."""
    _validate_output_format(as_json, as_yaml)
    _, client, resolved_list_id = _init_context(list_id, env_file)
    try:
        list_schema, items = client.get_board(resolved_list_id)
        item = _resolve_item(items, item_ref)
    except (ValueError, SlackListsError) as exc:
        err_console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=1) from exc

    title = _item_title(item, list_schema)
    if not yes and not typer.confirm(f"Delete card '{title}' ({item.id})?"):
        console.print("[dim]Cancelled.[/dim]")
        raise typer.Exit(code=0)

    try:
        client.delete_item(resolved_list_id, item.id)
    except SlackListsError as exc:
        err_console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=1) from exc

    if _emit_structured(
        {"id": item.id, "title": title, "list_id": resolved_list_id, "deleted": True},
        as_json=as_json,
        as_yaml=as_yaml,
    ):
        return
    console.print(f"[green]Deleted card[/green] [bold]{title}[/bold] ([dim]{item.id}[/dim])")
