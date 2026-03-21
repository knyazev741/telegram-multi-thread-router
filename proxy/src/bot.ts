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

function transcribeAudio(filePath: string, durationSec: number): Promise<string> {
  // ~10s processing per 1s audio on CPU with medium model, plus 30s for model load
  const timeoutMs = Math.max(60000, (durationSec * 10 + 30) * 1000)
  return new Promise((resolve, reject) => {
    execFile('python3', [TRANSCRIBE_SCRIPT, filePath], { timeout: timeoutMs }, (err, stdout, stderr) => {
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
  pluginName: string = 'telegram-multi@telegram-multi-thread',
): Promise<Bot> {
  const bot = new Bot(token)
  const handleCommand = createCommandHandler(bot, registry, ipc, publicHost, pluginName)

  // Typing indicators per thread — cleared when session responds
  const typingIntervals = new Map<number, ReturnType<typeof setInterval>>()

  function startTyping(chatId: string | number, threadId: number) {
    stopTyping(threadId)
    // Send immediately, then every 4s (Telegram typing expires after 5s)
    const send = () => {
      bot.api.sendChatAction(chatId, 'typing', { message_thread_id: threadId })
        .catch(err => console.error('[Bot] Typing failed:', err.message))
    }
    send()
    typingIntervals.set(threadId, setInterval(send, 4000))
  }

  function stopTyping(threadId: number) {
    const interval = typingIntervals.get(threadId)
    if (interval) {
      clearInterval(interval)
      typingIntervals.delete(threadId)
    }
  }

  // All messages handler
  bot.on('message', async ctx => {
    const userId = ctx.from?.id
    const chatId = ctx.chat.id
    const threadId = ctx.message.message_thread_id

    console.log(`[Bot] Message from userId=${userId}, chatId=${chatId}, threadId=${threadId}, text="${(ctx.message.text || '').slice(0, 50)}"`)

    // Access control: only owner
    if (userId !== ownerId) return

    // General topic → management commands only
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
        launchCommands(threadId, publicHost, pluginName),
        { message_thread_id: threadId, parse_mode: 'HTML' },
      )
      return
    }

    // Start typing while we process (transcription etc.)
    startTyping(chatId, threadId)

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

    // Handle voice messages — transcribe in background, don't block other threads
    if (ctx.message.voice) {
      try {
        const localPath = await downloadFile(bot, ctx.message.voice.file_id, ctx.message.message_id, 'voice.ogg')
        const voiceData = {
          file_id: ctx.message.voice.file_id,
          file_path: localPath,
          duration: ctx.message.voice.duration,
        }

        // Transcribe in background — only send to session when transcription is ready
        console.log(`[Bot] Transcribing voice message (${ctx.message.voice.duration}s) in background...`)
        transcribeAudio(localPath, ctx.message.voice.duration).then(transcription => {
          console.log(`[Bot] Transcription: "${transcription.slice(0, 100)}"`)
          stopTyping(threadId)
          const msg: IncomingMessage = {
            ...incoming,
            text: transcription || '(voice message, transcription failed)',
            voice: { ...voiceData, transcription },
          }
          const sent = ipc.sendToSession(threadId, { type: 'incoming_message', message: msg })
          console.log(`[Bot] sendToSession thread=${threadId} (transcribed voice): ${sent ? 'OK' : 'FAILED'}`)
          bot.api.setMessageReaction(chatId, ctx.message.message_id, [
            { type: 'emoji', emoji: '👀' as any },
          ]).catch(err => console.error('[Bot] Reaction failed:', err.message))
        }).catch(err => {
          console.error('[Bot] Transcription failed:', err.message)
          stopTyping(threadId)
          const msg: IncomingMessage = {
            ...incoming,
            text: '(voice message, transcription failed)',
            voice: voiceData,
          }
          ipc.sendToSession(threadId, { type: 'incoming_message', message: msg })
        })

        return // Handled asynchronously — skip the common send below
      } catch (err: any) {
        console.error('[Bot] Voice download failed:', err.message)
        incoming.text = '(voice message, download failed)'
      }
    }

    // Forward to session via IPC
    const sent = ipc.sendToSession(threadId, { type: 'incoming_message', message: incoming })
    console.log(`[Bot] sendToSession thread=${threadId}: ${sent ? 'OK' : 'FAILED'}`)

    // 👀 = delivered to Claude session (after sendToSession, not before)
    bot.api.setMessageReaction(chatId, ctx.message.message_id, [
      { type: 'emoji', emoji: '👀' as any },
    ]).catch(err => console.error('[Bot] Reaction failed:', err.message))
  })

  // Handle outgoing messages from sessions → Telegram
  ipc.onOutgoing(async (msg: SessionToProxy) => {
    // Stop typing when session sends any visible response
    if ('thread_id' in msg && msg.thread_id) {
      stopTyping(msg.thread_id)
    }

    try {
      switch (msg.type) {
        case 'send_message': {
          const htmlText = mdToHtml(msg.text)
          const chunks = chunkText(htmlText, 4096)
          for (let i = 0; i < chunks.length; i++) {
            await bot.api.sendMessage(msg.chat_id, chunks[i], {
              message_thread_id: msg.thread_id,
              parse_mode: 'HTML',
              ...(msg.reply_to && i === 0 ? { reply_parameters: { message_id: msg.reply_to } } : {}),
            }).catch(async () => {
              // Fallback: send without formatting if HTML parsing fails
              await bot.api.sendMessage(msg.chat_id, msg.text, {
                message_thread_id: msg.thread_id,
                ...(msg.reply_to && i === 0 ? { reply_parameters: { message_id: msg.reply_to } } : {}),
              })
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

/** Convert common Markdown to Telegram HTML */
function mdToHtml(text: string): string {
  // Escape HTML entities first
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // Code blocks: ```lang\n...\n``` → <pre><code>...</code></pre>
  html = html.replace(/```(?:\w*)\n([\s\S]*?)```/g, (_m, code) =>
    `<pre><code>${code.replace(/<\/?[a-z][^>]*>/gi, '')}</code></pre>`)

  // Inline code: `...` → <code>...</code>
  html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>')

  // Bold: **...** → <b>...</b>
  html = html.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')

  // Italic: *...* → <i>...</i> (but not inside words with asterisks)
  html = html.replace(/(?<!\w)\*([^\s*](?:.*?[^\s*])?)\*(?!\w)/g, '<i>$1</i>')

  // Strikethrough: ~~...~~ → <s>...</s>
  html = html.replace(/~~(.+?)~~/g, '<s>$1</s>')

  return html
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
