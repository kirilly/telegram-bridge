#!/usr/bin/env bun
/**
 * Miry Telegram runner for Codex.
 *
 * Polls Telegram directly, persists inbound messages before model delivery,
 * runs Codex non-interactively, sends the final Codex message back to Telegram,
 * and only then appends the ack record.
 */

import { Bot } from 'grammy'
import { appendFileSync, existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync, mkdtempSync } from 'fs'
import { dirname, join } from 'path'
import { tmpdir } from 'os'
import { spawn } from 'child_process'

const TOKEN = process.env.TELEGRAM_BOT_TOKEN
if (!TOKEN) {
  process.stderr.write('TELEGRAM_BOT_TOKEN required\n')
  process.exit(1)
}

const ALLOWED_RAW = process.env.TG_ALLOWED_USERS
if (!ALLOWED_RAW) {
  process.stderr.write('TG_ALLOWED_USERS required (comma-separated user IDs)\n')
  process.exit(1)
}

const ALLOWED = new Set(ALLOWED_RAW.split(',').map(Number))
const IMG_DIR = process.env.TG_IMAGE_DIR ?? '/tmp/tg-images'
const QUEUE_PATH = process.env.QUEUE_PATH ?? '/home/dev/telegram/miry-queue.jsonl'
const SESSION_ID_PATH = process.env.MIRY_SESSION_ID_PATH ?? '/home/dev/telegram/.miry-last-session-id'
const MIRY_LOG_PATH = process.env.MIRY_LOG_PATH ?? '/home/dev/telegram/miry.log'
const CODEX_BIN = process.env.CODEX_BIN ?? 'codex'
const CODEX_CWD = process.env.MIRY_CODEX_CWD ?? process.cwd()
const CODEX_MODEL = process.env.MIRY_CODEX_MODEL
const CODEX_SANDBOX = process.env.MIRY_CODEX_SANDBOX ?? 'danger-full-access'
const CODEX_TIMEOUT_MS = Number(process.env.MIRY_CODEX_TIMEOUT_MS ?? 7200000)
const BYPASS_HOOK_TRUST = process.env.MIRY_CODEX_BYPASS_HOOK_TRUST === '1'

mkdirSync(dirname(QUEUE_PATH), { recursive: true })
mkdirSync(dirname(SESSION_ID_PATH), { recursive: true })
mkdirSync(dirname(MIRY_LOG_PATH), { recursive: true })

type TelegramParams = {
  content: string
  meta: {
    sender: string
    chat_id: string
    msg_id: string
    reply_to_msg_id?: string
    reply_to_preview?: string
    image_path?: string
  }
}

const knownChats = new Set<number>()
const queue: TelegramParams[] = []
let processing = false
const bot = new Bot(TOKEN)

function logLine(message: string) {
  appendFileSync(MIRY_LOG_PATH, `${new Date().toISOString()} ${message}\n`)
}

function logRecv(params: TelegramParams) {
  appendFileSync(QUEUE_PATH, JSON.stringify({ type: 'recv', ts: Date.now(), msg_id: params.meta.msg_id, params }) + '\n')
}

function logAck(msg_id: string) {
  appendFileSync(QUEUE_PATH, JSON.stringify({ type: 'ack', ts: Date.now(), msg_id }) + '\n')
}

function loadPending(): TelegramParams[] {
  if (!existsSync(QUEUE_PATH)) return []
  const recv = new Map<string, TelegramParams>()
  const acked = new Set<string>()
  for (const line of readFileSync(QUEUE_PATH, 'utf8').split('\n')) {
    if (!line) continue
    try {
      const r = JSON.parse(line)
      if (r.type === 'recv') recv.set(r.msg_id, r.params)
      else if (r.type === 'ack') acked.add(r.msg_id)
    } catch {}
  }
  const pending: TelegramParams[] = []
  for (const [id, params] of recv) if (!acked.has(id)) pending.push(params)
  return pending
}

