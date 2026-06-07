# telegram-bridge Coverage Matrix

Thresholds:

- `critical`: 100% covered by runnable tests.
- `high`: at least 80% covered by runnable tests.

| ID | Repo | Risk | Behavior | Required test type | Evidence | Gap | QA note |
|----|------|------|----------|--------------------|----------|-----|---------|
| C01 | telegram-bridge | critical | The bridge refuses to start unless both `TELEGRAM_BOT_TOKEN` and `TG_ALLOWED_USERS` are configured. | Source contract | `tests/test-contract.sh` T1 | covered | Start without each variable and expect a hard failure before polling. |
| C02 | telegram-bridge | critical | Incoming messages are accepted only from configured Telegram user ids. | Source contract | `tests/test-contract.sh` T2 | covered | Message from an unlisted user id must not reach Claude. |
| C03 | telegram-bridge | critical | The reply tool rejects outbound replies to chat ids that were not seen in inbound messages. | Source contract | `tests/test-contract.sh` T3 | covered | Prompt injection must not make Claude message arbitrary chats. |
| C04 | telegram-bridge | critical | Reply acknowledgements append ack records so crash recovery does not redeliver processed messages. | Source contract | `tests/test-contract.sh` T4 | covered | Reply with `ack_msg_id`, restart, and expect the message not to replay. |
| C05 | telegram-bridge | critical | Inbound text/photo messages are persisted before channel notification for crash recovery. | Source contract | `tests/test-contract.sh` T5 | covered | Kill process after receipt; unacked message must remain replayable. |
| H01 | telegram-bridge | high | HTTP transport binds only to localhost and exposes `/mcp`. | Source contract | `tests/test-contract.sh` T6 | covered | Do not expose the MCP transport on a public interface. |
| H02 | telegram-bridge | high | Long Telegram replies are chunked to Telegram's 4096 character limit. | Source contract | `tests/test-contract.sh` T7 | covered | Send a long reply and expect multiple chunks. |
| H03 | telegram-bridge | high | Rate-limit modal detection queues messages instead of silently dropping them. | Source contract | `tests/test-contract.sh` T8 | covered | Simulate Claude rate-limit modal and expect a queued notice. |
| C06 | telegram-bridge | critical | Miry refuses to start unless both `TELEGRAM_BOT_TOKEN` and `TG_ALLOWED_USERS` are configured. | Source contract | `tests/test-contract.sh` T9 | covered | Start Miry without each variable and expect a hard failure before polling. |
| C07 | telegram-bridge | critical | Miry accepts inbound text/photo/catch-all messages only from configured Telegram user ids. | Source contract | `tests/test-contract.sh` T10 | covered | Message from an unlisted user id must not reach Codex. |
| C08 | telegram-bridge | critical | Miry persists inbound messages before Codex delivery and writes ack records only after replies are sent. | Source contract | `tests/test-contract.sh` T11 | covered | Kill after receipt and expect replay; reply success should prevent replay. |
| C09 | telegram-bridge | critical | Miry invokes Codex through `codex exec`/`exec resume` with JSONL event capture and final-output file capture. | Source contract | `tests/test-contract.sh` T12-T13 | covered | Runner must capture thread id and final response without terminal banners. |
| C10 | telegram-bridge | critical | Miry does not use Claude channel notifications. | Source contract | `tests/test-contract.sh` T14 | covered | A Codex runner that still depends on `notifications/claude/channel` is not a replacement. |
| C11 | telegram-bridge | critical | Miry outbound replies keep the known-chat guard and Telegram chunking. | Source contract | `tests/test-contract.sh` T15 | covered | Prompt output must not message arbitrary chats or exceed Telegram message length. |
| C12 | telegram-bridge | critical | Miry failure replies are acked after Telegram send so service restarts do not replay duplicate failure messages. | Source contract | `tests/test-contract.sh` T16 | covered | If Codex auth fails and Miry sends a failure reply, restart must not send that same failure again. |
| C13 | telegram-bridge | critical | Miry uses its own queue file, not the old Claude bridge queue. | Source contract | `tests/test-contract.sh` T17 | covered | Cutover must not replay stale unacked Claude Bot E2E backlog. |
