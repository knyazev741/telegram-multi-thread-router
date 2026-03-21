import { config } from 'dotenv'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'
import { randomBytes } from 'crypto'
import { TopicsRegistry } from './topics-registry.js'
import { IPCServer } from './ipc-server.js'
import { startBot } from './bot.js'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Load .env from project root
config({ path: resolve(__dirname, '../../.env') })

const BOT_TOKEN = process.env.BOT_TOKEN
const OWNER_USER_ID = process.env.OWNER_USER_ID
const IPC_PORT = Number(process.env.IPC_PORT || 9600)
const AUTH_TOKEN = process.env.AUTH_TOKEN || randomBytes(32).toString('hex')
const PUBLIC_HOST = process.env.PUBLIC_HOST || ''
const PLUGIN_NAME = process.env.PLUGIN_NAME || 'telegram-multi@telegram-multi-thread'
const GROUP_CHAT_ID = process.env.GROUP_CHAT_ID ? Number(process.env.GROUP_CHAT_ID) : undefined
const GROUP_THREAD_ID = process.env.GROUP_THREAD_ID ? Number(process.env.GROUP_THREAD_ID) : 1

if (!BOT_TOKEN) {
  console.error('BOT_TOKEN is required in .env')
  process.exit(1)
}

if (!OWNER_USER_ID) {
  console.error('OWNER_USER_ID is required in .env')
  process.exit(1)
}

if (!process.env.AUTH_TOKEN) {
  console.warn(`[Proxy] WARNING: AUTH_TOKEN not set in .env, generated random: ${AUTH_TOKEN}`)
  console.warn(`[Proxy] Add this to .env: AUTH_TOKEN=${AUTH_TOKEN}`)
}

async function main() {
  console.log('[Proxy] Starting Telegram Multi-Thread Router...')

  // 1. Topics registry
  const registry = new TopicsRegistry(resolve(__dirname, '../data'))

  // 2. IPC server (TCP for remote sessions)
  const ipc = new IPCServer(IPC_PORT, AUTH_TOKEN)

  // 3. Start bot (long polling)
  const bot = await startBot(BOT_TOKEN!, Number(OWNER_USER_ID), registry, ipc, PUBLIC_HOST, PLUGIN_NAME, GROUP_CHAT_ID, GROUP_THREAD_ID)

  // 4. Graceful shutdown
  const shutdown = () => {
    console.log('[Proxy] Shutting down...')
    bot.stop()
    ipc.closeAll()
    process.exit(0)
  }

  process.on('SIGINT', shutdown)
  process.on('SIGTERM', shutdown)

  console.log('[Proxy] Ready. Waiting for sessions to connect...')
  console.log(`[Proxy] IPC TCP port: ${IPC_PORT}`)
  console.log(`[Proxy] Owner: ${OWNER_USER_ID}`)
  if (GROUP_CHAT_ID) {
    console.log(`[Proxy] Group chat: ${GROUP_CHAT_ID} (thread: ${GROUP_THREAD_ID})`)
  }
}

main().catch(err => {
  console.error('[Proxy] Fatal:', err)
  process.exit(1)
})