function compactOnStartup(pending: TelegramParams[]) {
  const lines = pending.map(p => JSON.stringify({ type: 'recv', ts: Date.now(), msg_id: p.meta.msg_id, params: p }))
  writeFileSync(QUEUE_PATH, lines.length ? lines.join('\n') + '\n' : '')
  for (const p of pending) {
    if (p.meta?.chat_id) knownChats.add(Number(p.meta.chat_id))
  }
}

function replyContext(message: any) {
  const replied = message.reply_to_message
  if (!replied) return {}
  const repliedText = replied.text ?? replied.caption ?? ''
  const preview = repliedText.replace(/\s+/g, ' ').trim().slice(0, 240)
  return {
    reply_to_msg_id: String(replied.message_id),
    reply_to_preview: preview,
  }
}

function withReplyPrefix(content: string, message: any) {
  const replied = message.reply_to_message
  if (!replied) return content
  const repliedText = replied.text ?? replied.caption ?? ''
  const preview = repliedText.replace(/\s+/g, ' ').trim().slice(0, 240)
  if (!preview) return `[Reply to msg ${replied.message_id}]\n\n${content}`
  return `[Reply to msg ${replied.message_id}: ${preview}]\n\n${content}`
}

function readSessionId(): string | null {
  if (!existsSync(SESSION_ID_PATH)) return null
  const sessionId = readFileSync(SESSION_ID_PATH, 'utf8').trim()
  return sessionId || null
}

function writeSessionId(sessionId: string) {
  writeFileSync(SESSION_ID_PATH, `${sessionId}\n`)
}

function buildPrompt(params: TelegramParams) {
  return [
    "You are Miry, Kirill's private Telegram agent running inside his harness.",
    'Handle the Telegram message below. Use shell/tools as needed.',
    'Keep the final answer suitable for Telegram. Be concise unless the task needs a status summary.',
    'The runtime will send your final answer to Telegram and ack the inbound message only after the send succeeds.',
    'If the message starts with /ping-test, reply with the nonce from that message so the Bot E2E probe can verify the round trip.',
    '',
    'Telegram metadata:',
    JSON.stringify(params.meta, null, 2),
    '',
    'Telegram message:',
    params.content,
  ].join('\n')
}

function parseCodexJson(stdout: string) {
  let threadId = ''
  let lastAgentMessage = ''
  for (const line of stdout.split('\n')) {
    if (!line.trim()) continue
    try {
      const event = JSON.parse(line)
      if (event.type === 'thread.started' && event.thread_id) threadId = String(event.thread_id)
      if (event.type === 'item.completed' && event.item?.type === 'agent_message' && event.item?.text) {
        lastAgentMessage = String(event.item.text)
      }
    } catch {}
  }
  return { threadId, lastAgentMessage }
}

function codexArgs(outFile: string, prompt: string, sessionId: string | null, imagePath?: string) {
  const common = ['--json', '-o', outFile, '--skip-git-repo-check']
  if (CODEX_MODEL) common.push('-m', CODEX_MODEL)
  if (BYPASS_HOOK_TRUST) common.push('--dangerously-bypass-hook-trust')
  if (imagePath && existsSync(imagePath)) common.push('-i', imagePath)

  if (sessionId) {
    return ['exec', 'resume', ...common, sessionId, prompt]
  }

  return ['exec', ...common, '--sandbox', CODEX_SANDBOX, prompt]
}

