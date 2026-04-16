# telegram-bridge

Telegram transport component for Claude Code.

This repo is a reusable bridge, not the main entrypoint for the job-bot workflow.

Preferred adoption path:
1. Start from the private modular skills repo `kirilly/kirilly-claude-skills`
2. Try `job-search` locally first
3. Add `tg-bridge` or `job-search-tg-bridge` if Telegram delivery is useful
4. Use this repo as the transport layer those skills rely on

## Local setup

```bash
bun install
```

## Role in the stack

- receives and sends Telegram messages
- exposes the `tg` Claude channel runtime
- can be reused by multiple higher-level skills

It should stay transport-focused and not own job-search product logic.
