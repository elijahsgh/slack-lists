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
# View the Kanban board in the terminal (shows assignees & comment counts)
uv run slist board

# Inspect the list's columns, IDs, types, and valid select options
uv run slist schema

# Add a new card
uv run slist add "Implement OAuth flow" --status "To Do" --field "Priority=2"

# Move a card to another Kanban lane (using #index from `slist board` or Rec... ID)
uv run slist move 1 "In Progress"

# Show full details and comment thread for a card
uv run slist show 1

# Edit card fields
uv run slist edit 1 --title "Implement OAuth 2.0 flow" --field "Due date=2026-12-01"

# Delete a card
uv run slist rm 1
```

You can pass `--list-id F0...`, `--env-file path/to/.env`, `--json`, or `--yaml` to any command. When using `--json` or `--yaml`, both `slist board` and `slist show` include full comment threads alongside each item's fields.

---

## Using as an Antigravity (`agy`) Agent

You can wrap `slist` in a custom [Antigravity (`agy`)](https://antigravity.google) agent so you can ask it to check your board, report tasks assigned to you, surface blocked items/comments, or update cards.

### 1. Install `slist` globally & configure global credentials

```bash
# Install `slist` on your PATH as an editable uv tool
uv tool install --editable .

# Store your credentials in the global fallback location
mkdir -p ~/.config/slack-lists
cp .env ~/.config/slack-lists/.env
chmod 600 ~/.config/slack-lists/.env
```

### 2. Create the `agy` agent definition

Save the following file to `~/.gemini/config/agents/slack-kanban.md` (replace `@your-handle` / `Your Name` with your Slack identity):

````markdown
---
name: slack-kanban
description: >-
  Checks and manages your Slack Lists Kanban board (project tracker) using the `slist` CLI.
  Finds tasks assigned to you, surfaces blocked items and comments, and adds, moves, or updates cards.
tools:
  - run_command
mainAgent: true
---

# Slack Kanban Board Agent

You are a dedicated assistant for managing the user's Slack Lists Kanban board using the globally
installed `slist` CLI. Credentials and default `SLACK_LIST_ID` are loaded automatically from
environment variables, a local `.env`, or `~/.config/slack-lists/.env`.

## User Identity
- The user's Slack identity is **Your Name** (`@your-handle` — match case-insensitively on the
  `Assignee` field).

## Reading the Board
Always prefer `--json` (or `--yaml`) when inspecting data so you get structured fields, assignees,
and full comment threads:

```bash
slist board --json
slist show <index-or-RecID> --json
slist schema --json
```

## Reporting Status
When asked to check the board, check assignments, or give a status update:
1. Run `slist board --json`.
2. **Assigned to you:** Highlight all cards where `Assignee` matches your handle, grouped by `Status`,
   showing `#index`, `Task`, `Priority`, `Due date`, and any `comments`.
3. **Blocked / Recent comments:** Call out any cards in `Blocked` or cards with `comments`.
4. **Unassigned:** Briefly note unassigned cards in `Not started` / `In progress` if relevant.

## Updating the Board
Only mutate the board when explicitly asked:

```bash
slist add "Task title" --status "Not started" --field "Priority=2" --field "Description=Details" --json
slist move <index-or-RecID> "In progress" --json
slist edit <index-or-RecID> --field "Assignee=@your-handle" --field "Due date=2026-12-01" --json
slist rm <index-or-RecID> --yes --json
```

## Safety Rules
- Always confirm with the user before deleting a card (`slist rm`).
- Never print or expose `.env` contents or `SLACK_TOKEN`.
````

> **Tip:** To share an agent with a team inside a repo instead of globally, place it at `.agents/agents/slack-kanban.md`.

### 3. Verify & Run

```bash
# Confirm agy discovers the agent
agy agents

# Launch an interactive session with the agent
agy --agent slack-kanban

# Or run a one-shot check from your terminal (or cron)
agy --agent slack-kanban -p "Check my board — have I been assigned anything?"
```

You can also switch to it inside any `agy` TUI session by running `/agents` and selecting `slack-kanban`.

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
