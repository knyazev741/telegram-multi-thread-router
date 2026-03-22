import type { Context, Bot } from 'grammy'
import type { TopicsRegistry } from './topics-registry.js'
import type { IPCServer } from './ipc-server.js'

const ICON_COLORS = [0x6FB9F0, 0xFFD67E, 0xCB86DB, 0x8EEE98, 0xFF93B2, 0xFB6F5F]
let colorIndex = 0

export function launchCommands(threadId: number | string, _publicHost: string, pluginName: string = 'telegram-multi@telegram-multi-thread'): string {
  const cmd = `TELEGRAM_THREAD_ID=${threadId} claude --dangerously-load-development-channels plugin:${pluginName} --dangerously-skip-permissions`
  return `<pre>${cmd}</pre>`
}

export function createCommandHandler(bot: Bot, registry: TopicsRegistry, ipc: IPCServer, publicHost: string = '', pluginName: string = 'telegram-multi@telegram-multi-thread') {
  return async function handleCommand(ctx: Context): Promise<void> {
    const text = ctx.message?.text || ''
    const args = text.split(/\s+/)
    const command = args[0]

    switch (command) {
      case '/new': {
        const name = args.slice(1).join(' ') || 'Новая сессия'
        try {
          const topic = await bot.api.createForumTopic(ctx.chat!.id, name, {
            icon_color: ICON_COLORS[colorIndex++ % ICON_COLORS.length] as any,
          })

          registry.add(topic.message_thread_id, name)

          await ctx.reply(
            `✅ Топик "<b>${name}</b>" создан (thread_id: ${topic.message_thread_id})\n\n` +
            `Запустите сессию Claude Code:\n\n` +
            launchCommands(topic.message_thread_id, publicHost, pluginName),
            { message_thread_id: 1, parse_mode: 'HTML' },
          )
        } catch (err: any) {
          await ctx.reply(`❌ Ошибка создания топика: ${err.message}`)
        }
        break
      }

      case '/close': {
        const threadId = parseInt(args[1])
        if (!threadId) {
          await ctx.reply('Использование: /close <thread_id>')
          break
        }

        const results: string[] = []

        // 1. Disconnect IPC session if connected
        const disconnected = ipc.closeSession(threadId)
        if (disconnected) results.push('🔌 IPC-сессия отключена')

        // 2. Delete Telegram topic
        try {
          await bot.api.deleteForumTopic(ctx.chat!.id, threadId)
          results.push('🗑 Топик удалён')
        } catch (err: any) {
          results.push(`⚠️ Топик: ${err.message}`)
        }

        // 3. Remove from registry
        const name = registry.getName(threadId) || String(threadId)
        registry.remove(threadId)
        results.push('📋 Реестр очищен')

        await ctx.reply(
          `✅ Тред <b>${name}</b> (${threadId}) закрыт:\n` + results.map(r => `• ${r}`).join('\n'),
          { message_thread_id: 1, parse_mode: 'HTML' },
        )
        break
      }

      case '/list': {
        const topics = registry.getAll()
        if (topics.length === 0) {
          await ctx.reply('Нет созданных топиков. Используйте /new <название>')
          return
        }

        let response = '📋 Топики:\n\n'
        for (const t of topics) {
          const session = ipc.getSession(t.threadId)
          const status = session ? '🟢 подключена' : '🔴 нет сессии'
          response += `• ${t.name} (thread: ${t.threadId}) — ${status}\n`
        }

        await ctx.reply(response)
        break
      }

      case '/sessions': {
        const sessions = ipc.getConnectedSessions()
        if (sessions.length === 0) {
          await ctx.reply('Нет активных сессий.')
          return
        }

        let response = '🔌 Активные сессии:\n\n'
        for (const s of sessions) {
          const name = registry.getName(s.threadId) || 'unknown'
          const uptime = Math.floor((Date.now() - s.connectedAt.getTime()) / 60000)
          response += `• ${name} (thread: ${s.threadId}) — ${uptime} мин\n`
        }

        await ctx.reply(response)
        break
      }

      case '/help': {
        await ctx.reply(
          '<b>Команды управления:</b>\n\n' +
          '/new &lt;название&gt; — создать новый топик\n' +
          '/list — показать все топики и статус сессий\n' +
          '/sessions — показать активные сессии\n' +
          '/close &lt;thread_id&gt; — закрыть тред и сессию\n' +
          '/help — это сообщение\n\n' +
          '<b>Запуск сессии:</b>\n\n' +
          launchCommands('&lt;id&gt;', publicHost, pluginName),
          { parse_mode: 'HTML' },
        )
        break
      }

      default: {
        if (text.startsWith('/')) {
          await ctx.reply('Неизвестная команда. /help — список команд.')
        }
      }
    }
  }
}
