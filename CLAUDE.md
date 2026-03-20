# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**selfcontrol-mcp** is an MCP server that gives an AI the ability to prompt itself through tmux. It schedules prompts for immediate or future delivery, with a background scheduler that ensures continuous activity via fallback prompts. See `docs/CONCEPT.md` for the full design.

License: GPL v3

## Architecture

Three Python scripts:

1. **MCP Server** (`server.py`) — FastMCP server exposing:
   - **Tools:** `prompt_now(message)`, `prompt_later(message, target_time?, delay?)`
   - **Prompts:** `start` — returns contents of `start.md` (bootstraps a session)
   - Writes prompt files to `~/.ai-sessions/{session}:{window}.{pane}/queue/`
   - Auto-detects tmux pane via `tmux display-message -p`

2. **Background Scheduler** (`scheduler.py`) — Single global instance, checks all session folders every 60s:
   - Priority: queue (oldest due) → input folder (oldest) → config default prompt
   - Sends via `tmux send-keys -t {s}:{w}.{p}` + Enter
   - Sets `generating.lock` after sending; skips locked sessions (< 30 min old)
   - Logs each sent prompt to `history.log`; deletes consumed files

3. **Hook Script** (`reset_generating.py`) — Called by Claude Code hook after generation completes. Detects current tmux pane and deletes the corresponding `generating.lock`.

## Session Folder Structure (`~/.ai-sessions/`)

```
~/.ai-sessions/{session}:{window}.{pane}/
├── queue/            # Timestamped prompt files (filename: {YYYYMMDDTHHMMSS}_{rand}.txt)
├── input/            # Manual fallback prompts (sorted by mtime, oldest first)
├── generating.lock   # Present while AI is working (contains timestamp)
└── history.log       # Audit log of all sent prompts
```

## Key Files

| File | Purpose |
|------|---------|
| `server.py` | FastMCP MCP server |
| `scheduler.py` | Background prompt scheduler |
| `reset_generating.py` | Hook script to clear generating lock |
| `config.yaml` | Default prompt, base_dir, intervals |
| `start.md` | User-edited startup prompt (gitignored) |
| `example.start.md` | Template for `start.md` |

## Development

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run MCP server (typically configured in Claude Code MCP settings)
python server.py

# Run scheduler (in a separate tmux pane)
python scheduler.py

# Clear generating lock (called by hooks, or manually)
python reset_generating.py
```

## Prompt File Naming

- Queue: `20260320T153000_a1b2c3.txt` — target time + random suffix
- `prompt_now` uses `19000101T000000` as timestamp to sort first
- Content: raw prompt text
