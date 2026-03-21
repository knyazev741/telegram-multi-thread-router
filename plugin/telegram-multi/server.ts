#!/usr/bin/env bun
/**
 * Telegram Multi-Thread Channel for Claude Code.
 *
 * Fork of the official telegram plugin. Instead of doing its own long polling,
 * connects to a central Proxy via Unix socket. Each instance is bound to a
 * specific forum topic (thread_id).
 *
 * The Proxy handles all Telegram communication; this plugin just bridges
 * IPC ↔ MCP for a single Claude Code session.
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from '@modelcontextprotocol/sdk/types.js'
import net from 'net'
import { readFileSync, statSync, realpathSync } from 'fs'
import { homedir } from 'os'
import { join, extname, sep } from 'path'

// ── Config ──────────────────────────────────────────────────────────────────

const STATE_DIR = join(homedir(), '.claude', 'channels', 'telegram-multi')
const ENV_FILE = join(STATE_DIR, '.env')

// Load channel .env (env vars take precedence)
try {
  for (const line of readFileSync(ENV_FILE, 'utf8').split('\n')) {
    const m = line.match(/^(\w+)=(.*)$/)
    if (m && process.env[m[1]] === undefined) process.env[m[1]] = m[2]
  }
} catch {}

const THREAD_ID = Number(process.env.TELEGRAM_THREAD_ID)
const PROXY_HOST = process.env.TELEGRAM_PROXY_HOST || '127.0.0.1'
const PROXY_PORT = Number(process.env.TELEGRAM_PROXY_PORT || 9600)
const AUTH_TOKEN = process.env.TELEGRAM_AUTH_TOKEN || ''
const CHAT_ID = process.env.TELEGRAM_CHAT_ID || ''

if (!THREAD_ID) {
  process.stderr.write(
    `telegram-multi channel: TELEGRAM_THREAD_ID required\n` +
    `  set via env: TELEGRAM_THREAD_ID=42 claude --dangerously-load-development-channels plugin:telegram-multi@<marketplace>\n`,
  )
  process.exit(1)
}

if (!AUTH_TOKEN) {
  process.stderr.write(
    `telegram-multi channel: TELEGRAM_AUTH_TOKEN required\n` +
    `  set in ${ENV_FILE} or via env\n`,
  )
  process.exit(1)
}

// ── State ───────────────────────────────────────────────────────────────────

let proxySocket: net.Socket | null = null
let connected = false
let chatId = CHAT_ID
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let heartbeatTimer: ReturnType<typeof setInterval> | null = null

const MAX_CHUNK_LIMIT = 4096
const MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
const PHOTO_EXTS = new Set(['.jpg', '.jpeg', '.png', '.gif', '.webp'])

// ── Security ────────────────────────────────────────────────────────────────

function assertSendable(f: string): void {
  let real: string
  try { real = realpathSync(f) } catch { return }
  const stateReal = (() => { try { return realpathSync(STATE_DIR) } catch { return STATE_DIR } })()
  if (real.startsWith(stateReal + sep)) {
    throw new Error(`refusing to send channel state: ${f}`)
  }
}

// ── Text chunking ───────────────────────────────────────────────────────────

function chunk(text: string, limit: number): string[] {
  if (text.length <= limit) return [text]
  const out: string[] = []
  let rest = text
  while (rest.length > limit) {
    const nl = rest.lastIndexOf('\n', limit)
    const cut = nl > limit / 2 ? nl : limit
    out.push(rest.slice(0, cut))
    rest = rest.slice(cut).replace(/^\n+/, '')
  }
  if (rest) out.push(rest)
  return out
}

// ── IPC to Proxy ────────────────────────────────────────────────────────────

function sendToProxy(msg: Record<string, unknown>): void {
  if (!proxySocket || !connected) {
    process.stderr.write(`telegram-multi: not connected to proxy, dropping message\n`)
    return
  }
  proxySocket.write(JSON.stringify(msg) + '\n')
}

function connectToProxy(): void {
  if (proxySocket) {
    proxySocket.removeAllListeners()
    proxySocket.destroy()
  }

  process.stderr.write(`telegram-multi: connecting to proxy at ${PROXY_HOST}:${PROXY_PORT}...\n`)

  proxySocket = net.createConnection({ host: PROXY_HOST, port: PROXY_PORT }, () => {
    connected = true
    // TCP keepalive — prevent idle timeout drops
    proxySocket!.setKeepAlive(true, 15000)
    proxySocket!.setNoDelay(true)

    process.stderr.write(`telegram-multi: connected to proxy, registering thread=${THREAD_ID}\n`)

    // First message must include auth_token
    sendToProxy({
      type: 'register',
      thread_id: THREAD_ID,
      chat_id: chatId,
      auth_token: AUTH_TOKEN,
    })

    // Heartbeat every 30s to keep connection alive
    if (heartbeatTimer) clearInterval(heartbeatTimer)
    heartbeatTimer = setInterval(() => {
      if (connected) {
        try { proxySocket!.write('{"type":"ping"}\n') } catch {}
      }
    }, 30000)
  })

  let buffer = ''
  proxySocket.on('data', data => {
    buffer += data.toString()
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (!line.trim()) continue
      try {
        const msg = JSON.parse(line)
        handleProxyMessage(msg)
      } catch (e) {
        process.stderr.write(`telegram-multi: invalid JSON from proxy: ${e}\n`)
      }
    }
  })

  proxySocket.on('close', () => {
    connected = false
    if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null }
    process.stderr.write(`telegram-multi: disconnected from proxy, reconnecting in 3s...\n`)
    scheduleReconnect()
  })

  proxySocket.on('error', err => {
    connected = false
    process.stderr.write(`telegram-multi: proxy connection error: ${err.message}\n`)
    scheduleReconnect()
  })
}

function scheduleReconnect(): void {
  if (reconnectTimer) return
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    connectToProxy()
  }, 3000)
}

// ── Handle messages from Proxy ──────────────────────────────────────────────

function handleProxyMessage(msg: any): void {
  switch (msg.type) {
    case 'registered':
      chatId = msg.chat_id || chatId
      process.stderr.write(`telegram-multi: registered for thread=${msg.thread_id}\n`)
      break

    case 'incoming_message': {
      const m = msg.message
      if (m.thread_id !== THREAD_ID) return // extra safety filter

      const text = m.text || m.caption || ''
      const meta: Record<string, string> = {
        chat_id: String(m.chat_id),
        ...(m.message_id != null ? { message_id: String(m.message_id) } : {}),
        user: m.from?.username ?? String(m.from?.id),
        user_id: String(m.from?.id),
        ts: new Date().toISOString(),
        thread_id: String(THREAD_ID),
      }

      if (m.photo?.file_path) {
        meta.image_path = m.photo.file_path
      }
      if (m.document?.file_path) {
        meta.document_path = m.document.file_path
        meta.document_name = m.document.file_name || 'file'
      }
      if (m.voice) {
        meta.voice = 'true'
        meta.voice_duration = String(m.voice.duration)
        if (m.voice.file_path) meta.voice_path = m.voice.file_path
      }

      void mcp.notification({
        method: 'notifications/claude/channel',
        params: { content: text, meta },
      })
      break
    }
  }
}

// ── MCP Server ──────────────────────────────────────────────────────────────

const mcp = new Server(
  { name: 'telegram-multi', version: '1.0.0' },
  {
    capabilities: { tools: {}, experimental: { 'claude/channel': {} } },
    instructions: [
      'The sender reads Telegram, not this session. Anything you want them to see must go through the reply tool — your transcript output never reaches their chat.',
      '',
      `This session is bound to Telegram forum topic (thread_id: ${THREAD_ID}). Messages arrive as <channel source="telegram-multi" chat_id="..." message_id="..." thread_id="${THREAD_ID}" user="..." ts="...">. If the tag has an image_path attribute, Read that file — it is a photo the sender attached. If it has document_path, read that file.`,
      '',
      'Reply with the reply tool — pass chat_id back. Use reply_to (set to a message_id) only when replying to an earlier message; the latest message doesn\'t need a quote-reply, omit reply_to for normal responses.',
      '',
      'reply accepts file paths (files: ["/abs/path.png"]) for attachments. Use react to add emoji reactions, and edit_message to update a message you previously sent.',
      '',
      "Telegram's Bot API exposes no history or search — you only see messages as they arrive.",
      '',
      '## Response strategy: one-step vs multi-step',
      '',
      'Before doing any work, decide whether the task is ONE-STEP or MULTI-STEP.',
      '',
      '**One-step** = you can answer immediately without tool calls or with one quick lookup (questions, short explanations, simple checks).',
      'Action: do the work, then send ONE reply with the result.',
      '',
      'Example — user asks "какая версия ноды на серваке?":',
      '1. Run `node -v` via Bash',
      '2. reply({ chat_id, text: "v20.11.0" })',
      '',
      '**Multi-step** = requires multiple tool calls, code changes, research, deployment, or anything that takes noticeable time.',
      'Action: FIRST send a short acknowledgement so the user knows you started, THEN do the work, THEN send the final result.',
      '',
      'Example — user asks "обнови зависимости и задеплой":',
      '1. reply({ chat_id, text: "Понял, обновляю зависимости и деплою — отпишусь когда будет готово." })',
      '2. ... run npm update, commit, push, deploy ...',
      '3. reply({ chat_id, text: "Готово. Обновил X, Y, Z. Задеплоил, сервис работает." })',
      '',
      'The acknowledgement must be SHORT (1 sentence). Never skip it for multi-step tasks — the user needs to know you received the request and started working.',
    ].join('\n'),
  },
)

mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'reply',
      description:
        'Reply on Telegram in the current forum topic. Pass chat_id from the inbound message. Optionally pass reply_to (message_id) for threading, and files (absolute paths) to attach.',
      inputSchema: {
        type: 'object' as const,
        properties: {
          chat_id: { type: 'string' as const },
          text: { type: 'string' as const },
          reply_to: {
            type: 'string' as const,
            description: 'Message ID to thread under.',
          },
          files: {
            type: 'array' as const,
            items: { type: 'string' as const },
            description: 'Absolute file paths to attach. Images as photos; others as documents. Max 50MB each.',
          },
        },
        required: ['chat_id', 'text'],
      },
    },
    {
      name: 'react',
      description: 'Add an emoji reaction to a Telegram message.',
      inputSchema: {
        type: 'object' as const,
        properties: {
          chat_id: { type: 'string' as const },
          message_id: { type: 'string' as const },
          emoji: { type: 'string' as const },
        },
        required: ['chat_id', 'message_id', 'emoji'],
      },
    },
    {
      name: 'edit_message',
      description: 'Edit a message the bot previously sent.',
      inputSchema: {
        type: 'object' as const,
        properties: {
          chat_id: { type: 'string' as const },
          message_id: { type: 'string' as const },
          text: { type: 'string' as const },
        },
        required: ['chat_id', 'message_id', 'text'],
      },
    },
  ],
}))

mcp.setRequestHandler(CallToolRequestSchema, async req => {
  const args = (req.params.arguments ?? {}) as Record<string, unknown>
  try {
    switch (req.params.name) {
      case 'reply': {
        const chat_id = args.chat_id as string
        const text = args.text as string
        const reply_to = args.reply_to != null ? Number(args.reply_to) : undefined
        const files = (args.files as string[] | undefined) ?? []

        for (const f of files) {
          assertSendable(f)
          const st = statSync(f)
          if (st.size > MAX_ATTACHMENT_BYTES) {
            throw new Error(`file too large: ${f} (${(st.size / 1024 / 1024).toFixed(1)}MB, max 50MB)`)
          }
        }

        // Send text chunks
        const chunks = chunk(text, MAX_CHUNK_LIMIT)
        for (const c of chunks) {
          sendToProxy({
            type: 'send_message',
            chat_id,
            thread_id: THREAD_ID,
            text: c,
            reply_to,
            parse_mode: 'Markdown',
          })
        }

        // Send files
        for (const f of files) {
          const ext = extname(f).toLowerCase()
          if (PHOTO_EXTS.has(ext)) {
            sendToProxy({
              type: 'send_photo',
              chat_id,
              thread_id: THREAD_ID,
              file_path: f,
              reply_to,
            })
          } else {
            sendToProxy({
              type: 'send_document',
              chat_id,
              thread_id: THREAD_ID,
              file_path: f,
              reply_to,
            })
          }
        }

        return { content: [{ type: 'text', text: `sent (${chunks.length} chunk(s), ${files.length} file(s))` }] }
      }

      case 'react': {
        sendToProxy({
          type: 'react',
          chat_id: args.chat_id as string,
          message_id: Number(args.message_id),
          emoji: args.emoji as string,
        })
        return { content: [{ type: 'text', text: 'reacted' }] }
      }

      case 'edit_message': {
        sendToProxy({
          type: 'edit_message',
          chat_id: args.chat_id as string,
          message_id: Number(args.message_id),
          text: args.text as string,
        })
        return { content: [{ type: 'text', text: 'edited' }] }
      }

      default:
        return { content: [{ type: 'text', text: `unknown tool: ${req.params.name}` }], isError: true }
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return { content: [{ type: 'text', text: `${req.params.name} failed: ${msg}` }], isError: true }
  }
})

// ── Start ───────────────────────────────────────────────────────────────────

await mcp.connect(new StdioServerTransport())
connectToProxy()
