import { Bot, InputFile } from 'grammy'
import { execFile } from 'child_process'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'
import type { TopicsRegistry } from './topics-registry.js'
import type { IPCServer } from './ipc-server.js'
import { createCommandHandler, launchCommands } from './commands.js'
import { downloadFile } from './file-handler.js'
import type { SessionToProxy, IncomingMessage } from './types.js'

const __dirname = dirname(fileURLToPath(import.meta.url))
const TRANSCRIBE_SCRIPT = resolve(__dirname, '../scripts/transcribe.py')

function transcribeAudio(filePath: string): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile('python3', [TRANSCRIBE_SCRIPT, filePath], { timeout: 60000 }, (err, stdout, stderr) => {
      if (err) {
        reject(new Error(stderr || err.message))
        return
      }
      resolve(stdout.trim())
    })
  })
}

export async function startBot(
  token: string,
  ownerId: number,
  registry: TopicsRegistry,
  ipc: IPCServer,
  publicHost: string = '',
): Promise<Bot> {
  const bot = new Bot(token)
  const handleCommand = createCommandHandler(bot, registry, ipc, publicHost)

  // All messages handler
  bot.on('message', async ctx => {
    const userId = ctx.from?.id
    const chatId = ctx.chat.id
    const threadId = ctx.message.message_thread_id

    console.log(`[Bot] Message from userId=${userId}, chatId=${chatId}, threadId=${threadId}, text="${(ctx.message.text || '').slice(0, 50)}"`)

    // Access control: only owner
    if (userId !== ownerId) return

    // General topic → management commands
    if (!threadId || threadId === 1) {
      return handleCommand(ctx)
    }

    // Auto-register unknown topics
    if (!registry.has(threadId)) {
      const topicName = (ctx.message as any).forum_topic_created?.name
      registry.add(threadId, topicName || `Topic ${threadId}`)
    }

    // Find connected session
    const session = ipc.getSession(threadId)
    const allSessions = ipc.getConnectedSessions()
    console.log(`[Bot] Looking for thread=${threadId}, connected sessions: ${JSON.stringify(allSessions.map(s => s.threadId))}`)

    if (!session) {
      await ctx.reply(
        '⚠️ Нет подключённой сессии для этого топика.\n\n' +
        launchCommands(threadId, publicHost),
        { message_thread_id: threadId, parse_mode: 'HTML' },
      )
      return
    }

    // Build incoming message
    const incoming: IncomingMessage = {
      message_id: ctx.message.message_id,
      thread_id: threadId,
      chat_id: String(chatId),
      text: ctx.message.text || '',
      caption: (ctx.message as any).caption,
      from: {
        id: ctx.from!.id,
        first_name: ctx.from!.first_name,
        username: ctx.from!.username,
      },
    }

    // Handle photos
    if (ctx.message.photo && ctx.message.photo.length > 0) {
      const best = ctx.message.photo[ctx.message.photo.length - 1]
      try {
        const localPath = await downloadFile(bot, best.file_id, ctx.message.message_id)
        incoming.photo = { file_id: best.file_id, file_path: localPath }
      } catch (err: any) {
        console.error('[Bot] Photo download failed:', err.message)
      }
      incoming.text = incoming.caption || '(photo)'
    }

    // Handle documents
    if (ctx.message.document) {
      try {
        const localPath = await downloadFile(
          bot,
          ctx.message.document.file_id,
          ctx.message.message_id,
          ctx.message.document.file_name,
        )
        incoming.document = {
          file_id: ctx.message.document.file_id,
          file_name: ctx.message.document.file_name || 'file',
          file_path: localPath,
        }
      } catch (err: any) {
        console.error('[Bot] Document download failed:', err.message)
      }
      incoming.text = incoming.caption || `(document: ${ctx.message.document.file_name})`
    }

    // Handle voice messages
    if (ctx.message.voice) {
      try {
        const localPath = await downloadFile(bot, ctx.message.voice.file_id, ctx.message.message_id, 'voice.ogg')
        incoming.voice = {
          file_id: ctx.message.voice.file_id,
          file_path: localPath,
          duration: ctx.message.voice.duration,
        }

        console.log(`[Bot] Transcribing voice message (${ctx.message.voice.duration}s)...`)
        const transcription = await transcribeAudio(localPath)
        incoming.voice.transcription = transcription
        incoming.text = transcription || '(voice message, transcription failed)'
        console.log(`[Bot] Transcription: "${transcription.slice(0, 100)}"`)
      } catch (err: any) {
        console.error('[Bot] Voice handling failed:', err.message)
        incoming.text = '(voice message, transcription failed)'
      }
    }

    // Forward to session via IPC
    ipc.sendToSession(threadId, { type: 'incoming_message', message: incoming })
  })

  // Handle outgoing messages from sessions → Telegram
  ipc.onOutgoing(async (msg: SessionToProxy) => {
    try {
      switch (msg.type) {
        case 'send_message': {
          // Chunk long messages
          const chunks = chunkText(msg.text, 4096)
          for (let i = 0; i < chunks.length; i++) {
            await bot.api.sendMessage(msg.chat_id, chunks[i], {
              message_thread_id: msg.thread_id,
              ...(msg.reply_to && i === 0 ? { reply_parameters: { message_id: msg.reply_to } } : {}),
            })
          }
          break
        }

        case 'send_photo':
          await bot.api.sendPhoto(msg.chat_id, new InputFile(msg.file_path), {
            message_thread_id: msg.thread_id,
            caption: msg.caption,
            ...(msg.reply_to ? { reply_parameters: { message_id: msg.reply_to } } : {}),
          })
          break

        case 'send_document':
          await bot.api.sendDocument(msg.chat_id, new InputFile(msg.file_path), {
            message_thread_id: msg.thread_id,
            caption: msg.caption,
            ...(msg.reply_to ? { reply_parameters: { message_id: msg.reply_to } } : {}),
          })
          break

        case 'send_chat_action':
          await bot.api.sendChatAction(msg.chat_id, msg.action as any, {
            message_thread_id: msg.thread_id,
          })
          break

        case 'react':
          await bot.api.setMessageReaction(msg.chat_id, msg.message_id, [
            { type: 'emoji', emoji: msg.emoji as any },
          ])
          break

        case 'edit_message':
          await bot.api.editMessageText(msg.chat_id, msg.message_id, msg.text)
          break
      }
    } catch (err: any) {
      console.error(`[Bot] Outgoing ${msg.type} failed:`, err.message)
    }
  })

  await bot.init()
  console.log(`[Bot] Polling as @${bot.botInfo.username}`)
  bot.start()

  return bot
}

function chunkText(text: string, limit: number): string[] {
  if (text.length <= limit) return [text]
  const chunks: string[] = []
  let rest = text
  while (rest.length > limit) {
    const cut = rest.lastIndexOf('\n', limit)
    const pos = cut > limit / 2 ? cut : limit
    chunks.push(rest.slice(0, pos))
    rest = rest.slice(pos).replace(/^\n+/, '')
  }
  if (rest) chunks.push(rest)
  return chunks
}
