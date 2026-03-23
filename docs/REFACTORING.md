# OOP-Refactoring: Zusammenfassung

**Datum:** 2026-03-23
**Tag vor Refactoring:** `v1.0-pre-refactor` (zum Zurückspringen falls etwas kaputt ist)

## Motivation

Der gesamte Code lag in flachen Scripts mit massiver Duplikation:
- `load_config()` war 6x kopiert
- `BASE_DIR`-Expansion 5x
- `random_suffix()` 2x identisch
- Tmux-Pane-Detection 3x mit leichten Varianten
- Telegram-Config-Laden 4x
- Lock-File-Operationen über 3 Dateien verstreut
- Rate-Limit JSON über 3 Dateien verstreut
- `session_mapper.py` war ein Utility-Modul mit losen Funktionen

## Was gemacht wurde

### Neues `lib/`-Package

6 Klassen ersetzen alle duplizierten Patterns:

```
lib/
├── __init__.py          # Re-exports aller Klassen
├── config.py            # Config — typed config.yaml Zugriff
├── tmux.py              # TmuxClient + NotInTmuxError
├── session.py           # Session — eine Session-Directory
├── session_manager.py   # SessionManager — alle Sessions + Map
├── telegram.py          # TelegramClient — One-Shot Sending
└── rate_limiter.py      # RateLimiter — rate_limit.json
```

#### `Config` (lib/config.py)
- Lädt `config.yaml` einmalig, bietet Properties mit Defaults
- `REPO_DIR` und `CONFIG_PATH` als Klassenattribute
- Ersetzt 6 separate `load_config()` Funktionen + manuelle `config.get()`-Aufrufe

#### `TmuxClient` (lib/tmux.py)
- `get_pane_id()` — raises `NotInTmuxError`
- `get_pane_id_safe()` — returns `"unknown"` statt Exception
- `send_keys(pane, text)` — literal mode + Enter
- `send_enter(pane)` — nur Enter
- Ersetzt 3 separate tmux subprocess-Aufrufe in server.py, session_mapper.py, reset_generating.py

#### `Session` (lib/session.py)
- Repräsentiert ein Session-Verzeichnis mit allen Subdirs als Properties
- Lock: `is_locked`, `is_lock_stale()`, `set_lock()`, `clear_lock()`
- Queue: `get_due_queue_files()`, `write_queue_file()`
- Input: `get_input_files()`, `write_input_file()`
- Permissions: `write_permission_response()`, `read_permission_response()`
- History: `log_history()`
- Utilities: `random_suffix()`, `TIMESTAMP_FORMAT`, `IMMEDIATE_TIMESTAMP`

#### `SessionManager` (lib/session_manager.py)
- `list_sessions()` → `list[Session]`
- `get_session(name)` → `Session`
- `refresh_map()`, `load_map()`, `decode_command()`
- Static: `encode_name()`, `escape_markdown()`
- Ersetzt komplett `session_mapper.py`

#### `TelegramClient` (lib/telegram.py)
- `send_message()`, `send_photo()`, `send_document()`, `edit_message()`
- Returns `message_id` oder `None` bei Fehler
- Ersetzt 4x manuelles `telebot.TeleBot(token)` + try/except

#### `RateLimiter` (lib/rate_limiter.py)
- `is_limited` (Property), `set_limit()`, `load()`, `clear()`
- Ersetzt verstreute `rate_limit.json` Operationen in 3 Dateien

### Umgeschriebene Scripts

| Script | Vorher | Nachher |
|--------|--------|---------|
| `server.py` | Eigenes `load_config()`, `get_tmux_pane()`, `random_suffix()`, `write_prompt_file()` | Nutzt `Config`, `Session`, `TmuxClient`, `TelegramClient`, `SessionManager` |
| `scheduler.py` | 12 lose Funktionen + `main()` Loop | `Scheduler`-Klasse mit `process_session()` und `run()` |
| `telebot_runner.py` | Modul-Level Bot + 12 lose Handler-Funktionen | `TelebotRunner`-Klasse, Handler via `_register_handlers()` |
| `reset_generating.py` | Eigene tmux-Detection, hardcoded BASE_DIR | 4 Zeilen: `TmuxClient` + `Session.clear_lock()` |
| `notify_user.py` | Eigenes Config-Laden, eigenes `telebot.TeleBot()` | Nutzt `Config`, `TmuxClient`, `TelegramClient`, `SessionManager` |
| `permission_handler.py` | Eigenes Config-Laden, eigene random_id, eigenes Polling | Nutzt lib-Klassen, `Session.read_permission_response()` für Polling |
| `rate_limit_handler.py` | Eigenes Config-Laden, manuelles JSON-Schreiben | Nutzt `RateLimiter.set_limit()`, `TelegramClient`, `TmuxClient` |
| `setup.py` | Bug: undefinierte Variable `rate_limit_wait` auf Zeile 109 | Bug gefixt (Zeile entfernt), Pfade aus `lib.config.REPO_DIR` |

