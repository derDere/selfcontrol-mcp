# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**selfcontrol-mcp** is an MCP server that gives an AI the ability to prompt itself through tmux. It schedules prompts for immediate or future delivery, with a background scheduler that ensures continuous activity via fallback prompts. A Telegram bot provides bidirectional communication between the user and the AI. See `docs/CONCEPT.md` and `docs/TELEGRAM_BOT_CONCEPT.md` for the full design.

License: GPL v3

## Architecture

### Shared Library (`lib/`)

All shared logic lives in `lib/` as reusable classes:

| Class | Module | Purpose |
|-------|--------|---------|
| `Config` | `lib/config.py` | Typed access to `config.yaml` with sensible defaults |
| `TmuxClient` | `lib/tmux.py` | All tmux subprocess interactions (pane detection, send-keys) |
| `Session` | `lib/session.py` | One session directory — lock, queue, input, permissions, history |
| `SessionManager` | `lib/session_manager.py` | Discovers sessions, maintains `session_map.json`, encode/decode names |
| `TelegramClient` | `lib/telegram.py` | One-shot Telegram message sending (used by hooks and server) |
| `RateLimiter` | `lib/rate_limiter.py` | Reads/writes `rate_limit.json` |

Import via `from lib import Config, Session, SessionManager, ...`

### Scripts (thin orchestration)

1. **MCP Server** (`server.py`) — FastMCP server exposing:
   - **Tools:** `prompt_now(message)`, `prompt_later(message, target_time?, delay?)`, `message_user(message, file_path?)`
   - **Prompts:** `start` — returns contents of `start.md` (bootstraps a session)
   - Writes prompt files to `~/.ai-sessions/{session}:{window}.{pane}/queue/`
   - `message_user` sends Telegram messages directly using bot token from config
   - Tmux pane detection is deferred to first tool call (not import time), so the server starts even outside tmux

2. **Background Scheduler** (`scheduler.py`) — `Scheduler` class with main loop:
   - Checks queue/input every `check_interval_seconds` (default 10s)
   - Default prompts only sent if last prompt (any type) was `default_prompt_interval_minutes` ago (default 5min)
   - Priority: queue (oldest due) → input folder (oldest) → config default prompt
   - Sends via `TmuxClient.send_keys()` (literal mode + Enter)
   - Sets `generating.lock` after sending; skips locked sessions (< 30 min old)
   - Checks `RateLimiter` before processing — pauses all sessions until reset
   - Logs each sent prompt to `history.log`; deletes consumed files

3. **Telegram Bot** (`telebot_runner.py`) — `TelebotRunner` class:
   - Restricted to a single authorized user via `telegram_user_id`
   - Text messages are written to the active session's `input/` folder
   - `/sessions` lists all sessions with clickable switch commands
   - `/s_ENCODED` switches active session (e.g. `/s_work_0_1` → `work:0.1`)
   - `/s_ENCODED_allow`, `_always`, `_deny` — respond to permission requests
   - Auto-maintains `session_map.json` for command ↔ session name translation

4. **Hook Script** (`reset_generating.py`) — Called by Claude Code `Stop` hook after generation completes. Detects current tmux pane and deletes the corresponding `generating.lock`. Silently does nothing if not in tmux.

5. **Notification Script** (`notify_user.py`) — Called by Claude Code `Notification` hook when the AI needs user attention (e.g. waiting for permission approval). Sends a Telegram message with session info.

6. **Permission Handler** (`permission_handler.py`) — Called by Claude Code `PermissionRequest` hook:
   - Sends permission request to Telegram with tool name/input and clickable allow/always/deny commands
   - Polls for response file written by the Telegram bot
   - Configurable timeout (`permission_timeout_minutes`, default 10min) — denies on timeout
   - Returns JSON `{"decision": "allow"|"always"|"deny"}` to Claude Code

7. **Rate Limit Handler** (`rate_limit_handler.py`) — Called by Claude Code `StopFailure` hook (matcher: `rate_limit`):
   - Uses `RateLimiter` to write the pause marker
   - Waits 1 second then sends Enter via tmux to dismiss the rate limit dialog
   - Sends Telegram notification with `/unlimit` command to resume
   - Scheduler skips all sessions while rate-limited
   - User removes via `/unlimit` in Telegram

8. **Setup Wizard** (`setup.py`) — Interactive questionary-based setup that:
   - Creates `start.md` from `example.start.md`
   - Configures `config.yaml` with sensible defaults
   - Configures Telegram bot token and user ID
   - Installs the `Stop`, `Notification`, `PermissionRequest`, and `StopFailure` hooks in `~/.claude/settings.json`

## Session Folder Structure (`~/.ai-sessions/`)

```
~/.ai-sessions/{session}:{window}.{pane}/
├── queue/            # Timestamped prompt files (filename: {YYYYMMDDTHHMMSS}_{rand}.txt)
├── input/            # Manual fallback prompts (sorted by mtime, oldest first)
├── generating.lock       # Present while AI is working (contains timestamp)
├── permissions/          # Per-request permission response files (filename: request ID)
└── history.log           # Audit log of all sent prompts

~/.ai-sessions/session_map.json   # Auto-generated command ↔ session mapping
~/.ai-sessions/rate_limit.json    # Present during rate limit (contains reset time)
```

## Key Files

| File | Purpose |
|------|---------|
| `lib/config.py` | `Config` — typed config.yaml access |
| `lib/tmux.py` | `TmuxClient` — tmux pane detection and send-keys |
| `lib/session.py` | `Session` — single session directory operations |
| `lib/session_manager.py` | `SessionManager` — multi-session discovery and name mapping |
| `lib/telegram.py` | `TelegramClient` — one-shot Telegram message sending |
| `lib/rate_limiter.py` | `RateLimiter` — rate limit file management |
| `server.py` | FastMCP MCP server (`prompt_now`, `prompt_later`, `message_user`, `start`) |
| `scheduler.py` | `Scheduler` class — background prompt scheduler |
| `telebot_runner.py` | `TelebotRunner` class — Telegram bot for user communication |
| `reset_generating.py` | Hook script to clear generating lock |
| `notify_user.py` | Hook script to notify user via Telegram when AI needs attention |
| `permission_handler.py` | Hook script for remote permission approval via Telegram |
| `rate_limit_handler.py` | Hook script for rate limit detection, pausing, and notification |
| `setup.py` | Interactive setup wizard |
| `config.yaml` | Default prompt, base_dir, intervals, Telegram credentials |
| `start.md` | User-edited startup prompt (gitignored) |
| `example.start.md` | Template for `start.md` |

## Development

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python setup.py

# Run MCP server (typically configured in Claude Code MCP settings)
python server.py

# Run scheduler (in a separate tmux pane)
python scheduler.py

# Run Telegram bot (in a separate tmux pane)
python telebot_runner.py

# Clear generating lock (called by hooks, or manually)
python reset_generating.py
```

## Prompt File Naming

- Queue: `20260320T153000_a1b2c3.txt` — target time + random suffix
- `prompt_now` uses `19000101T000000` as timestamp to sort first
- Content: raw prompt text
