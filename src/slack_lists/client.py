"""Thin wrapper around slack_sdk.WebClient for Slack Lists operations."""

from __future__ import annotations

from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from slack_lists.models import ListComment, ListItem, ListSchema


class SlackListsError(RuntimeError):
    """Raised when a Slack Lists API call fails."""


class SlackListsClient:
    """Client for interacting with Slack Lists via the official Slack SDK."""

    def __init__(self, token: str, web_client: WebClient | None = None) -> None:
        self._client = web_client or WebClient(token=token)

    def _handle_error(self, action: str, exc: SlackApiError) -> SlackListsError:
        err = exc.response.get("error", str(exc)) if exc.response else str(exc)
        needed = exc.response.get("needed") if exc.response else None
        extra = f" (missing scope: {needed})" if needed else ""
        return SlackListsError(f"Slack API error during {action}: {err}{extra}")

    def list_items(self, list_id: str, include_archived: bool = False) -> list[ListItem]:
        """Fetch all items from a Slack List, handling cursor pagination."""
        items: list[ListItem] = []
        cursor: str | None = None

        try:
            while True:
                kwargs: dict[str, Any] = {"list_id": list_id, "limit": 100}
                if cursor:
                    kwargs["cursor"] = cursor
                if include_archived:
                    kwargs["archived"] = True

                resp = self._client.slackLists_items_list(**kwargs)
                for raw_item in resp.get("items") or []:
                    item = ListItem.from_slack(raw_item)
                    if include_archived or not item.is_archived:
                        items.append(item)

                meta = resp.get("response_metadata") or {}
                cursor = meta.get("next_cursor") or None
                if not cursor:
                    break
        except SlackApiError as exc:
            raise self._handle_error("slackLists.items.list", exc) from exc

        return items

    def get_item_with_schema(self, list_id: str, item_id: str) -> tuple[ListSchema, ListItem]:
        """Fetch a single item along with its parent list schema."""
        try:
            resp = self._client.slackLists_items_info(list_id=list_id, id=item_id)
        except SlackApiError as exc:
            raise self._handle_error("slackLists.items.info", exc) from exc

        list_obj = resp.get("list") or {}
        record = resp.get("record") or {}
        schema = ListSchema.from_slack_list(list_obj, list_id=list_id)
        item = ListItem.from_slack(record)
        return schema, item

    def get_schema(self, list_id: str, items: list[ListItem] | None = None) -> ListSchema:
        """Discover a list's column schema.

        Uses `slackLists.items.info` on the first item when available (only requires
        `lists:read`), falling back to `files.info` when the list is empty.
        """
        existing = items if items is not None else self.list_items(list_id, include_archived=True)
        if existing:
            schema, _ = self.get_item_with_schema(list_id, existing[0].id)
            return schema

        try:
            resp = self._client.files_info(file=list_id)
            file_obj = resp.get("file") or {}
            return ListSchema.from_slack_list(file_obj, list_id=list_id)
        except SlackApiError as exc:
            raise SlackListsError(
                "List is empty and schema lookup via files.info failed. "
                "Add the `files:read` scope or add one item in Slack first. "
                f"Details: {exc.response.get('error', str(exc)) if exc.response else exc}"
            ) from exc

    def get_board(
        self, list_id: str, include_archived: bool = False
    ) -> tuple[ListSchema, list[ListItem]]:
        """Fetch both the list schema and all active (or archived) items."""
        items = self.list_items(list_id, include_archived=include_archived)
        schema = self.get_schema(list_id, items=items)
        return schema, items

    def create_item(
        self,
        list_id: str,
        initial_fields: list[dict[str, Any]],
        parent_item_id: str | None = None,
    ) -> ListItem:
        """Create a new item (card) in the Slack List."""
        kwargs: dict[str, Any] = {
            "list_id": list_id,
            "initial_fields": initial_fields,
        }
        if parent_item_id:
            kwargs["parent_item_id"] = parent_item_id

        try:
            resp = self._client.slackLists_items_create(**kwargs)
        except SlackApiError as exc:
            raise self._handle_error("slackLists.items.create", exc) from exc

        raw_item = resp.get("item") or {}
        return ListItem.from_slack(raw_item)

    def update_cells(self, list_id: str, cells: list[dict[str, Any]]) -> dict[str, Any]:
        """Update one or more cells in the Slack List."""
        try:
            resp = self._client.slackLists_items_update(list_id=list_id, cells=cells)
            return dict(resp.data) if isinstance(resp.data, dict) else {}
        except SlackApiError as exc:
            raise self._handle_error("slackLists.items.update", exc) from exc

    def delete_item(self, list_id: str, item_id: str) -> dict[str, Any]:
        """Delete a single item from the Slack List."""
        try:
            resp = self._client.slackLists_items_delete(list_id=list_id, id=item_id)
            return dict(resp.data) if isinstance(resp.data, dict) else {}
        except SlackApiError as exc:
            raise self._handle_error("slackLists.items.delete", exc) from exc

    @staticmethod
    def shadow_channel_id(list_id: str) -> str:
        """Derive the Slack shadow channel ID (C...) that stores list item comment threads."""
        return f"C{list_id[1:]}" if list_id.startswith("F") else list_id

    def get_comment_counts(self, list_id: str) -> dict[str, int]:
        """Return `{item_id: reply_count}` for all items that have comments.

        Reads the list's shadow channel history once. Gracefully returns `{}` if
        history scopes are not granted or the channel is unavailable.
        """
        channel = self.shadow_channel_id(list_id)
        counts: dict[str, int] = {}
        cursor: str | None = None

        try:
            while True:
                kwargs: dict[str, Any] = {"channel": channel, "limit": 200}
                if cursor:
                    kwargs["cursor"] = cursor
                resp = self._client.conversations_history(**kwargs)
                for msg in resp.get("messages") or []:
                    meta = msg.get("slack_list") or {}
                    rec_id = meta.get("list_record_id")
                    reply_count = int(msg.get("reply_count") or 0)
                    if rec_id and reply_count > 0:
                        counts[str(rec_id)] = reply_count
                next_cursor = (resp.get("response_metadata") or {}).get("next_cursor")
                if not next_cursor:
                    break
                cursor = next_cursor
        except SlackApiError:
            return {}

        return counts

    def _fetch_thread_replies(self, channel: str, parent_ts: str) -> list[ListComment]:
        comments: list[ListComment] = []
        reply_cursor: str | None = None
        while True:
            rkwargs: dict[str, Any] = {"channel": channel, "ts": parent_ts, "limit": 200}
            if reply_cursor:
                rkwargs["cursor"] = reply_cursor
            rresp = self._client.conversations_replies(**rkwargs)
            for msg in rresp.get("messages") or []:
                if msg.get("ts") == parent_ts:
                    continue
                comments.append(
                    ListComment(
                        ts=str(msg.get("ts") or ""),
                        user=str(msg.get("user") or "unknown"),
                        text=str(msg.get("text") or ""),
                    )
                )
            next_reply_cursor = (rresp.get("response_metadata") or {}).get("next_cursor")
            if not next_reply_cursor:
                break
            reply_cursor = next_reply_cursor
        return comments

    def get_all_item_comments(self, list_id: str) -> dict[str, list[ListComment]]:
        """Fetch comments for all items in a list that have at least one reply."""
        channel = self.shadow_channel_id(list_id)
        anchors: dict[str, str] = {}
        cursor: str | None = None

        try:
            while True:
                kwargs: dict[str, Any] = {"channel": channel, "limit": 200}
                if cursor:
                    kwargs["cursor"] = cursor
                resp = self._client.conversations_history(**kwargs)
                for msg in resp.get("messages") or []:
                    meta = msg.get("slack_list") or {}
                    rec_id = meta.get("list_record_id")
                    ts = msg.get("ts")
                    reply_count = int(msg.get("reply_count") or 0)
                    if rec_id and ts and reply_count > 0:
                        anchors[str(rec_id)] = str(ts)
                next_cursor = (resp.get("response_metadata") or {}).get("next_cursor")
                if not next_cursor:
                    break
                cursor = next_cursor

            return {
                rec_id: self._fetch_thread_replies(channel, parent_ts)
                for rec_id, parent_ts in anchors.items()
            }
        except SlackApiError:
            return {}

    def get_item_comments(self, list_id: str, item_id: str) -> list[ListComment]:
        """Fetch comments from the item's thread in the list's shadow channel.

        Requires `channels:history` / `groups:history`. Gracefully returns an empty list
        if those scopes are not granted or no comment thread exists.
        """
        channel = self.shadow_channel_id(list_id)
        parent_ts: str | None = None
        reply_count = 0
        cursor: str | None = None

        try:
            while True:
                kwargs: dict[str, Any] = {"channel": channel, "limit": 200}
                if cursor:
                    kwargs["cursor"] = cursor
                resp = self._client.conversations_history(**kwargs)
                for msg in resp.get("messages") or []:
                    meta = msg.get("slack_list") or {}
                    if meta.get("list_record_id") == item_id:
                        parent_ts = msg.get("ts")
                        reply_count = int(msg.get("reply_count") or 0)
                        break
                if parent_ts:
                    break
                next_cursor = (resp.get("response_metadata") or {}).get("next_cursor")
                if not next_cursor:
                    break
                cursor = next_cursor

            if not parent_ts or reply_count == 0:
                return []

            return self._fetch_thread_replies(channel, parent_ts)
        except SlackApiError:
            return []

    def get_user_maps(self) -> tuple[dict[str, str], dict[str, str]]:
        """Return (id_to_display, name_to_id) maps if `users:read` is available.

        Gracefully returns empty dicts if the token lacks `users:read`.
        """
        id_to_display: dict[str, str] = {}
        name_to_id: dict[str, str] = {}
        cursor: str | None = None

        try:
            while True:
                kwargs: dict[str, Any] = {"limit": 200}
                if cursor:
                    kwargs["cursor"] = cursor
                resp = self._client.users_list(**kwargs)
                for member in resp.get("members") or []:
                    uid = member.get("id")
                    if not uid:
                        continue
                    profile = member.get("profile") or {}
                    display = (
                        profile.get("display_name")
                        or profile.get("real_name")
                        or member.get("name")
                        or uid
                    )
                    id_to_display[uid] = f"@{display}"
                    for alias in (
                        member.get("name"),
                        profile.get("display_name"),
                        profile.get("real_name"),
                        uid,
                    ):
                        if alias:
                            name_to_id[str(alias).lower()] = uid

                meta = resp.get("response_metadata") or {}
                cursor = meta.get("next_cursor") or None
                if not cursor:
                    break
        except SlackApiError:
            return {}, {}

        return id_to_display, name_to_id
