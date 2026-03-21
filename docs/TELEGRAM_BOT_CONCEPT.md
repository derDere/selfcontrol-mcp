# Telegram Bot Concept

## Overview

A Telegram bot that serves as the bidirectional communication layer between the user and the autonomous AI sessions. The user sends messages to the bot, which writes them as prompt files into the active session's `input/` folder. The AI sends messages back via the `message_user` MCP tool, which sends Telegram messages directly.

## Components

### 1. Telegram Bot (`telebot_runner.py`)

A standalone script using **pyTelegramBotAPI** (telebot). Runs as a long-lived process alongside the scheduler.

#### Security

- The bot is restricted to a **single user** via `telegram_user_id` in `config.yaml`
- Every incoming message is checked against this ID — all others are silently ignored
- The `chat_id` filter on every handler ensures no unauthorized access

#### Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message, shows current active session |
| `/sessions` | Lists all discovered sessions with clickable encoded commands |
| `/s_ENCODED` | Switch active session (e.g. `/s_work_0_1` → `work:0.1`) |
| `/help` | Shows available commands |

#### Message Handling

- All regular text messages are written as files to the **active session's** `input/` folder
- File naming: `{YYYYMMDDTHHMMSS}_{6char_random}.txt` (same format as queue files, sorted by time)
- Photos, documents, and other media sent by the user are saved to the input folder as well

#### Session Switching

- The bot maintains a current active session per user
- On startup, defaults to the first session found in `~/.ai-sessions/`
- User switches via encoded commands like `/s_work_0_1`

### 2. Session Map (`session_map.json`)

Auto-generated mapping between encoded Telegram command names and real tmux session identifiers.

```json
{
  "s_0_0_1": "0:0.1",
  "s_work_0_1": "work:0.1",
  "s_myproject_2_0": "myproject:2.0"
}
```

- **Location:** `~/.ai-sessions/session_map.json`
- **Auto-updated:** The bot scans `~/.ai-sessions/` for session folders and rebuilds the map on startup and periodically
- **Encoding:** Replace `:` with `_` and `.` with `_` in the session name, prefix with `s_`
- **Reverse lookup:** The bot can decode commands back to real session names via this map

### 3. `message_user` MCP Tool (in `server.py`)

A new MCP tool added to the existing server.

```
message_user(message: str, file_path: str | None = None)
```

- Reads `telegram_bot_token` and `telegram_user_id` from `config.yaml`
- Creates a telebot instance and sends the message directly via Telegram API
- Prefixes every message with the encoded session command and timestamp:
  ```
  /s_work_0_1  2026-03-21 14:30

  Your build finished successfully. All 42 tests pass.
  ```
- This prefix allows the user to tap the session command to switch context and reply directly
- If `file_path` is provided, sends the file as a document or image (detected by extension)
- Returns a friendly error if bot token or user ID is not configured

## Config Changes (`config.yaml`)

```yaml
# Existing config...
default_prompt: ...
base_dir: ~/.ai-sessions
check_interval_seconds: 60
generating_timeout_minutes: 30

# Telegram bot config
telegram_bot_token: "123456:ABC-DEF..."
telegram_user_id: 123456789
```

## Setup Wizard Changes (`setup.py`)

The setup wizard gains a new Telegram section that:

1. Asks if the user wants to configure the Telegram bot
2. Explains how to create a bot via [@BotFather](https://t.me/BotFather) on Telegram
3. Prompts for the bot token
4. Explains how to find your user ID (send `/start` to [@userinfobot](https://t.me/userinfobot) or [@RawDataBot](https://t.me/RawDataBot))
5. Prompts for the user ID
6. Saves both to `config.yaml`

## Message Flow

### User → AI

```
User sends "Fix the login bug" in Telegram
  → Bot checks user ID (authorized?)
  → Bot writes ~/.ai-sessions/{active_session}/input/20260321T143000_a1b2c3.txt
  → Scheduler picks it up next cycle
  → AI receives "Fix the login bug" as a prompt
```

### AI → User

```
AI calls message_user("The login bug is fixed. See commit abc123.")
  → server.py reads bot token + user ID from config
  → Sends Telegram message: "/s_work_0_1  2026-03-21 14:35\n\nThe login bug is fixed. See commit abc123."
  → User sees message in Telegram, taps /s_work_0_1 to switch session if they want to reply
```

## Dependencies

- `pyTelegramBotAPI` — added to `requirements.txt`
- Used by both `telebot_runner.py` (bot process) and `server.py` (message_user tool)

## File Inventory (new/changed)

| File | Status | Purpose |
|------|--------|---------|
| `telebot_runner.py` | New | Telegram bot process |
| `server.py` | Changed | Add `message_user` tool |
| `config.yaml` | Changed | Add `telegram_bot_token`, `telegram_user_id` |
| `setup.py` | Changed | Add Telegram setup section |
| `requirements.txt` | Changed | Add `pyTelegramBotAPI` |
| `~/.ai-sessions/session_map.json` | Auto-generated | Session name ↔ command mapping |
