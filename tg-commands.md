---
tags:
  - project/personal
  - type/reference
  - domain/telegram
  - status/active
---

# Telegram Commands Reference

Script: `~/Documents/harness/1-skills/personal/telegram/tg.py`

## Command Reference

```bash
# Auth (interactive, one-time)
python tg.py auth

# List all channels/groups (JSON)
python tg.py channels

# List Telegram folders with channels
python tg.py folders

# Read recent posts from a channel
python tg.py read <channel> --limit 20

# Search across all channels (or specific ones)
python tg.py search "query"
python tg.py search "query" --channels @chan1 @chan2

# Get a specific post
python tg.py post <channel> <msg_id>

# Download media to a directory
python tg.py media <channel> <msg_id> ~/evernote/_resources/
```

Channel identifiers: `@username`, `https://t.me/channelname`, or numeric ID.

## Workflows

### Browse channels
1. `tg.py folders` — organized view, or `tg.py channels` for full list
2. `tg.py read @channelname --limit 10` — browse recent posts

### Search across channels
1. `tg.py search "keyword"` — all channels (5 results each)
2. `tg.py search "keyword" --channels @chan1 @chan2 --limit 10` — targeted

### Save post as note
1. `tg.py post @channel <msg_id>` — get full post
2. `tg.py media @channel <msg_id> ~/evernote/_resources/` — download media
3. Create `~/evernote/tg-<channel>-<msg_id>.md` — note format in [[tg-channel-server]]

## Related

- [[telegram]]
- [[tg-channel-server]]
- [[tg-channel-list]]
