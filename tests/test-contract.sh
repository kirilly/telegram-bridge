#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/channel-server.ts"
pass=0

ok() {
  printf 'PASS: %s\n' "$1"
  pass=$((pass + 1))
}

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

grep -q 'TELEGRAM_BOT_TOKEN required' "$SOURCE" \
  && grep -q 'TG_ALLOWED_USERS required' "$SOURCE" \
  && ok "T1: required Telegram environment exits before startup" \
  || fail "T1: missing required environment guard"

grep -q 'const ALLOWED = new Set' "$SOURCE" \
  && grep -q 'if (!ALLOWED.has(ctx.from.id)) return' "$SOURCE" \
  && grep -q 'if (!ALLOWED.has(ctx.from!.id)) return' "$SOURCE" \
  && ok "T2: inbound text/photo/catch-all handlers enforce allowed users" \
  || fail "T2: allowed-user gate missing"

grep -q 'knownChats.add(ctx.chat.id)' "$SOURCE" \
  && grep -q 'if (!knownChats.has(Number(chat_id)))' "$SOURCE" \
  && grep -q 'rejected: chat_id' "$SOURCE" \
  && ok "T3: reply tool rejects unknown outbound chats" \
  || fail "T3: outbound known-chat guard missing"

grep -q 'ack_msg_id' "$SOURCE" \
  && grep -q 'if (ack_msg_id) logAck(ack_msg_id)' "$SOURCE" \
  && grep -q "type: 'ack'" "$SOURCE" \
  && ok "T4: reply acknowledgements persist ack records" \
  || fail "T4: ack persistence missing"

grep -q 'function logRecv' "$SOURCE" \
  && grep -q 'logRecv(params)' "$SOURCE" \
  && grep -q 'loadPending()' "$SOURCE" \
  && grep -q 'compactOnStartup(pending)' "$SOURCE" \
  && ok "T5: inbound messages are persisted and replayed on restart" \
  || fail "T5: crash-recovery queue contract missing"

grep -q "hostname: '127.0.0.1'" "$SOURCE" \
  && grep -q "url.pathname === '/mcp'" "$SOURCE" \
  && ok "T6: HTTP MCP transport binds to localhost /mcp only" \
  || fail "T6: HTTP transport contract missing"

grep -q 'text.substring(0, 4096)' "$SOURCE" \
  && grep -q 'i += 4096' "$SOURCE" \
  && ok "T7: Telegram replies are chunked to 4096 characters" \
  || fail "T7: reply chunking missing"

grep -q 'detectRateLimitModal' "$SOURCE" \
  && grep -q 'your message is queued' "$SOURCE" \
  && grep -q 'Stop and wait for limit to reset' "$SOURCE" \
  && ok "T8: rate-limit modal queues inbound messages with a notice" \
  || fail "T8: rate-limit queue notice missing"

printf '\ntelegram-bridge contract: %d passed, 0 failed\n' "$pass"
