---
tags:
  - project/personal
  - type/reference
  - domain/telegram
---

# Telegram Channel Server — Architecture & Config

## Architecture

Layered architecture: MCP channel (primary, instant) + fallback dispatcher (`claude -p --resume`).

### Layer 1: MCP Channel (primary)

`channel-server.ts` — ~80 lines of Bun + MCP SDK + grammy. Registered as `tg` MCP server in `~/.claude.json`. Messages arrive instantly as `<channel source="tg">` tags.

```bash
# Start Claude with TG channel
claude --dangerously-load-development-channels server:tg

# Or just start claude (tg server auto-starts from ~/.claude.json MCP config)
# Then say "start telegram" to activate tg-dispatch skill
```

### Layer 2: Fallback Dispatcher

`telegram-dispatcher.py` — standalone Python, zero deps. Polls Telegram, dispatches via `claude -p --resume` (session-persistent). Use when MCP is down.

```bash
python ~/Documents/harness/1-skills/personal/telegram/telegram-dispatcher.py
```

## Files

| Path | Purpose |
|------|---------|
| `channel-server.ts` | MCP channel server (Layer 1) |
| `telegram-dispatcher.py` | Fallback dispatcher (Layer 2) |
| `telegram-bridge.py` | Legacy inbox/outbox bridge (reference) |
| `bridge-config.json` | Bot token env, allowed users, poll timeout |
| `bridge.log` | Activity log |

## Config

- `bot_token_env` — env var name for bot token (default: `TELEGRAM_BOT_TOKEN`)
- `allowed_users` — numeric Telegram user IDs that can send messages
- MCP registration: `~/.claude.json` → `mcpServers.tg`

**Bot:** `@claude_code_brg_bot` (created via @BotFather)

**Security:** Allowlist-only. Messages from unknown senders silently dropped. Token from env var, never hardcoded.

## Credentials

- API credentials: `~/code-environment/telegram.env` (TG_API_ID, TG_API_HASH)
- Session file: `~/code-environment/.telegram-session.session` (chmod 600)
- First auth: `python tg.py auth` — interactive (phone code + optional 2FA)
- Session persists until revoked in Telegram Settings > Devices

## Note Format

Notes go in `~/evernote/` (flat, no subdirectories). Images in `~/evernote/_resources/`.

```markdown
---
tags:
  - source/telegram
  - channel/<channel-name>
date: YYYY-MM-DD
---

# <post title or first line, truncated to ~80 chars>

<post text converted to markdown>

![[tg-channelname-msgid-1.jpg]]

---
Source: t.me/<channel>/<message_id>
```

**Naming conventions:**
- Note: `~/evernote/tg-<channel>-<msg_id>.md`
- Media: `~/evernote/_resources/tg-<channel>-<msg_id>[-N].jpg`

Strip `@` from channel name in filenames. For posts without text, use first line of forwarded message or "Telegram media post".