function runCodexOnce(params: TelegramParams, sessionId: string | null): Promise<{ ok: boolean; text: string; threadId: string; stderr: string; stdout: string }> {
  const dir = mkdtempSync(join(tmpdir(), 'miry-codex-'))
  const outFile = join(dir, 'final.txt')
  const prompt = buildPrompt(params)
  const args = codexArgs(outFile, prompt, sessionId, params.meta.image_path)
  const started = Date.now()

  logLine(`codex start msg_id=${params.meta.msg_id} resume=${sessionId ? 'yes' : 'no'} cwd=${CODEX_CWD}`)

  return new Promise((resolve) => {
    const child = spawn(CODEX_BIN, args, {
      cwd: CODEX_CWD,
      env: process.env,
      stdio: ['ignore', 'pipe', 'pipe'],
    })

    let stdout = ''
    let stderr = ''
    let timedOut = false
    const timer = setTimeout(() => {
      timedOut = true
      child.kill('SIGTERM')
    }, CODEX_TIMEOUT_MS)

    child.stdout.on('data', chunk => { stdout += chunk.toString() })
    child.stderr.on('data', chunk => { stderr += chunk.toString() })
    child.on('close', code => {
      clearTimeout(timer)
      const parsed = parseCodexJson(stdout)
      const finalText = existsSync(outFile) ? readFileSync(outFile, 'utf8').trim() : parsed.lastAgentMessage.trim()
      try { unlinkSync(outFile) } catch {}
      const elapsedMs = Date.now() - started
      logLine(`codex done msg_id=${params.meta.msg_id} code=${code} timeout=${timedOut} elapsed_ms=${elapsedMs} thread=${parsed.threadId || sessionId || ''}`)
      if (stderr.trim()) logLine(`codex stderr msg_id=${params.meta.msg_id}: ${stderr.trim().slice(-1000)}`)
      resolve({
        ok: code === 0 && !timedOut,
        text: finalText,
        threadId: parsed.threadId || sessionId || '',
        stderr,
        stdout,
      })
    })
  })
}

async function runCodex(params: TelegramParams) {
  const sessionId = readSessionId()
  let result = await runCodexOnce(params, sessionId)
  if (!result.ok && sessionId) {
    logLine(`codex resume failed msg_id=${params.meta.msg_id}; retrying with a new session`)
    try { unlinkSync(SESSION_ID_PATH) } catch {}
    result = await runCodexOnce(params, null)
  }
  if (result.ok && result.threadId) writeSessionId(result.threadId)
  return result
}

async function sendReply(chatId: string, text: string, replyToMsgId?: string) {
  if (!knownChats.has(Number(chatId))) {
    throw new Error(`rejected: chat_id ${chatId} not in known inbound chats`)
  }
  const safeText = text || 'Miry completed the task but produced no final reply.'
  const chunks = [safeText.substring(0, 4096)]
  for (let i = 4096; i < safeText.length; i += 4096) chunks.push(safeText.substring(i, i + 4096))
  for (const chunk of chunks) {
    await bot.api.sendMessage(Number(chatId), chunk, {
      reply_to_message_id: replyToMsgId ? Number(replyToMsgId) : undefined,
    }).catch(() => bot.api.sendMessage(Number(chatId), chunk))
  }
}

async function processJob(params: TelegramParams) {
  const result = await runCodex(params)
  if (!result.ok) {
    const detail = result.stderr.trim().split('\n').slice(-4).join(' ').slice(0, 500) || 'Codex exited without a final reply.'
    await sendReply(params.meta.chat_id, `Miry/Codex failed; this message has been acked after the failure reply: ${detail}`, params.meta.msg_id)
    logAck(params.meta.msg_id)
    return
  }

  await sendReply(params.meta.chat_id, result.text, params.meta.msg_id)
  logAck(params.meta.msg_id)
}

async function processQueue() {
  if (processing) return
  processing = true
  try {
    while (queue.length > 0) {
      const params = queue.shift()
      if (!params) continue
      try {
        await processJob(params)
      } catch (err: any) {
        logLine(`job failed msg_id=${params.meta.msg_id}: ${err?.message ?? err}`)
      }
    }
  } finally {
    processing = false
  }
}

function enqueue(params: TelegramParams) {
  queue.push(params)
  processQueue().catch(err => logLine(`queue failed: ${err?.message ?? err}`))
}

