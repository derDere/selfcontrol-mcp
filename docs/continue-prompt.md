# Continue Prompt — selfcontrol-mcp

> **Context:** This project was initialized in a prior Claude Code session. The design phase is complete. Implementation has NOT started yet.

## What exists so far

| File | Status | Purpose |
|------|--------|---------|
| `CLAUDE.md` | Done | Project guidance for Claude Code |
| `docs/CONCEPT.md` | Done | Full design document — **read this first** |
| `example.start.md` | Done | Template for `start.md` (user copies and edits) |
| `.gitignore` | Updated | Added `start.md` |
| `README.md` | Original | Brief one-liner, could be expanded later |
| `LICENSE` | Original | GPL v3 |

## What needs to be implemented

All implementation is pending. The following files need to be created:

### 1. `requirements.txt`
- `fastmcp` (latest)
- `pyyaml` (latest)
- No pinned versions

### 2. `config.yaml`
```yaml
default_prompt: "Continue working on the current task. If no task is active, review recent changes and suggest improvements."
base_dir: "~/.ai-sessions"
check_interval_seconds: 60
generating_timeout_minutes: 30
```

### 3. `server.py` — FastMCP MCP Server
- Uses `fastmcp` library (`from fastmcp import FastMCP`)
- Auto-detects current tmux pane via `tmux display-message -p '#{session_name}:#{window_index}.#{pane_index}'`
- Creates session folder at `~/.ai-sessions/{s}:{w}.{p}/` with `queue/` and `input/` subdirs on startup
- **Tool `prompt_now(message: str)`** — writes a prompt file to queue with timestamp `19000101T000000_{random}.txt` so it always sorts first
- **Tool `prompt_later(message: str, target_time: str | None, delay: str | None)`** — writes a prompt file with a future timestamp. `target_time` is absolute ISO 8601, `delay` is relative (e.g. `"10m"`, `"2h"`, `"1d"`). At least one required; `target_time` takes precedence if both given
- **Prompt `start`** — uses `@mcp.prompt` decorator, reads and returns contents of `start.md` from the repo root. This is an MCP prompt (not a tool)
- Prompt file naming: `{YYYYMMDDTHHMMSS}_{6char_random}.txt`, content is raw prompt text

### 4. `scheduler.py` — Background Scheduler
- Runs as standalone script, one global instance
- Loads `config.yaml` on startup
- Every `check_interval_seconds` (default 60), iterates over all session folders in `base_dir`:
  1. **Check lock** — if `generating.lock` exists and is younger than `generating_timeout_minutes`, skip this session
  2. **Check queue** — find files in `queue/` where filename timestamp ≤ now. Pick the oldest one (sort by filename)
  3. **Fallback to input** — if no due queue files, pick oldest file from `input/` (sorted by filesystem mtime)
  4. **Fallback to default** — if input is also empty, use `default_prompt` from config
  5. **Send** — run `tmux send-keys -t {s}:{w}.{p} '{prompt_content}' Enter`
  6. **Set lock** — write current timestamp to `generating.lock`
  7. **Log** — append to `history.log`: `[{ISO timestamp}] [{source: queue|input|default}] {prompt summary (first 100 chars)} -> {s}:{w}.{p}`
  8. **Delete** — remove the consumed prompt file (queue or input). Do NOT delete anything for default prompts
- Only sends **one prompt per session per cycle**
- Handle edge cases: missing folders, empty files, tmux errors

### 5. `reset_generating.py` — Hook Script
- Designed to be called from a Claude Code hook (user configures the hook themselves)
- On execution:
  1. Runs `tmux display-message -p '#{session_name}:#{window_index}.#{pane_index}'` to detect current pane
  2. Deletes `~/.ai-sessions/{s}:{w}.{p}/generating.lock` if it exists
- Should be a simple, fast script — no config loading needed (base_dir can be hardcoded or use the same default `~/.ai-sessions`)

## Design decisions already made (do not re-ask)

- **One prompt per scheduler cycle per session** — never batch-send
- **`prompt_now` uses 1900 timestamp trick** — not instant bypass
- **Input files are consumed** (deleted after sending), same as queue files
- **All sent prompts are logged** to `history.log` per session folder
- **Generating lock** is file-based with 30 min timeout
- **tmux send-keys includes Enter** at the end
- **No list/cancel tools** in the MCP server
- **No version pinning** in requirements.txt
- **`start.md` is gitignored**, `example.start.md` is committed
- **`start` is an MCP prompt** (`@mcp.prompt`), not a tool
- **Session detection** via `tmux display-message -p`
- **One global scheduler** manages all session folders

## Conversation style notes

The user prefers concise communication. Ask clarifying questions before implementing if anything is ambiguous, but don't re-ask things already decided above. The user wants to discuss a bit more before implementation begins — wait for their go-ahead.
