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
