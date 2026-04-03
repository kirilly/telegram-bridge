#!/usr/bin/env bun
/**
 * Minimal Telegram channel server for Claude Code.
 * Polls Telegram Bot API, pushes messages into the session via MCP channel notifications.
 * Claude replies via the `reply` tool.
 *
 * ~80 lines. Replaces the 995-line official plugin.
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { ListToolsRequestSchema, CallToolRequestSchema } from '@modelcontextprotocol/sdk/types.js'
import { Bot } from 'grammy'

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
const bot = new Bot(TOKEN)

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

const mcp = new Server(
  { name: 'tg', version: '0.1.0' },
  {
    capabilities: {
      experimental: { 'claude/channel': {} },
      tools: {},
    },
    instructions: [
      'Telegram messages arrive as <channel source="tg" sender="..." chat_id="..." msg_id="...">.',
      'When present, reply metadata is included as reply_to_msg_id and reply_to_preview.',
      'Reply with the reply tool, passing chat_id and optionally reply_to_msg_id from the tag.',
      'Follow the dispatch rules from the tg-dispatch skill: classify as quick/light/medium/heavy, spawn agents for non-trivial work.',
    ].join(' '),
  },
)

// Reply tool — Claude calls this to send messages back to Telegram
mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [{
    name: 'reply',
    description: 'Send a message to a Telegram chat',
    inputSchema: {
      type: 'object' as const,
      properties: {
        chat_id: { type: 'string', description: 'Telegram chat ID from the channel tag' },
        text: { type: 'string', description: 'Message text to send' },
        reply_to_msg_id: { type: 'string', description: 'Optional: message ID to reply to' },
      },
      required: ['chat_id', 'text'],
    },
  }],
}))

mcp.setRequestHandler(CallToolRequestSchema, async (req) => {
  if (req.params.name === 'reply') {
    const { chat_id, text, reply_to_msg_id } = req.params.arguments as {
      chat_id: string; text: string; reply_to_msg_id?: string
    }
    const chunks = [text.substring(0, 4096)]
    for (let i = 4096; i < text.length; i += 4096) chunks.push(text.substring(i, i + 4096))
    for (const chunk of chunks) {
      await bot.api.sendMessage(Number(chat_id), chunk, {
        reply_to_message_id: reply_to_msg_id ? Number(reply_to_msg_id) : undefined,
      }).catch(() => {
        // Retry without reply_to in case the original message was deleted
        return bot.api.sendMessage(Number(chat_id), chunk)
      })
    }
    return { content: [{ type: 'text', text: `sent ${text.length} chars to ${chat_id}` }] }
  }
  throw new Error(`unknown tool: ${req.params.name}`)
})

// Connect MCP over stdio
await mcp.connect(new StdioServerTransport())

// Poll Telegram, push allowed messages into Claude session
bot.on('message:text', async (ctx) => {
  if (!ALLOWED.has(ctx.from.id)) return
  // Acknowledge receipt — reaction added after notification to avoid blocking
  bot.api.setMessageReaction(ctx.chat.id, ctx.message.message_id, [{ type: 'emoji', emoji: '👀' }]).catch(() => {})
  await mcp.notification({
    method: 'notifications/claude/channel',
    params: {
      content: withReplyPrefix(ctx.message.text, ctx.message),
      meta: {
        sender: ctx.from.username ?? String(ctx.from.id),
        chat_id: String(ctx.chat.id),
        msg_id: String(ctx.message.message_id),
        ...replyContext(ctx.message),
      },
    },
  })
})

// Handle photos — download and save locally for Claude to read
bot.on('message:photo', async (ctx) => {
  if (!ALLOWED.has(ctx.from!.id)) return
  bot.api.setMessageReaction(ctx.chat.id, ctx.message.message_id, [{ type: 'emoji', emoji: '👀' }]).catch(() => {})
  const photo = ctx.message.photo[ctx.message.photo.length - 1] // largest size
  const file = await bot.api.getFile(photo.file_id)
  const url = `https://api.telegram.org/file/bot${TOKEN}/${file.file_path}`
  const imgDir = '/tmp/tg-images'
  const { mkdirSync, writeFileSync } = await import('fs')
  mkdirSync(imgDir, { recursive: true })
  const ext = file.file_path?.split('.').pop() ?? 'jpg'
  const imgPath = `${imgDir}/${ctx.message.message_id}.${ext}`
  const resp = await fetch(url)
  writeFileSync(imgPath, Buffer.from(await resp.arrayBuffer()))
  const caption = ctx.message.caption ?? ''
  await mcp.notification({
    method: 'notifications/claude/channel',
    params: {
      content: withReplyPrefix(`[Image saved to ${imgPath}] ${caption}`.trim(), ctx.message),
      meta: {
        sender: ctx.from!.username ?? String(ctx.from!.id),
        chat_id: String(ctx.chat.id),
        msg_id: String(ctx.message.message_id),
        image_path: imgPath,
        ...replyContext(ctx.message),
      },
    },
  })
})

// Catch-all for other message types to avoid silent drops
bot.on('message', async (ctx) => {
  if (!ALLOWED.has(ctx.from!.id)) return
  if (ctx.message.text || ctx.message.photo) return // already handled
  bot.api.sendMessage(ctx.chat.id, 'Text messages only — images without captions and other media are not supported.', {
    reply_to_message_id: ctx.message.message_id,
  }).catch(() => {})
})

// Catch unhandled errors to prevent crashes
bot.catch((err) => {
  process.stderr.write(`bot error: ${err.message}\n`)
})

const me = await bot.api.getMe()
process.stderr.write(`tg channel: @${me.username} ready, allowed: [${[...ALLOWED]}]\n`)
bot.start()
