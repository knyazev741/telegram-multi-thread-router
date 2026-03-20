import { mkdirSync, writeFileSync } from 'fs'
import { join, extname } from 'path'
import type { Bot } from 'grammy'

const INBOX_DIR = '/tmp/claude-proxy/inbox'

export async function downloadFile(
  bot: Bot,
  fileId: string,
  messageId: number,
  originalName?: string,
): Promise<string> {
  const file = await bot.api.getFile(fileId)
  if (!file.file_path) throw new Error('No file_path from Telegram')

  const token = process.env.BOT_TOKEN!
  const url = `https://api.telegram.org/file/bot${token}/${file.file_path}`
  const ext = extname(file.file_path) || (originalName ? extname(originalName) : '.bin')
  const filename = originalName
    ? `${messageId}_${originalName}`
    : `${messageId}${ext}`
  const localPath = join(INBOX_DIR, filename)

  mkdirSync(INBOX_DIR, { recursive: true })

  const response = await fetch(url)
  const buffer = Buffer.from(await response.arrayBuffer())
  writeFileSync(localPath, buffer)

  console.log(`[Files] Downloaded: ${localPath} (${buffer.length} bytes)`)
  return localPath
}
