import { config } from 'dotenv'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'
import { TopicsRegistry } from './topics-registry.js'
import { IPCServer } from './ipc-server.js'
import { startBot } from './bot.js'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Load .env from project root
config({ path: resolve(__dirname, '../../.env') })

const BOT_TOKEN = process.env.BOT_TOKEN
const OWNER_USER_ID = process.env.OWNER_USER_ID
const SOCKET_DIR = process.env.SOCKET_DIR || '/tmp/claude-proxy'

if (!BOT_TOKEN) {
  console.error('BOT_TOKEN is required in .env')
  process.exit(1)
}

if (!OWNER_USER_ID) {
  console.error('OWNER_USER_ID is required in .env')
  process.exit(1)
}

async function main() {
  console.log('[Proxy] Starting Telegram Multi-Thread Router...')

  // 1. Topics registry
  const registry = new TopicsRegistry(resolve(__dirname, '../data'))

  // 2. IPC server for sessions
  const ipc = new IPCServer(SOCKET_DIR)

  // 3. Start bot (long polling)
  const bot = await startBot(BOT_TOKEN!, Number(OWNER_USER_ID), registry, ipc)

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
  console.log(`[Proxy] Socket dir: ${SOCKET_DIR}`)
  console.log(`[Proxy] Owner: ${OWNER_USER_ID}`)
}

main().catch(err => {
  console.error('[Proxy] Fatal:', err)
  process.exit(1)
})
