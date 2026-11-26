# slack-lists

A small CLI tool for interacting with [Slack Lists](https://slack.com/features/lists) to manage a Kanban board / project tracker directly from the terminal.

Built with Python using [`uv`](https://docs.astral.sh/uv/) and [`ruff`](https://docs.astral.sh/ruff/).

---

## Prerequisites

* A **paid Slack workspace** (Pro, Business+, or Enterprise Grid) — the Slack Lists API (`slackLists.*`) is only available on paid plans.
* [`uv`](https://docs.astral.sh/uv/) installed locally.
* [`ruff`](https://docs.astral.sh/ruff/) for linting and formatting.

---

## Slack App Setup

You do **not** need an App-Level Token (`xapp-`). You only need a **User Token (`xoxp-`)** or a **Bot Token (`xoxb-`)**.

### Choosing a Token Type

| Token Type | Prefix | Best For | Access Behavior |
| :--- | :--- | :--- | :--- |
| **User Token** *(Recommended)* | `xoxp-` | Personal CLI usage | Acts as you; automatically accesses any Slack List you can already view or edit (private, shared, or channel lists). |
| **Bot Token** | `xoxb-` | Shared team automation | Acts as the app's bot user; you must **explicitly share each target Slack List** with the bot (in Slack or via `slackLists.access.set`). |

### Step-by-Step: Create the Slack App & Generate a Token

1. Go to **[api.slack.com/apps](https://api.slack.com/apps)** and click **Create New App**.
2. In the **Create new app** dialog, under **From scratch**, choose either **Paste a manifest** *(fastest)* or **Pick features** *(manual)*:

#### Option A: Paste a manifest *(Recommended / Fastest)*

1. Under **From scratch**, select **Paste a manifest** and click **Continue**.
2. Select your workspace and click **Next**.
3. Paste the YAML manifest below (configured for a **User Token**; change `user:` to `bot:` under `scopes:` if you prefer a Bot Token):

```yaml
display_information:
  name: Slack Lists CLI
oauth_config:
  scopes:
    user:
      - lists:read
      - lists:write
      - users:read
      - files:read
      - channels:history
      - groups:history
settings:
  org_deploy_enabled: false
  socket_mode_enabled: false
  token_rotation_enabled: false
```

4. Click **Next**, review the summary, and click **Create**.
5. In the left sidebar, open **OAuth & Permissions**, click **Install to <Your Workspace>**, and click **Allow**.
6. Copy the **User OAuth Token** (`xoxp-...`) — or **Bot User OAuth Token** (`xoxb-...`) if you used `bot:` scopes.

#### Option B: Pick features *(Manual)*

1. Under **From scratch**, select **Pick features** (*Set up with scopes and events*) and click **Continue**.
2. Enter an app name (e.g., `Slack Lists CLI`), select your workspace, and create the app.
3. In the left sidebar, open **OAuth & Permissions**.
4. Scroll to **Scopes** and add the required scopes under **User Token Scopes** *(recommended)* — or under **Bot Token Scopes** if you prefer a bot token:
   * `lists:read` *(Required)* — Read list items, column schemas, and exports.
   * `lists:write` *(Required)* — Create, update (move cards), and delete list items.
   * `users:read` *(Recommended)* — Resolve Assignee user IDs (`U...`) to names/`@handles`.
   * `files:read` *(Optional)* — Inspect underlying list file metadata via `files.info` (needed if inspecting an empty list).
   * `channels:history` *(Optional)* — Read item comment threads on lists shared in public channels.
   * `groups:history` *(Optional)* — Read item comment threads on lists shared in private channels.
5. Scroll back up to **OAuth Tokens** and click **Install to <Your Workspace>** (or **Reinstall to <Your Workspace>** if you added scopes later), then click **Allow**.
6. Copy the generated token:
   * **User OAuth Token** (`xoxp-...`) if you configured User Token Scopes.
   * **Bot User OAuth Token** (`xoxb-...`) if you configured Bot Token Scopes.

### Finding Your List ID (`F0...`)

Slack Lists are backed by Slack's file model, so every list has a File ID starting with `F0...`:

1. Open your project tracker / Kanban list in Slack.
2. Click **Copy link** on the list.
3. Extract the `F0...` segment from the URL — this is your `list_id`.

---

## Configuration

Settings are managed via `pydantic-settings` with the following precedence (highest to lowest):
1. Environment variables (`SLACK_TOKEN`, `SLACK_LIST_ID`, `SLACK_STATUS_COLUMN`)
2. Local `.env` in the current working directory
3. Global `~/.config/slack-lists/.env`

Copy `.env.example` to `.env` (or `~/.config/slack-lists/.env` for global use) and fill in your values:

```bash
cp .env.example .env
```

```dotenv
SLACK_TOKEN=xoxp-your-token-here
SLACK_LIST_ID=F0123456789
# Optional: defaults to "Status"
SLACK_STATUS_COLUMN=Status
```

Or export them directly in your shell:

```bash
export SLACK_TOKEN="xoxp-your-token-here"
export SLACK_LIST_ID="F0123456789"
```

> **Security note:** `.env` is listed in `.gitignore`. Never commit your Slack token to version control.

---

## Usage

```bash
# View the Kanban board in the terminal
uv run slist board

# Inspect the list's columns, IDs, types, and valid select options
uv run slist schema

# Add a new card
uv run slist add "Implement OAuth flow" --status "To Do" --field "Priority=High"

# Move a card to another Kanban lane (using #index from `slist board` or Rec... ID)
uv run slist move 1 "In Progress"

# Show full details for a card
uv run slist show 1

# Edit card fields
uv run slist edit 1 --title "Implement OAuth 2.0 flow" --field "Due Date=2026-12-01"

# Delete a card
uv run slist rm 1
```

You can also pass `--list-id F0...`, `--env-file path/to/.env`, `--json`, or `--yaml` to any command.

---

## Development

This project uses **`uv`** for all Python environment and dependency management (do not use `pip`) and **`ruff`** for linting and formatting.

```bash
# Install / sync dependencies
uv sync

# Run the CLI in development
uv run slist --help

# Lint and format
uv run ruff check .
uv run ruff format .

# Run tests
uv run pytest
```