### Gelöschte Dateien

- `session_mapper.py` — komplett ersetzt durch `SessionManager` + `TmuxClient`

## Was zu testen ist

**WICHTIG: Der Code wurde auf Windows refactored, wo kein tmux und kein Telegram-Token vorhanden ist. Syntax und Import-Tests sind bestanden, aber ein Funktionstest auf dem Ubuntu-Server ist nötig.**

Teste in dieser Reihenfolge:

1. **Imports prüfen:**
   ```bash
   python -c "from lib import Config, Session, SessionManager, TmuxClient, TelegramClient, RateLimiter; print('OK')"
   ```

2. **MCP Server starten:**
   ```bash
   python server.py
   ```
   Prüfen: Startet ohne Fehler, Tools sind verfügbar

3. **Scheduler starten:**
   ```bash
   python scheduler.py
   ```
   Prüfen: Loggt "Scheduler started", erkennt Sessions, sendet Prompts

4. **Telegram Bot starten:**
   ```bash
   python telebot_runner.py
   ```
   Prüfen: Loggt "Telegram bot started", reagiert auf Befehle

5. **Hooks testen:**
   - Stop-Hook: Prüfen ob `generating.lock` gelöscht wird
   - Notification-Hook: Prüfen ob Telegram-Nachricht kommt
   - Permission-Hook: Prüfen ob Allow/Deny über Telegram funktioniert
   - Rate-Limit-Hook: Prüfen ob `rate_limit.json` geschrieben wird

## Architektur-Diagramm

```mermaid
classDiagram
    class Config {
        +REPO_DIR: Path
        +CONFIG_PATH: Path
        +START_MD: Path
        +default_prompt: str
        +base_dir: Path
        +check_interval_seconds: int
        +default_prompt_interval_minutes: int
        +generating_timeout_minutes: int
        +permission_timeout_minutes: int
        +permission_timeout_message: str
        +telegram_bot_token: str
        +telegram_user_id: int
        +reload()
    }

    class TmuxClient {
        +get_pane_id() str
        +get_pane_id_safe() str
        +send_keys(pane, text) bool
        +send_enter(pane) bool
    }

    class Session {
        +name: str
        +path: Path
        +queue_dir: Path
        +input_dir: Path
        +permissions_dir: Path
        +lock_path: Path
        +history_path: Path
        +is_locked: bool
        +ensure_dirs() Session
        +is_lock_stale(timeout) bool
        +set_lock()
        +clear_lock() bool
        +log_history(source, text, pane)
        +get_due_queue_files() list
        +get_input_files() list
        +write_queue_file(ts, msg) str
        +write_input_file(content) Path?
        +write_permission_response(id, decision) bool
        +read_permission_response(id) str?
        +random_suffix(length) str$
    }

    class SessionManager {
        +base_dir: Path
        +map_path: Path
        +get_session(name) Session
        +list_sessions() list~Session~
        +refresh_map() dict
        +load_map() dict
        +decode_command(cmd) str?
        +encode_name(name) str$
        +escape_markdown(encoded) str$
    }

    class TelegramClient {
        +bot: TeleBot
        +user_id: int
        +send_message(text, parse_mode?) int?
        +send_photo(photo, caption?) int?
        +send_document(doc, caption?) int?
        +edit_message(msg_id, text, parse_mode?) bool
    }

    class RateLimiter {
        +path: Path
        +is_limited: bool
        +set_limit(error, details, session, msg_id?)
        +load() dict?
        +clear() bool
    }

    class Scheduler {
        +config: Config
        +tmux: TmuxClient
        +sessions: SessionManager
        +rate_limiter: RateLimiter
        +process_session(session)
        +run()
    }

    class TelebotRunner {
        +config: Config
        +sessions: SessionManager
        +rate_limiter: RateLimiter
        +bot: TeleBot
        +run()
    }

    SessionManager --> Session : creates
    Scheduler --> Config
    Scheduler --> TmuxClient
    Scheduler --> SessionManager
    Scheduler --> RateLimiter
    TelebotRunner --> Config
    TelebotRunner --> SessionManager
    TelebotRunner --> RateLimiter