async function dropPendingTelegramUpdates() {
  await bot.api.deleteWebhook({ drop_pending_updates: true }).catch(err => {
    logLine(`deleteWebhook drop_pending_updates failed: ${err?.message ?? err}`)
  })

  try {
    const updates = await bot.api.getUpdates({ offset: -1, limit: 1, timeout: 0 })
    const lastUpdateId = updates.length > 0 ? updates[updates.length - 1]?.update_id : undefined
    if (typeof lastUpdateId === 'number') {
      await bot.api.getUpdates({ offset: lastUpdateId + 1, limit: 1, timeout: 0 })
      logLine(`dropped pending Telegram updates through update_id=${lastUpdateId}`)
    } else {
      logLine('no pending Telegram updates to drop')
    }
  } catch (err: any) {
    logLine(`getUpdates drop_pending failed: ${err?.message ?? err}`)
  }
}

bot.on('message:text', async (ctx) => {
  if (!ALLOWED.has(ctx.from.id)) return
  knownChats.add(ctx.chat.id)
  bot.api.setMessageReaction(ctx.chat.id, ctx.message.message_id, [{ type: 'emoji', emoji: '👀' }]).catch(() => {})
  const params: TelegramParams = {
    content: withReplyPrefix(ctx.message.text, ctx.message),
    meta: {
      sender: ctx.from.username ?? String(ctx.from.id),
      chat_id: String(ctx.chat.id),
      msg_id: String(ctx.message.message_id),
      ...replyContext(ctx.message),
    },
  }
  logRecv(params)
  enqueue(params)
})

bot.on('message:photo', async (ctx) => {
  if (!ALLOWED.has(ctx.from!.id)) return
  knownChats.add(ctx.chat.id)
  bot.api.setMessageReaction(ctx.chat.id, ctx.message.message_id, [{ type: 'emoji', emoji: '👀' }]).catch(() => {})
  const photos = ctx.message.photo
  if (!photos?.length) return
  const photo = photos[photos.length - 1]
  if (!photo) return
  let imgPath: string
  try {
    const file = await bot.api.getFile(photo.file_id)
    const url = `https://api.telegram.org/file/bot${TOKEN}/${file.file_path}`
    mkdirSync(IMG_DIR, { recursive: true })
    const ext = file.file_path?.split('.').pop() ?? 'jpg'
    imgPath = `${IMG_DIR}/${ctx.message.message_id}.${ext}`
    const resp = await fetch(url)
    writeFileSync(imgPath, Buffer.from(await resp.arrayBuffer()))
  } catch {
    process.stderr.write('photo download failed\n')
    return
  }
  const caption = ctx.message.caption ?? ''
  const params: TelegramParams = {
    content: withReplyPrefix(`[Image saved to ${imgPath}] ${caption}`.trim(), ctx.message),
    meta: {
      sender: ctx.from!.username ?? String(ctx.from!.id),
      chat_id: String(ctx.chat.id),
      msg_id: String(ctx.message.message_id),
      image_path: imgPath,
      ...replyContext(ctx.message),
    },
  }
  logRecv(params)
  enqueue(params)
})

bot.on('message', async (ctx) => {
  if (!ALLOWED.has(ctx.from!.id)) return
  if (ctx.message.text || ctx.message.photo) return
  bot.api.sendMessage(ctx.chat.id, 'Text messages only - images without captions and other media are not supported.', {
    reply_to_message_id: ctx.message.message_id,
  }).catch(() => {})
})

bot.catch((err) => {
  process.stderr.write(`bot error: ${err.message}\n`)
  logLine(`bot error: ${err.message}`)
})

const me = await bot.api.getMe()
process.stderr.write(`miry tg: @${me.username} ready, allowed: [${[...ALLOWED]}]\n`)
logLine(`miry tg ready bot=@${me.username} allowed_count=${ALLOWED.size}`)

await dropPendingTelegramUpdates()

const pending = loadPending()
compactOnStartup(pending)
if (pending.length > 0) {
  process.stderr.write(`miry tg: replaying ${pending.length} unacked message(s)\n`)
  for (const params of pending) enqueue(params)
}

bot.start({ drop_pending_updates: true })
