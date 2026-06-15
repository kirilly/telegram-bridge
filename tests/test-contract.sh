#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/channel-server.ts"
MIRY_SOURCE="$ROOT/miry-server.ts"
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

grep -q 'TELEGRAM_BOT_TOKEN required' "$MIRY_SOURCE" \
  && grep -q 'TG_ALLOWED_USERS required' "$MIRY_SOURCE" \
  && ok "T9: Miry requires Telegram token and allowed users" \
  || fail "T9: Miry required environment guard missing"

grep -q 'if (!ALLOWED.has(ctx.from.id)) return' "$MIRY_SOURCE" \
  && grep -q 'if (!ALLOWED.has(ctx.from!.id)) return' "$MIRY_SOURCE" \
  && ok "T10: Miry inbound handlers enforce allowed users" \
  || fail "T10: Miry allowed-user gate missing"

grep -q 'function logRecv' "$MIRY_SOURCE" \
  && grep -q 'logRecv(params)' "$MIRY_SOURCE" \
  && grep -q 'function logAck' "$MIRY_SOURCE" \
  && grep -q 'logAck(params.meta.msg_id)' "$MIRY_SOURCE" \
  && ok "T11: Miry preserves queue-before-run and ack-after-reply" \
  || fail "T11: Miry queue/ack contract missing"

grep -q "return \\['exec', 'resume'" "$MIRY_SOURCE" \
  && grep -q "'--json'" "$MIRY_SOURCE" \
  && grep -q "'-o'" "$MIRY_SOURCE" \
  && grep -q "'--sandbox', CODEX_SANDBOX" "$MIRY_SOURCE" \
  && grep -q "'--skip-git-repo-check'" "$MIRY_SOURCE" \
  && ok "T12: Miry invokes Codex exec/resume with JSONL and final-output capture" \
  || fail "T12: Miry Codex command contract missing"

grep -q 'SESSION_ID_PATH' "$MIRY_SOURCE" \
  && grep -q 'writeSessionId(result.threadId)' "$MIRY_SOURCE" \
  && grep -q 'readSessionId()' "$MIRY_SOURCE" \
  && ok "T13: Miry stores and resumes the Codex session id" \
  || fail "T13: Miry session-id persistence missing"

if grep -q 'notifications/claude/channel' "$MIRY_SOURCE"; then
  fail "T14: Miry must not use Claude channel notifications"
else
  ok "T14: Miry does not use Claude channel notifications"
fi

grep -q 'knownChats.has(Number(chatId))' "$MIRY_SOURCE" \
  && grep -q 'safeText.substring(0, 4096)' "$MIRY_SOURCE" \
  && ok "T15: Miry outbound replies keep known-chat guard and chunking" \
  || fail "T15: Miry outbound safety contract missing"

ack_count=$(grep -c 'logAck(params.meta.msg_id)' "$MIRY_SOURCE")
if [[ "$ack_count" -ge 2 ]] && grep -q 'Miry/Codex failed; this message has been acked after the failure reply' "$MIRY_SOURCE"; then
  ok "T16: Miry failure replies are acked to prevent replay spam"
else
  fail "T16: Miry failure reply ack contract missing"
fi

grep -q "miry-queue.jsonl" "$MIRY_SOURCE" \
  && ok "T17: Miry uses a separate queue file from the old Claude bridge" \
  || fail "T17: Miry must not replay the old Claude queue"

grep -q 'deleteWebhook({ drop_pending_updates: true })' "$MIRY_SOURCE" \
  && grep -q 'getUpdates({ offset: -1, limit: 1, timeout: 0 })' "$MIRY_SOURCE" \
  && grep -q 'getUpdates({ offset: lastUpdateId + 1, limit: 1, timeout: 0 })' "$MIRY_SOURCE" \
  && grep -q 'bot.start({ drop_pending_updates: true })' "$MIRY_SOURCE" \
  && ok "T18: Miry drops Telegram pending updates before polling" \
  || fail "T18: Miry must not process stale Telegram update backlog"

grep -q 'JOB_SEARCH_FEEDBACK_LOG' "$MIRY_SOURCE" \
  && grep -q 'looksLikeDailySearchFeedback' "$MIRY_SOURCE" \
  && grep -q 'recordSearchFeedback' "$MIRY_SOURCE" \
  && grep -q 'feedback-events.jsonl' "$MIRY_SOURCE" \
  && grep -q 'Feedback recorded' "$MIRY_SOURCE" \
  && ok "T19: Miry records daily search feedback replies to local state" \
  || fail "T19: Miry daily search feedback capture missing"

printf '\ntelegram-bridge contract: %d passed, 0 failed\n' "$pass"
