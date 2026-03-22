import { Bot, InputFile } from 'grammy'
import { execFile, exec } from 'child_process'
import { promisify } from 'util'

const execAsync = promisify(exec)
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'
import type { TopicsRegistry } from './topics-registry.js'
import type { IPCServer } from './ipc-server.js'
import { createCommandHandler, launchCommands } from './commands.js'
import { downloadFile } from './file-handler.js'
import type { SessionToProxy, IncomingMessage } from './types.js'
import { ChatHistory } from './chat-history.js'

// Claude slash commands that should be forwarded directly to tmux (no AI processing)
const TERMINAL_COMMANDS = ['/clear', '/compact', '/reset', '/doctor', '/logout']

function sendToTmux(server: string | undefined, sessionName: string, keys: string): Promise<void> {
  const escaped = keys.replace(/'/g, "'\\''")
  let cmd: string
  switch (server) {
    case 'personal':
      cmd = `tmux send-keys -t '${sessionName}' '${escaped}' Enter`
      break
    case 'business':
      cmd = `ssh business-server-full "tmux send-keys -t '${sessionName}' '${escaped}' Enter"`
      break
    case 'mac':
      cmd = `ssh mac "/opt/homebrew/bin/tmux send-keys -t '${sessionName}' '${escaped}' Enter"`
      break
    default:
      return Promise.reject(new Error(`Нет информации о сервере для этого треда`))
  }
  return new Promise((resolve, reject) => {
    exec(cmd, { timeout: 10000 }, (err) => err ? reject(err) : resolve())
  })
}

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
  groupChatId?: number,
  groupThreadId: number = 1,
  dataDir: string = './data',
): Promise<Bot> {
  const bot = new Bot(token)
  const handleCommand = createCommandHandler(bot, registry, ipc, publicHost, pluginName)

  // Persistent chat history (SQLite)
  const chatHistory = new ChatHistory(dataDir)

  // Map IPC thread → tmux session name (populated on session registration)
  const tmuxSessionNames = new Map<number, string>()
  // Default: group chat session
  tmuxSessionNames.set(groupThreadId, 'ks-agent')

  // Forward slash-command directly to tmux session (no AI involved)
  async function forwardCommand(tmuxSession: string, command: string): Promise<{ ok: boolean; error?: string }> {
    try {
      // Check tmux session exists
      await execAsync(`tmux has-session -t ${tmuxSession}`)
      // Send the command as keystrokes
      await execAsync(`tmux send-keys -t ${tmuxSession} ${JSON.stringify(command)} Enter`)
      return { ok: true }
    } catch (err: any) {
      return { ok: false, error: err.message }
    }
  }

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

    // Group chat mode: handle messages from the configured group
    if (groupChatId && chatId === groupChatId) {
      const botUsername = bot.botInfo.username
      const text = ctx.message.text || ctx.message.caption || ''
      const fromName = ctx.from?.username || ctx.from?.first_name || `user${userId}`

      // Save ALL messages to persistent DB (before filtering)
      chatHistory.save({
        chat_id: chatId,
        message_id: ctx.message.message_id,
        thread_id: threadId,
        user_id: userId!,
        username: ctx.from?.username,
        first_name: ctx.from?.first_name || '',
        text,
        has_photo: !!(ctx.message.photo && ctx.message.photo.length > 0),
        has_document: !!ctx.message.document,
        has_voice: !!(ctx.message.voice || (ctx.message as any).video_note),
      })

      // Background-transcribe voice/video_note for ALL messages (updates DB)
      if (ctx.message.voice || (ctx.message as any).video_note) {
        const media = ctx.message.voice || (ctx.message as any).video_note
        const msgId = ctx.message.message_id
        const label = ctx.message.voice ? 'голосовое' : 'кружочек'
        const ext = ctx.message.voice ? 'voice.ogg' : 'video_note.mp4'
        downloadFile(bot, media.file_id, msgId, ext)
          .then(localPath => transcribeAudio(localPath, media.duration))
          .then(transcription => {
            chatHistory.updateText(chatId, msgId, `[${label}] ${transcription}`)
          })
          .catch(err => console.error(`[Bot] Background ${label} transcription failed:`, err.message))
      }

      // Slash-commands from owner → forward to tmux session directly (no AI)
      if (userId === ownerId && text.startsWith('/')) {
        const parts = text.split(/\s+/)
        const cmd = parts[0] // e.g. /clear, /compact

        // Skip Telegram's built-in commands like /start@bot
        if (cmd.includes('@') && !cmd.includes(`@${botUsername}`)) return
        const cleanCmd = cmd.replace(`@${botUsername}`, '')

        // Determine target tmux session
        let targetSession = tmuxSessionNames.get(groupThreadId) || 'ks-agent'
        let targetThreadId: number | undefined

        // Check if second arg is a thread_id: /clear 12345
        if (parts.length > 1 && /^\d+$/.test(parts[1])) {
          targetThreadId = Number(parts[1])
          targetSession = tmuxSessionNames.get(targetThreadId) || `tg-${targetThreadId}`
        }

        // Build the command to send (slash command + remaining args, minus thread_id if it was routing)
        const cmdArgs = targetThreadId
          ? parts.slice(2).join(' ')
          : parts.slice(1).join(' ')
        const fullCmd = cmdArgs ? `${cleanCmd} ${cmdArgs}` : cleanCmd

        console.log(`[Bot] Command ${fullCmd} → tmux:${targetSession}`)
        const result = await forwardCommand(targetSession, fullCmd)

        const emoji = result.ok ? '👌' : '❌'
        await bot.api.setMessageReaction(chatId, ctx.message.message_id, [
          { type: 'emoji', emoji: emoji as any },
        ]).catch(() => {})

        if (!result.ok) {
          await bot.api.sendMessage(chatId, `❌ Не удалось: ${result.error}`, {
            message_thread_id: threadId,
            reply_parameters: { message_id: ctx.message.message_id },
          }).catch(() => {})
        }
        return
      }

      // Check if bot is @mentioned or message is a reply to bot
      const isMentioned = botUsername && text.includes(`@${botUsername}`)
      const replyFromId = ctx.message.reply_to_message?.from?.id
      const isReplyToBot = replyFromId === bot.botInfo.id

      console.log(`[Bot] Group check: mentioned=${!!isMentioned}, replyToBot=${isReplyToBot} (replyFrom=${replyFromId}, botId=${bot.botInfo.id})`)

      if (!isMentioned && !isReplyToBot) return // Ignore messages not directed at bot

      // Single session serves entire group chat (thread=groupThreadId for IPC routing)
      const ipcThread = groupThreadId
      if (!registry.has(ipcThread)) {
        registry.add(ipcThread, 'group-chat')
      }

      const session = ipc.getSession(ipcThread)
      if (!session) {
        console.log(`[Bot] No session for group (ipc thread=${ipcThread})`)
        return // Silently ignore if no session — don't spam the group
      }

      startTyping(chatId, threadId || 0)

      // Build message, include reply context if present
      let messageText = text.replace(`@${botUsername}`, '').trim()
      let replyPhoto: { file_id: string; file_path?: string } | undefined
      if (ctx.message.reply_to_message) {
        const reply = ctx.message.reply_to_message as any
        const replyFrom = reply.from?.username || reply.from?.first_name || 'unknown'
        const replyText = reply.text || reply.caption || ''
        if (replyText) {
          messageText = `[реплай на сообщение от ${replyFrom}: "${replyText.slice(0, 500)}"]\n\n${messageText}`
        }
        // Download photo from the replied message
        if (reply.photo && reply.photo.length > 0) {
          const best = reply.photo[reply.photo.length - 1]
          try {
            const localPath = await downloadFile(bot, best.file_id, reply.message_id)
            replyPhoto = { file_id: best.file_id, file_path: localPath }
            if (!replyText) {
              messageText = `[реплай на фото от ${replyFrom}]\n\n${messageText}`
            }
          } catch (err: any) {
            console.error('[Bot] Reply photo download failed:', err.message)
          }
        }
      }

      const incoming: IncomingMessage = {
        message_id: ctx.message.message_id,
        thread_id: ipcThread, // route through single IPC session
        chat_id: String(chatId),
        text: messageText,
        from: {
          id: ctx.from!.id,
          first_name: ctx.from!.first_name,
          username: ctx.from!.username,
        },
        recent_messages: chatHistory.getRecent(chatId, 15).reverse().map(m => ({
          from: m.username || m.first_name,
          text: m.text,
          ts: m.ts,
        })),
        reply_thread_id: threadId, // actual Telegram thread to reply in
        photo: replyPhoto, // photo from replied message (if any)
      }

      // Handle photos in the message itself (overrides reply photo)
      if (ctx.message.photo && ctx.message.photo.length > 0) {
        const best = ctx.message.photo[ctx.message.photo.length - 1]
        try {
          const localPath = await downloadFile(bot, best.file_id, ctx.message.message_id)
          incoming.photo = { file_id: best.file_id, file_path: localPath }
        } catch (err: any) {
          console.error('[Bot] Photo download failed:', err.message)
        }
        incoming.text = messageText || incoming.caption || '(photo)'
      }

      // Handle voice in group
      if (ctx.message.voice) {
        try {
          const localPath = await downloadFile(bot, ctx.message.voice.file_id, ctx.message.message_id, 'voice.ogg')
          console.log(`[Bot] Transcribing group voice (${ctx.message.voice.duration}s)...`)
          const transcription = await transcribeAudio(localPath, ctx.message.voice.duration)
          incoming.text = transcription || '(voice, transcription failed)'
          incoming.voice = { file_id: ctx.message.voice.file_id, file_path: localPath, duration: ctx.message.voice.duration, transcription }
          // Update DB with transcription text
          chatHistory.updateText(chatId, ctx.message.message_id, `[голосовое] ${transcription}`)
        } catch (err: any) {
          console.error('[Bot] Voice processing failed:', err.message)
          incoming.text = '(voice message, processing failed)'
        }
      }

      // Handle video notes (кружочки) in group
      if ((ctx.message as any).video_note) {
        const videoNote = (ctx.message as any).video_note
        try {
          const localPath = await downloadFile(bot, videoNote.file_id, ctx.message.message_id, 'video_note.mp4')
          console.log(`[Bot] Transcribing group video note (${videoNote.duration}s)...`)
          const transcription = await transcribeAudio(localPath, videoNote.duration)
          incoming.text = transcription || '(video note, transcription failed)'
          incoming.voice = { file_id: videoNote.file_id, file_path: localPath, duration: videoNote.duration, transcription }
          chatHistory.updateText(chatId, ctx.message.message_id, `[кружочек] ${transcription}`)
        } catch (err: any) {
          console.error('[Bot] Video note processing failed:', err.message)
          incoming.text = '(video note, processing failed)'
        }
      }

      const sent = ipc.sendToSession(ipcThread, { type: 'incoming_message', message: incoming })
      console.log(`[Bot] Group message → session (telegram thread=${threadId}): ${sent ? 'OK' : 'FAILED'}`)

      // 👀 = delivered to Claude session
      if (sent) {
        bot.api.setMessageReaction(chatId, ctx.message.message_id, [
          { type: 'emoji', emoji: '👀' as any },
        ]).catch(err => console.error('[Bot] Reaction failed:', err.message))
      }
      stopTyping(threadId || 0)
      return
    }

    // === Private chat mode (original behavior) ===

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

    // Terminal commands in topics → forward directly to tmux (server-aware, no AI)
    const topicText = ctx.message.text || ''
    const termCmd = TERMINAL_COMMANDS.find(c => topicText === c || topicText.startsWith(c + ' '))
    if (termCmd) {
      const topic = registry.get(threadId)
      const sessionName = `tg-${threadId}`
      console.log(`[Bot] Terminal command "${topicText}" → tmux:${sessionName} (${topic?.server})`)
      try {
        await sendToTmux(topic?.server, sessionName, topicText)
        await bot.api.setMessageReaction(chatId, ctx.message.message_id, [
          { type: 'emoji', emoji: '👌' as any },
        ]).catch(() => {})
      } catch (err: any) {
        await bot.api.setMessageReaction(chatId, ctx.message.message_id, [
          { type: 'emoji', emoji: '❌' as any },
        ]).catch(() => {})
        await ctx.reply(`❌ ${err.message}`, { message_thread_id: threadId })
      }
      return
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

  // Notify thread when session connects
  let startupPhase = true
  setTimeout(() => { startupPhase = false }, 15000) // suppress notifications during initial reconnect burst

  ipc.onRegister((threadId, chatId) => {
    if (startupPhase) return // skip the batch of reconnects at proxy startup
    bot.api.sendMessage(chatId, `✅ Сессия подключена \`${threadId}\``, {
      message_thread_id: threadId,
      parse_mode: 'MarkdownV2',
    }).catch(err => console.error(`[Bot] Session connect notify failed:`, err.message))
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
          // Record bot's own message in persistent history
          if (groupChatId && String(groupChatId) === msg.chat_id) {
            chatHistory.save({
              chat_id: groupChatId,
              message_id: Date.now(), // placeholder, will be replaced if we get the real ID
              user_id: bot.botInfo.id,
              username: bot.botInfo.username || 'bot',
              first_name: bot.botInfo.first_name || 'Bot',
              text: msg.text,
            })
          }
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
