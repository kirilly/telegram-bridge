---
tags:
  - project/personal
  - type/skill
  - domain/telegram
  - status/active
---
# Telegram Channel Reader

Read Telegram channels/groups, search across them, and save posts as Obsidian notes in `~/evernote`.

## L2 References

| File | Contents |
|---|---|
| [[tg-commands]] | Full command reference, auth, read/search/post/media commands, browse/search/save workflows |
| [[tg-channel-list]] | All 80+ channels organized by folder (Tech/AI, Blogs, Argentina, Chats, Bots) |
| [[tg-channel-server]] | Claude ↔ Telegram architecture, MCP channel-server.ts, dispatcher, note format |

## Channel Folders (Search Scope)

- Tech/AI/Career (24) — default search scope
- Blogs & Media (17) — add if topic is broader than tech
- Argentina Life (28) — only if user mentions Argentina
- Active Chats (7) — only if user mentions specific group
- Bots & Saved (22) — not typically searched

## Claude ↔ Telegram

- Layer 1 (primary): MCP `channel-server.ts` — messages arrive as `<channel source="tg">` tags
- Layer 2 (fallback): `telegram-dispatcher.py` — polls + dispatches via `claude -p --resume`

## Related

- [[tg-dispatch]] — route TG messages to background agents
- [[vps]] — always-on Claude Code server running TG dispatch 24/7
- [[youtube]] — another media extraction skill in the same domain
