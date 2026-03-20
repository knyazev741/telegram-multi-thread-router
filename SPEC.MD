# Техническое задание: Telegram Multi-Thread Router + Модифицированный Claude Code Telegram Plugin

**Версия:** 2.0
**Дата:** 2026-03-20
**Архитектура:** Тонкий прокси + форк плагина с параметром thread_id

---

## Оглавление

1. [Цель проекта](#1-цель-проекта)
2. [Архитектура](#2-архитектура)
3. [Компонент 1: Telegram Proxy (роутер)](#3-компонент-1-telegram-proxy)
4. [Компонент 2: Форк Telegram-плагина](#4-компонент-2-форк-telegram-плагина)
5. [Telegram Bot API: Forum Topics](#5-telegram-bot-api-forum-topics)
6. [Структура проекта](#6-структура-проекта)
7. [Детальная реализация Proxy](#7-детальная-реализация-proxy)
8. [Детальная реализация изменений в плагине](#8-детальная-реализация-изменений-в-плагине)
9. [Конфигурация](#9-конфигурация)
10. [Протокол IPC между Proxy и сессиями](#10-протокол-ipc-между-proxy-и-сессиями)
11. [Управление топиками](#11-управление-топиками)
12. [Контроль доступа](#12-контроль-доступа)
13. [Обработка фото и файлов](#13-обработка-фото-и-файлов)
14. [Сохранение контекста между перезапусками](#14-сохранение-контекста-между-перезапусками)
15. [Развёртывание и запуск](#15-развёртывание-и-запуск)
16. [Порядок реализации (фазы)](#16-порядок-реализации-фазы)
17. [Справочные ссылки](#17-справочные-ссылки)
18. [Примеры сценариев от начала до конца](#18-примеры-сценариев-от-начала-до-конца)
19. [Чеклист перед началом кодирования](#19-чеклист-перед-началом-кодирования)

---

## 1. Цель проекта

Минимальными изменениями добиться следующего:

- **Один Telegram-бот** с включённым Threaded Mode (Forum Topics).
- Каждый **топик (вкладка)** в этом боте привязан к **отдельной сессии Claude Code**.
- Пользователь сам запускает каждую сессию Claude Code в терминале, указывая, к какому топику она привязана.
- Сообщения из каждого топика попадают только в свою сессию, ответы уходят только в свой топик.
- Всё остальное поведение Claude Code (файлы, bash, MCP, плагины) сохраняется полностью.

**Что НЕ входит в проект:**
- Автоматический запуск/остановка сессий (пользователь делает это вручную).
- Сложный диспетчер или менеджер сессий.
- Веб-интерфейс или дашборд.

---

## 2. Архитектура

### 2.1. Проблема

Telegram Bot API отдаёт обновления (входящие сообщения) через **long polling** — и только **одному подключению на один токен**. Если несколько сессий Claude Code попытаются делать long polling с одним токеном — обновления будут хаотично распределяться между ними. Это сломает маршрутизацию.

### 2.2. Решение

Два компонента:

```
┌──────────────────────────────────────────────────────────────┐
│                   Telegram (телефон)                          │
│                                                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ General   │  │ Проект А │  │ Проект Б │  │ DevOps   │     │
│  │ thread=1  │  │ thread=42│  │ thread=87│  │ thread=93│     │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │
└────────────────────────┬─────────────────────────────────────┘
                         │ Bot API (long polling)
                         │
┌────────────────────────▼─────────────────────────────────────┐
│              TELEGRAM PROXY (Node.js)                         │
│              Один процесс, всегда работает.                   │
│                                                               │
│  - Единственный, кто делает long polling.                     │
│  - Получает ВСЕ обновления от Telegram.                      │
│  - Смотрит message_thread_id.                                │
│  - Пересылает обновление в нужную сессию через Unix socket.  │
│  - Принимает ответы от сессий и отправляет в Telegram.       │
│  - General-топик: управление (создать/список топиков).       │
│                                                               │
│  Слушает: /tmp/claude-proxy/control.sock (входящие от сессий)│
│  Пишет в: /tmp/claude-proxy/session-{thread_id}.sock         │
└───────┬──────────┬──────────┬────────────────────────────────┘
        │ IPC      │ IPC      │ IPC
        ▼          ▼          ▼
┌───────────┐ ┌───────────┐ ┌───────────┐
│ Claude    │ │ Claude    │ │ Claude    │
│ Code      │ │ Code      │ │ Code      │
│ thread=42 │ │ thread=87 │ │ thread=93 │
│           │ │           │ │           │
│ cwd:      │ │ cwd:      │ │ cwd:      │
│ /proj-a   │ │ /proj-b   │ │ /infra    │
└───────────┘ └───────────┘ └───────────┘
  (tmux:1)      (tmux:2)      (tmux:3)
```

### 2.3. Поток данных

**Входящее сообщение (user → Claude):**
```
1. Пользователь пишет "Запусти тесты" в топик "Проект А" (thread=42)
2. Telegram отправляет update с message_thread_id=42
3. Proxy получает update через long polling
4. Proxy смотрит thread_id=42 → находит подключённую сессию для thread=42
5. Proxy пересылает сообщение в сессию через Unix socket
6. Модифицированный плагин в сессии Claude Code получает сообщение
7. Claude Code обрабатывает запрос
```

**Исходящее сообщение (Claude → user):**
```
1. Claude Code хочет ответить через tool "reply"
2. Модифицированный плагин отправляет ответ через Unix socket в Proxy
3. Proxy вызывает bot.api.sendMessage(chat_id, text, { message_thread_id: 42 })
4. Пользователь видит ответ в топике "Проект А"
```

### 2.4. Почему так, а не иначе

| Вариант | Плюсы | Минусы |
|---------|-------|--------|
| **Этот (Proxy + IPC)** | Минимальные изменения в плагине, надёжная маршрутизация, сессии полностью независимы | Нужен отдельный процесс Proxy |
| Каждая сессия делает свой long polling | Не нужен Proxy | НЕ РАБОТАЕТ — Telegram отдаёт обновления только одному подключению |
| Webhook | Не нужен long polling | Нужен домен + SSL + белый IP, сложнее для домашнего сервера |
| Один монолитный диспетчер | Один процесс | Теряем нативный Claude Code, нужно эмулировать через API |

---

## 3. Компонент 1: Telegram Proxy

### 3.1. Что это

Лёгкий Node.js-процесс (~300-400 строк кода). Его задачи:

1. **Long polling** — единственная точка подключения к Telegram Bot API.
2. **Маршрутизация** — по `message_thread_id` определяет, какой сессии переслать сообщение.
3. **Отправка** — принимает от сессий команды на отправку и вызывает Telegram Bot API.
4. **General-топик** — обрабатывает команды управления (`/new`, `/list`).
5. **Реестр сессий** — знает, какие сессии подключены и к каким топикам.

### 3.2. Чего он НЕ делает

- Не запускает Claude Code.
- Не управляет жизненным циклом сессий.
- Не хранит историю сообщений (это делает Claude Code внутри своей сессии).
- Не обрабатывает контент сообщений — просто пересылает.

### 3.3. Технологии

- **Язык:** TypeScript (Node.js)
- **Telegram:** grammY (https://grammy.dev/)
- **IPC:** Unix domain sockets (модуль `net` из Node.js)
- **Зависимости:** grammy, dotenv — и всё.

---

## 4. Компонент 2: Форк Telegram-плагина

### 4.1. Что меняется

Берём существующий плагин из https://github.com/anthropics/claude-plugins-official/tree/main/external_plugins/telegram и вносим минимальные изменения:

**Изменение 1: Новый параметр `TELEGRAM_THREAD_ID`.**
Сессия знает, к какому топику она привязана.

**Изменение 2: Подключение к Proxy вместо прямого Bot API.**
Вместо собственного long polling, плагин подключается к Proxy через Unix socket.

**Изменение 3: Фильтрация входящих.**
Плагин принимает только сообщения со своим thread_id (на всякий случай, как второй уровень фильтрации).

**Изменение 4: Исходящие с thread_id.**
Все отправки (`reply`, `react`, `edit_message`) включают `message_thread_id`.

### 4.2. Что НЕ меняется

- Структура MCP-сервера.
- Инструменты `reply`, `react`, `edit_message` — те же, только с добавленным thread_id.
- Скачивание фото.
- Контроль доступа (оставляем как есть + фильтрация на уровне Proxy).
- Всё остальное поведение плагина.

---

## 5. Telegram Bot API: Forum Topics

### 5.1. Включение Threaded Mode

Перед началом работы — одноразовая настройка:

```
1. Открыть @BotFather в Telegram.
2. Выбрать бота.
3. Включить Threaded Mode (Forum Topics для приватных чатов).
   - Через BotFather Mini App, или
   - Через команду в BotFather (если доступна).
4. Результат: чат с ботом теперь показывает вкладки.
```

**Важно проверить:** включённый Threaded Mode подтверждается полем `has_topics_enabled: true` в объекте `User` (для бота). Ссылка: https://core.telegram.org/bots/api#user

**Возможная платность:** В документации Telegram упоминается: "This feature is subject to an additional fee for Telegram Star purchases as described in Section 6.2.6 of our Terms of Service for Bot Developers." Нужно проверить при включении — возможно, потребуется оплата в Telegram Stars.

### 5.2. Структура входящего сообщения

Когда пользователь пишет в топик, Telegram отправляет Update:

```json
{
  "update_id": 123456,
  "message": {
    "message_id": 789,
    "message_thread_id": 42,
    "is_topic_message": true,
    "from": {
      "id": 412587349,
      "first_name": "User",
      "username": "myuser"
    },
    "chat": {
      "id": 412587349,
      "type": "private"
    },
    "date": 1710936000,
    "text": "Запусти тесты"
  }
}
```

Ключевые поля:
- `message.message_thread_id` — ID топика (число). Используется для маршрутизации.
- `message.is_topic_message` — `true` если сообщение из топика.
- Для General-топика: `message_thread_id` равен 1 или отсутствует.

### 5.3. Отправка в топик

Все методы отправки поддерживают параметр `message_thread_id`:

```javascript
// Текст
await bot.api.sendMessage(chatId, "Ответ", {
  message_thread_id: 42
});

// Фото
await bot.api.sendPhoto(chatId, fileId, {
  message_thread_id: 42,
  caption: "Скриншот"
});

// Документ
await bot.api.sendDocument(chatId, fileId, {
  message_thread_id: 42
});

// Typing indicator
await bot.api.sendChatAction(chatId, "typing", {
  message_thread_id: 42
});
```

### 5.4. Создание топика

```javascript
const topic = await bot.api.createForumTopic(chatId, "Проект А", {
  icon_color: 0x6FB9F0  // Голубой
});

console.log(topic.message_thread_id); // → 42 (ID нового топика)
console.log(topic.name);              // → "Проект А"
```

Доступные цвета иконок:
- `0x6FB9F0` — голубой
- `0xFFD67E` — жёлтый
- `0xCB86DB` — фиолетовый
- `0x8EEE98` — зелёный
- `0xFF93B2` — розовый
- `0xFB6F5F` — красный

### 5.5. Другие операции с топиками

```javascript
// Переименовать
await bot.api.editForumTopic(chatId, threadId, { name: "Новое имя" });

// Закрыть (нельзя писать, но видно)
await bot.api.closeForumTopic(chatId, threadId);

// Открыть заново
await bot.api.reopenForumTopic(chatId, threadId);

// Удалить со всеми сообщениями
await bot.api.deleteForumTopic(chatId, threadId);
```

### 5.6. Ограничения Bot API

- **Нет метода getForumTopics для ботов.** Бот не может запросить список существующих топиков. Proxy должен хранить свой реестр.
- **Нет истории сообщений.** Бот видит только новые входящие.
- **Лимит 4096 символов** на сообщение.
- **Файлы:** до 50 МБ отправка, до 20 МБ скачивание.
- **Реакции:** только из фиксированного списка Telegram.
- **Фото сжимаются.** Для оригинального качества — отправлять как файл (Send as File).

---

## 6. Структура проекта

```
claude-telegram-multi/
│
├── proxy/                          # Компонент 1: Telegram Proxy
│   ├── package.json
│   ├── tsconfig.json
│   ├── src/
│   │   ├── index.ts                # Точка входа
│   │   ├── bot.ts                  # grammY: long polling, отправка
│   │   ├── router.ts               # thread_id → session socket
│   │   ├── ipc-server.ts           # Unix socket сервер для сессий
│   │   ├── commands.ts             # Команды в General-топике
│   │   ├── topics-registry.ts      # Реестр топиков (JSON файл)
│   │   └── types.ts                # Типы
│   └── config/
│       ├── .env                    # BOT_TOKEN, OWNER_ID
│       └── topics.json             # Реестр топиков
│
├── plugin/                         # Компонент 2: Форк плагина
│   └── telegram/                   # Модифицированный плагин
│       ├── ... (структура оригинального плагина)
│       └── (изменённые файлы)
│
├── scripts/
│   ├── start-proxy.sh              # Запуск Proxy в tmux
│   ├── start-session.sh            # Запуск сессии Claude Code с thread_id
│   └── start-all.sh                # Запуск Proxy + всех сессий
│
└── README.md
```

---

## 7. Детальная реализация Proxy

### 7.1. `proxy/src/index.ts` — Точка входа

```typescript
import { startBot } from "./bot";
import { startIPCServer } from "./ipc-server";
import { loadTopicsRegistry } from "./topics-registry";

async function main() {
  // 1. Загрузить реестр топиков
  const registry = loadTopicsRegistry();

  // 2. Запустить IPC-сервер (Unix sockets)
  const ipc = await startIPCServer(registry);

  // 3. Запустить Telegram-бота (long polling)
  const bot = await startBot(registry, ipc);

  // 4. Graceful shutdown
  const shutdown = async () => {
    console.log("Shutting down...");
    bot.stop();
    ipc.closeAll();
    process.exit(0);
  };

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);

  console.log("Proxy started. Waiting for sessions to connect...");
}

main().catch(console.error);
```

### 7.2. `proxy/src/bot.ts` — Telegram Client

```typescript
import { Bot } from "grammy";
import { Router } from "./router";
import { IPCServer } from "./ipc-server";
import { handleCommand } from "./commands";

export async function startBot(registry, ipc: IPCServer) {
  const bot = new Bot(process.env.TELEGRAM_BOT_TOKEN!);

  bot.on("message", async (ctx) => {
    const userId = ctx.from?.id;
    const chatId = ctx.chat.id;
    const threadId = ctx.message.message_thread_id;

    // 1. Проверка доступа
    if (userId !== Number(process.env.OWNER_USER_ID)) {
      return; // Тихо игнорируем чужих
    }

    // 2. General-топик → команды управления
    if (!threadId || threadId === 1) {
      return handleCommand(ctx, bot, registry);
    }

    // 3. Найти подключённую сессию для этого топика
    const session = ipc.getSession(threadId);

    if (!session) {
      await ctx.reply(
        "⚠️ Нет подключённой сессии для этого топика.\n" +
        "Запустите сессию:\n" +
        `claude --channels plugin:telegram-multi --thread ${threadId}`,
        { message_thread_id: threadId }
      );
      return;
    }

    // 4. Переслать сообщение в сессию
    session.send({
      type: "incoming_message",
      message: {
        message_id: ctx.message.message_id,
        thread_id: threadId,
        text: ctx.message.text || "",
        from: ctx.from,
        // Фото, файлы — обработка ниже в разделе 13
        photo: ctx.message.photo,
        document: ctx.message.document,
      }
    });
  });

  // Обработка исходящих от сессий (через IPC)
  ipc.onOutgoing(async (msg) => {
    switch (msg.type) {
      case "send_message":
        await bot.api.sendMessage(msg.chat_id, msg.text, {
          message_thread_id: msg.thread_id,
          reply_to_message_id: msg.reply_to,
          parse_mode: msg.parse_mode,
        });
        break;

      case "send_photo":
        await bot.api.sendPhoto(msg.chat_id, msg.file_id_or_path, {
          message_thread_id: msg.thread_id,
          caption: msg.caption,
        });
        break;

      case "send_document":
        await bot.api.sendDocument(msg.chat_id, msg.file_id_or_path, {
          message_thread_id: msg.thread_id,
          caption: msg.caption,
        });
        break;

      case "send_chat_action":
        await bot.api.sendChatAction(msg.chat_id, msg.action, {
          message_thread_id: msg.thread_id,
        });
        break;

      case "react":
        await bot.api.setMessageReaction(msg.chat_id, msg.message_id, {
          reaction: [{ type: "emoji", emoji: msg.emoji }],
        });
        break;

      case "edit_message":
        await bot.api.editMessageText(msg.chat_id, msg.message_id, msg.text, {
          parse_mode: msg.parse_mode,
        });
        break;
    }
  });

  bot.start();
  return bot;
}
```

### 7.3. `proxy/src/ipc-server.ts` — IPC через Unix Sockets

```typescript
import net from "net";
import fs from "fs";
import path from "path";

const SOCKET_DIR = "/tmp/claude-proxy";

interface ConnectedSession {
  threadId: number;
  socket: net.Socket;
  connectedAt: Date;
}

export class IPCServer {
  private sessions: Map<number, ConnectedSession> = new Map();
  private server: net.Server;
  private outgoingHandler: ((msg: any) => void) | null = null;

  constructor() {
    // Создать директорию для сокетов
    fs.mkdirSync(SOCKET_DIR, { recursive: true });

    const controlSocket = path.join(SOCKET_DIR, "control.sock");

    // Удалить старый сокет если есть
    if (fs.existsSync(controlSocket)) {
      fs.unlinkSync(controlSocket);
    }

    // Сервер: сессии подключаются сюда
    this.server = net.createServer((socket) => {
      let buffer = "";

      socket.on("data", (data) => {
        buffer += data.toString();

        // Протокол: JSON-сообщения разделённые \n
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const msg = JSON.parse(line);
            this.handleSessionMessage(socket, msg);
          } catch (e) {
            console.error("Invalid JSON from session:", e);
          }
        }
      });

      socket.on("close", () => {
        // Найти и удалить отключившуюся сессию
        for (const [threadId, session] of this.sessions) {
          if (session.socket === socket) {
            console.log(`Session for thread ${threadId} disconnected`);
            this.sessions.delete(threadId);
            break;
          }
        }
      });

      socket.on("error", (err) => {
        console.error("Socket error:", err);
      });
    });

    this.server.listen(controlSocket, () => {
      console.log(`IPC server listening on ${controlSocket}`);
    });
  }

  private handleSessionMessage(socket: net.Socket, msg: any) {
    switch (msg.type) {
      case "register":
        // Сессия регистрируется: "я обслуживаю thread_id=42"
        const threadId = msg.thread_id;
        this.sessions.set(threadId, {
          threadId,
          socket,
          connectedAt: new Date(),
        });
        console.log(`Session registered for thread ${threadId}`);

        // Подтвердить регистрацию
        this.sendToSocket(socket, {
          type: "registered",
          thread_id: threadId,
        });
        break;

      case "send_message":
      case "send_photo":
      case "send_document":
      case "send_chat_action":
      case "react":
      case "edit_message":
        // Сессия хочет отправить что-то в Telegram
        if (this.outgoingHandler) {
          this.outgoingHandler(msg);
        }
        break;
    }
  }

  // Переслать входящее сообщение в нужную сессию
  getSession(threadId: number): ConnectedSession | null {
    return this.sessions.get(threadId) || null;
  }

  // Отправить данные конкретной сессии
  sendToSession(threadId: number, msg: any): boolean {
    const session = this.sessions.get(threadId);
    if (!session) return false;
    return this.sendToSocket(session.socket, msg);
  }

  private sendToSocket(socket: net.Socket, msg: any): boolean {
    try {
      socket.write(JSON.stringify(msg) + "\n");
      return true;
    } catch (e) {
      console.error("Failed to send to socket:", e);
      return false;
    }
  }

  // Обработчик исходящих сообщений (от сессий → Telegram)
  onOutgoing(handler: (msg: any) => void) {
    this.outgoingHandler = handler;
  }

  // Список подключённых сессий
  getConnectedSessions(): Array<{ threadId: number; connectedAt: Date }> {
    return Array.from(this.sessions.values()).map(s => ({
      threadId: s.threadId,
      connectedAt: s.connectedAt,
    }));
  }

  closeAll() {
    for (const session of this.sessions.values()) {
      session.socket.end();
    }
    this.server.close();
  }
}
```

### 7.4. `proxy/src/commands.ts` — Команды в General-топике

```typescript
import { Context, Bot } from "grammy";

export async function handleCommand(ctx: Context, bot: Bot, registry) {
  const text = ctx.message?.text || "";
  const args = text.split(/\s+/);
  const command = args[0];

  switch (command) {
    case "/new": {
      // /new Название проекта
      const name = args.slice(1).join(" ") || "Новая сессия";

      // Создать топик в Telegram
      const topic = await bot.api.createForumTopic(ctx.chat!.id, name, {
        icon_color: 0x6FB9F0,
      });

      // Сохранить в реестр
      registry.add(topic.message_thread_id, name);

      await ctx.reply(
        `✅ Топик "${name}" создан (thread_id: ${topic.message_thread_id}).\n\n` +
        `Запустите сессию Claude Code:\n` +
        `\`\`\`\n` +
        `claude --channels plugin:telegram-multi --thread ${topic.message_thread_id}\n` +
        `\`\`\``,
        { parse_mode: "Markdown" }
      );
      break;
    }

    case "/list": {
      const topics = registry.getAll();
      const ipc = /* ссылка на ipc */ null; // передать через замыкание

      if (topics.length === 0) {
        await ctx.reply("Нет созданных топиков. Используйте /new <название>");
        return;
      }

      let response = "📋 **Топики:**\n\n";
      for (const t of topics) {
        const connected = ipc?.getSession(t.threadId) ? "🟢 подключена" : "🔴 нет сессии";
        response += `• **${t.name}** (thread: ${t.threadId}) — ${connected}\n`;
      }

      await ctx.reply(response, { parse_mode: "Markdown" });
      break;
    }

    case "/help": {
      await ctx.reply(
        "**Команды управления:**\n\n" +
        "/new <название> — создать новый топик\n" +
        "/list — показать все топики и статус сессий\n" +
        "/help — это сообщение\n\n" +
        "**Запуск сессии:**\n" +
        "`claude --channels plugin:telegram-multi --thread <thread_id>`",
        { parse_mode: "Markdown" }
      );
      break;
    }

    default: {
      // Если не команда — можно игнорировать или подсказать
      if (text.startsWith("/")) {
        await ctx.reply("Неизвестная команда. /help — список команд.");
      }
    }
  }
}
```

### 7.5. `proxy/src/topics-registry.ts` — Реестр топиков

```typescript
import fs from "fs";
import path from "path";

interface TopicEntry {
  threadId: number;
  name: string;
  createdAt: string;
}

const REGISTRY_PATH = path.join(__dirname, "../config/topics.json");

export class TopicsRegistry {
  private topics: TopicEntry[] = [];

  constructor() {
    this.load();
  }

  private load() {
    try {
      const data = fs.readFileSync(REGISTRY_PATH, "utf-8");
      this.topics = JSON.parse(data);
    } catch {
      this.topics = [];
    }
  }

  private save() {
    fs.writeFileSync(REGISTRY_PATH, JSON.stringify(this.topics, null, 2));
  }

  add(threadId: number, name: string) {
    this.topics.push({
      threadId,
      name,
      createdAt: new Date().toISOString(),
    });
    this.save();
  }

  remove(threadId: number) {
    this.topics = this.topics.filter(t => t.threadId !== threadId);
    this.save();
  }

  getAll(): TopicEntry[] {
    return [...this.topics];
  }

  getName(threadId: number): string | null {
    return this.topics.find(t => t.threadId === threadId)?.name || null;
  }
}
```

---

## 8. Детальная реализация изменений в плагине

### 8.1. Что форкаем

Исходный код: https://github.com/anthropics/claude-plugins-official/tree/main/external_plugins/telegram

**Первый шаг:** склонировать репозиторий и изучить структуру плагина:

```bash
git clone https://github.com/anthropics/claude-plugins-official.git
ls external_plugins/telegram/
```

Изучить:
- Как плагин подключается к Telegram (long polling? webhook?).
- Где обрабатываются входящие сообщения.
- Где реализованы tools (reply, react, edit_message).
- Как плагин передаёт сообщения в Claude Code (MCP protocol).

### 8.2. Изменение 1: Конфигурация thread_id

**Новая переменная окружения:**
```env
TELEGRAM_THREAD_ID=42
```

**Или через `/telegram:configure`:**
```
/telegram:configure --thread 42
```

Записывается в `~/.claude/channels/telegram/.env`:
```env
TELEGRAM_BOT_TOKEN=123456789:AAHfiqksKZ8...
TELEGRAM_THREAD_ID=42
```

### 8.3. Изменение 2: Подключение к Proxy вместо Bot API

Вместо собственного long polling, плагин подключается к Proxy через Unix socket.

**БЫЛО (упрощённо):**
```typescript
// Плагин сам делает long polling
const bot = new Bot(token);
bot.on("message", (ctx) => {
  forwardToClaudeCode(ctx.message);
});
bot.start();
```

**СТАЛО:**
```typescript
import net from "net";

const PROXY_SOCKET = "/tmp/claude-proxy/control.sock";
const THREAD_ID = Number(process.env.TELEGRAM_THREAD_ID);

// Подключиться к Proxy
const socket = net.createConnection(PROXY_SOCKET, () => {
  // Зарегистрироваться: "я обслуживаю thread_id=42"
  socket.write(JSON.stringify({
    type: "register",
    thread_id: THREAD_ID,
    chat_id: CHAT_ID,
  }) + "\n");
});

// Получать входящие от Proxy
let buffer = "";
socket.on("data", (data) => {
  buffer += data.toString();
  const lines = buffer.split("\n");
  buffer = lines.pop() || "";

  for (const line of lines) {
    if (!line.trim()) continue;
    const msg = JSON.parse(line);

    if (msg.type === "incoming_message") {
      // Переслать в Claude Code через MCP
      forwardToClaudeCode(msg.message);
    }
  }
});

// Функция отправки (вызывается из tools reply/react/edit)
function sendToTelegram(payload: any) {
  // Добавить thread_id ко всем исходящим
  payload.thread_id = THREAD_ID;
  socket.write(JSON.stringify(payload) + "\n");
}
```

### 8.4. Изменение 3: Tools с thread_id

**Tool `reply` — БЫЛО:**
```typescript
async function reply(chatId, text, replyTo?, files?) {
  await bot.api.sendMessage(chatId, text, {
    reply_to_message_id: replyTo,
  });
}
```

**Tool `reply` — СТАЛО:**
```typescript
async function reply(chatId, text, replyTo?, files?) {
  sendToTelegram({
    type: "send_message",
    chat_id: chatId,
    text: text,
    reply_to: replyTo,
    thread_id: THREAD_ID,  // ДОБАВЛЕНО
  });
}
```

Аналогично для `react` и `edit_message`.

### 8.5. Изменение 4: Typing indicator с thread_id

**БЫЛО:**
```typescript
await bot.api.sendChatAction(chatId, "typing");
```

**СТАЛО:**
```typescript
sendToTelegram({
  type: "send_chat_action",
  chat_id: chatId,
  action: "typing",
  thread_id: THREAD_ID,  // ДОБАВЛЕНО
});
```

---

## 9. Конфигурация

### 9.1. Proxy `.env`

```env
# Обязательные
TELEGRAM_BOT_TOKEN=123456789:AAHfiqksKZ8...
OWNER_USER_ID=412587349

# Опциональные
SOCKET_DIR=/tmp/claude-proxy
LOG_LEVEL=info
```

### 9.2. Для каждой сессии Claude Code

В `~/.claude/channels/telegram/.env` (или переменные окружения):
```env
TELEGRAM_BOT_TOKEN=123456789:AAHfiqksKZ8...
TELEGRAM_THREAD_ID=42
TELEGRAM_PROXY_SOCKET=/tmp/claude-proxy/control.sock
```

**Или через аргументы:**
```bash
TELEGRAM_THREAD_ID=42 claude --channels plugin:telegram-multi
```

### 9.3. `proxy/config/topics.json`

Автоматически обновляется при `/new`:
```json
[
  {
    "threadId": 42,
    "name": "Проект А",
    "createdAt": "2026-03-20T10:00:00Z"
  },
  {
    "threadId": 87,
    "name": "Проект Б",
    "createdAt": "2026-03-20T11:30:00Z"
  }
]
```

---

## 10. Протокол IPC между Proxy и сессиями

### 10.1. Транспорт

Unix domain sockets. Один сокет `/tmp/claude-proxy/control.sock`, к которому подключаются все сессии.

### 10.2. Формат

JSON-строки, разделённые `\n` (newline-delimited JSON, NDJSON).

### 10.3. Сообщения от сессии к Proxy

**Регистрация (при подключении):**
```json
{
  "type": "register",
  "thread_id": 42,
  "chat_id": 412587349
}
```

**Отправить текст в Telegram:**
```json
{
  "type": "send_message",
  "chat_id": 412587349,
  "thread_id": 42,
  "text": "Тесты пройдены ✅",
  "reply_to": 789,
  "parse_mode": "Markdown"
}
```

**Отправить файл:**
```json
{
  "type": "send_document",
  "chat_id": 412587349,
  "thread_id": 42,
  "file_path": "/home/user/projects/api/report.pdf",
  "caption": "Отчёт"
}
```

**Typing indicator:**
```json
{
  "type": "send_chat_action",
  "chat_id": 412587349,
  "thread_id": 42,
  "action": "typing"
}
```

**Реакция:**
```json
{
  "type": "react",
  "chat_id": 412587349,
  "message_id": 789,
  "emoji": "👀"
}
```

**Редактирование:**
```json
{
  "type": "edit_message",
  "chat_id": 412587349,
  "message_id": 800,
  "text": "Обновлённый текст"
}
```

### 10.4. Сообщения от Proxy к сессии

**Подтверждение регистрации:**
```json
{
  "type": "registered",
  "thread_id": 42
}
```

**Входящее сообщение:**
```json
{
  "type": "incoming_message",
  "message": {
    "message_id": 789,
    "thread_id": 42,
    "text": "Запусти тесты",
    "from": {
      "id": 412587349,
      "first_name": "User"
    }
  }
}
```

**Входящее фото:**
```json
{
  "type": "incoming_message",
  "message": {
    "message_id": 790,
    "thread_id": 42,
    "text": "",
    "caption": "Вот скриншот бага",
    "from": { "id": 412587349 },
    "photo": {
      "file_id": "AgACAgIAAxkB...",
      "file_path": "/tmp/claude-proxy/inbox/790_photo.jpg"
    }
  }
}
```

**Входящий документ:**
```json
{
  "type": "incoming_message",
  "message": {
    "message_id": 791,
    "thread_id": 42,
    "text": "",
    "from": { "id": 412587349 },
    "document": {
      "file_id": "BQACAgIAAxkB...",
      "file_name": "data.csv",
      "file_path": "/tmp/claude-proxy/inbox/791_data.csv"
    }
  }
}
```

---

## 11. Управление топиками

### 11.1. Создание топика

Пользователь в General-топике:
```
/new Backend API
```

Proxy:
1. Вызывает `bot.api.createForumTopic(chatId, "Backend API")`.
2. Получает `topic.message_thread_id` (например, 42).
3. Сохраняет в `topics.json`.
4. Отвечает пользователю:
   ```
   ✅ Топик "Backend API" создан (thread: 42).
   
   Запустите сессию:
   TELEGRAM_THREAD_ID=42 claude --channels plugin:telegram-multi
   ```

### 11.2. Список топиков

```
/list
```

Proxy отвечает:
```
📋 Топики:

• Backend API (thread: 42) — 🟢 сессия подключена
• Frontend (thread: 87) — 🔴 нет сессии
• DevOps (thread: 93) — 🟢 сессия подключена
```

Статус определяется по наличию подключённого сокета в IPC-сервере.

### 11.3. Топики, созданные пользователем вручную

Пользователь может создать топик прямо в Telegram (не через /new). В этом случае Proxy не знает об этом топике. Когда придёт первое сообщение из неизвестного топика, Proxy должен:

1. Автоматически добавить его в реестр (с именем из `forum_topic_created` service message, если доступно).
2. Ответить: "Этот топик не привязан к сессии. Запустите: `claude --channels ... --thread <id>`"

---

## 12. Контроль доступа

### 12.1. На уровне Proxy

Простой: только `OWNER_USER_ID` может пользоваться ботом.

```typescript
if (ctx.from?.id !== Number(process.env.OWNER_USER_ID)) {
  return; // Игнорировать
}
```

При необходимости — расширить до allowlist (массив ID в конфиге).

### 12.2. На уровне плагина

Оставить как есть из оригинального плагина (access.json, pairing и т.д.), но оно может быть избыточным, учитывая что Proxy уже фильтрует. Можно упростить.

### 12.3. Рекомендация для production

После настройки — в General-топике:
1. Залочить бота: `dmPolicy: allowlist`.
2. Убедиться, что `OWNER_USER_ID` в allowlist.
3. Strangers не получают никакого ответа от бота.

---

## 13. Обработка фото и файлов

### 13.1. Входящие (user → Claude Code)

**Proxy делает:**
1. Получает сообщение с `photo` или `document`.
2. Вызывает `bot.api.getFile(file_id)` — получает `file_path` на серверах Telegram.
3. Скачивает файл: `https://api.telegram.org/file/bot<token>/<file_path>`.
4. Сохраняет в `/tmp/claude-proxy/inbox/<message_id>_<filename>`.
5. Включает локальный путь в IPC-сообщение для сессии.

**Плагин в сессии Claude Code:**
- Получает путь к файлу.
- Формирует `<channel>` notification для Claude Code: "Получено фото: /tmp/claude-proxy/inbox/790_photo.jpg".
- Claude Code может прочитать файл как обычно (Read tool).

**Код в Proxy:**
```typescript
async function downloadFile(bot, fileId: string, messageId: number): Promise<string> {
  const file = await bot.api.getFile(fileId);
  if (!file.file_path) throw new Error("No file_path");

  const url = `https://api.telegram.org/file/bot${process.env.TELEGRAM_BOT_TOKEN}/${file.file_path}`;
  const ext = path.extname(file.file_path) || ".bin";
  const localPath = path.join("/tmp/claude-proxy/inbox", `${messageId}${ext}`);

  const response = await fetch(url);
  const buffer = Buffer.from(await response.arrayBuffer());

  await fs.promises.mkdir(path.dirname(localPath), { recursive: true });
  await fs.promises.writeFile(localPath, buffer);

  return localPath;
}
```

### 13.2. Исходящие (Claude Code → user)

Когда Claude Code вызывает tool `reply` с файлами:

**Плагин:**
1. Получает от Claude Code путь к файлу (абсолютный).
2. Отправляет через IPC:
   ```json
   { "type": "send_document", "file_path": "/home/user/projects/api/report.pdf", "thread_id": 42 }
   ```

**Proxy:**
1. Получает сообщение.
2. Создаёт `InputFile` из пути.
3. Вызывает `bot.api.sendDocument(chatId, new InputFile(filePath), { message_thread_id: 42 })`.

**Ограничение:** файл должен быть доступен Proxy по файловой системе. Если Proxy и Claude Code на одной машине — это работает. Если на разных — нужен другой механизм (передача через socket, base64). Но для нашего кейса (всё на одном сервере) — работает.

---

## 14. Сохранение контекста между перезапусками

### 14.1. Что уже есть

Внутри одной сессии Claude Code контекст сохраняется автоматически — это стандартное поведение. Пока tmux-окно открыто, сессия помнит всё.

### 14.2. Между перезапусками

**Вариант A (простой, рекомендуемый): CLAUDE.md**

Перед завершением сессии попросите Claude:
```
Перед тем как я тебя выключу — запиши ключевые моменты нашего разговора в CLAUDE.md
```

Claude Code запишет саммари в файл проекта. При следующем запуске он автоматически прочитает CLAUDE.md и будет в курсе.

**Вариант B (автоматический): Proxy логирует историю**

Proxy может опционально записывать все проходящие сообщения в SQLite:

```sql
CREATE TABLE messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER NOT NULL,
  direction TEXT NOT NULL,       -- 'in' или 'out'
  content TEXT NOT NULL,
  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

При рестарте сессии — загружать последние N сообщений и передавать как контекст. Но это усложняет Proxy и может быть реализовано позже.

**Рекомендация: начните с Варианта A. Вариант B — если будет реальная потребность.**

---

## 15. Развёртывание и запуск

### 15.1. Предварительная настройка (один раз)

```bash
# 1. Создать бота
# @BotFather → /newbot → получить токен
# Включить Threaded Mode в настройках бота

# 2. Установить Proxy
cd claude-telegram-multi/proxy
npm install
cp .env.example .env
# Вписать TELEGRAM_BOT_TOKEN и OWNER_USER_ID в .env

# 3. Установить модифицированный плагин
cd ../plugin/telegram
# Инструкция по установке плагина (зависит от структуры)
# Вероятно:
claude /plugin install ./path/to/plugin
# или скопировать в ~/.claude/plugins/
```

### 15.2. Ежедневный запуск

```bash
# Шаг 1: Запустить Proxy (один раз, живёт постоянно)
tmux new -s proxy
cd claude-telegram-multi/proxy
npm start
# Ctrl+B, D — отключиться от tmux

# Шаг 2: Создать топики через Telegram
# В General-топике бота:
#   /new Backend API
#   /new Frontend
#   /new DevOps
# Бот ответит thread_id для каждого.

# Шаг 3: Запустить сессии Claude Code
tmux new -s sessions

# Окно 1: Backend API
tmux new-window -t sessions -n api
cd /home/user/projects/api
TELEGRAM_THREAD_ID=42 claude --channels plugin:telegram-multi
# Ctrl+B, C — новое окно

# Окно 2: Frontend
tmux new-window -t sessions -n frontend
cd /home/user/projects/web
TELEGRAM_THREAD_ID=87 claude --channels plugin:telegram-multi

# Окно 3: DevOps
tmux new-window -t sessions -n devops
cd /home/user/infra
TELEGRAM_THREAD_ID=93 claude --channels plugin:telegram-multi

# Ctrl+B, D — отключиться
```

### 15.3. Скрипт быстрого запуска

`scripts/start-all.sh`:
```bash
#!/bin/bash

# Конфигурация
PROXY_DIR="$(dirname "$0")/../proxy"
SESSIONS=(
  "42|api|/home/user/projects/api"
  "87|frontend|/home/user/projects/web"
  "93|devops|/home/user/infra"
)

# Запустить Proxy
tmux new-session -d -s claude-proxy -c "$PROXY_DIR" "npm start"
echo "✅ Proxy started"
sleep 2

# Запустить сессии
for entry in "${SESSIONS[@]}"; do
  IFS='|' read -r thread_id name workdir <<< "$entry"
  tmux new-window -t claude-proxy -n "$name" \
    "cd $workdir && TELEGRAM_THREAD_ID=$thread_id claude --channels plugin:telegram-multi"
  echo "✅ Session '$name' started (thread: $thread_id, dir: $workdir)"
  sleep 1
done

echo ""
echo "All sessions started. Attach with: tmux attach -t claude-proxy"
```

### 15.4. systemd для Proxy (production)

```ini
[Unit]
Description=Claude Telegram Proxy
After=network.target

[Service]
Type=simple
User=claude
WorkingDirectory=/home/claude/claude-telegram-multi/proxy
ExecStart=/usr/bin/node dist/index.js
Restart=on-failure
RestartSec=5
Environment=NODE_ENV=production
EnvironmentFile=/home/claude/claude-telegram-multi/proxy/.env

[Install]
WantedBy=multi-user.target
```

Сессии Claude Code по-прежнему запускаются вручную через tmux (или тоже через systemd, если нужен автостарт).

---

## 16. Порядок реализации (фазы)

### Фаза 0: Исследование (2-4 часа)

**Обязательно выполнить до написания кода.**

- [ ] Склонировать https://github.com/anthropics/claude-plugins-official
- [ ] Изучить структуру `external_plugins/telegram/`: файлы, точки входа, как плагин подключается к Bot API, как общается с Claude Code через MCP.
- [ ] Создать тестового бота через @BotFather.
- [ ] Включить Threaded Mode для бота.
- [ ] Отправить сообщение в топик, проверить что `message_thread_id` приходит (можно простым скриптом на grammY).
- [ ] Проверить `claude --help` на предмет --channels, --pipe, plugin install.
- [ ] Запустить оригинальный плагин без изменений, убедиться что базовая связка работает.

### Фаза 1: Proxy — минимальный (1 день)

- [ ] Инициализация проекта (package.json, tsconfig).
- [ ] `bot.ts` — long polling, логирование всех входящих с thread_id.
- [ ] `ipc-server.ts` — Unix socket сервер, приём подключений.
- [ ] Маршрутизация: thread_id → socket.
- [ ] Тест: отправить сообщение в топик, proxy логирует thread_id, пересылает на сокет.

### Фаза 2: Плагин — форк и подключение к Proxy (1-2 дня)

- [ ] Форкнуть плагин.
- [ ] Добавить `TELEGRAM_THREAD_ID` в конфиг.
- [ ] Заменить long polling на подключение к Proxy через Unix socket.
- [ ] Добавить `message_thread_id` ко всем исходящим.
- [ ] Тест: одна сессия Claude Code подключена к одному топику, сообщения ходят в обе стороны.

### Фаза 3: Мульти-сессии (0.5 дня)

- [ ] Запустить 2-3 сессии с разными thread_id.
- [ ] Проверить: сообщения из разных топиков попадают в разные сессии.
- [ ] Проверить: ответы из разных сессий попадают в правильные топики.
- [ ] Проверить: typing indicator работает в правильном топике.

### Фаза 4: Команды в General (0.5 дня)

- [ ] `/new` — создание топика.
- [ ] `/list` — список топиков и статусы.
- [ ] `/help`.
- [ ] `topics.json` — персистентный реестр.

### Фаза 5: Файлы и polish (0.5-1 день)

- [ ] Скачивание фото/документов в Proxy.
- [ ] Передача пути файла в сессию.
- [ ] Отправка файлов из сессии через Proxy.
- [ ] Разбивка длинных сообщений (>4096).
- [ ] Graceful shutdown Proxy.
- [ ] Обработка отключения сессий (логирование, уведомление в топик).

### Фаза 6 (опционально): Persistence

- [ ] SQLite логирование в Proxy.
- [ ] Восстановление контекста при рестарте.

**Итого MVP: 3-4 дня работы.**

---

## 17. Справочные ссылки

### Telegram

| Ресурс | URL |
|--------|-----|
| Bot API — полная документация | https://core.telegram.org/bots/api |
| Bot API — changelog (Forum Topics) | https://core.telegram.org/bots/api-changelog |
| Forum Topics (MTProto) | https://core.telegram.org/api/forum |
| Bot Features | https://core.telegram.org/bots/features |
| Введение в ботов | https://core.telegram.org/bots |
| createForumTopic | https://core.telegram.org/bots/api#createforumtopic |
| sendMessage (message_thread_id) | https://core.telegram.org/bots/api#sendmessage |

### Существующий плагин

| Ресурс | URL |
|--------|-----|
| Репозиторий (весь) | https://github.com/anthropics/claude-plugins-official |
| Telegram README | https://github.com/anthropics/claude-plugins-official/blob/main/external_plugins/telegram/README.md |
| Telegram ACCESS | https://github.com/anthropics/claude-plugins-official/blob/main/external_plugins/telegram/ACCESS.md |
| Код плагина | https://github.com/anthropics/claude-plugins-official/tree/main/external_plugins/telegram |

### Claude Code

| Ресурс | URL |
|--------|-----|
| Документация | https://docs.claude.com |
| Anthropic API | https://docs.anthropic.com/en/docs |
| SDK (npm) | https://www.npmjs.com/package/@anthropic-ai/sdk |

### Библиотеки для Proxy

| Библиотека | Назначение | URL |
|------------|-----------|-----|
| grammY | Telegram Bot Framework | https://grammy.dev/ |
| dotenv | Переменные окружения | https://www.npmjs.com/package/dotenv |
| better-sqlite3 | SQLite (для Фазы 6) | https://www.npmjs.com/package/better-sqlite3 |

### Полезное

| Ресурс | URL |
|--------|-----|
| @BotFather | https://t.me/BotFather |
| @userinfobot (узнать user_id) | https://t.me/userinfobot |
| @RawDataBot (узнать chat_id группы) | https://t.me/RawDataBot |

---

## 18. Примеры сценариев от начала до конца

### Сценарий 1: Первый запуск с нуля

```
═══ ПОДГОТОВКА (один раз) ═══

1. @BotFather → /newbot → "Claude Multi" → "claude_multi_bot"
   Получаем токен: 123456789:AAHfiqksKZ8...

2. @BotFather → настройки claude_multi_bot → включить Threaded Mode

3. @userinfobot → узнаём свой ID: 412587349

4. Устанавливаем Proxy на сервере:
   $ git clone <repo>
   $ cd claude-telegram-multi/proxy
   $ npm install
   $ echo "TELEGRAM_BOT_TOKEN=123456789:AAHfiqksKZ8..." > .env
   $ echo "OWNER_USER_ID=412587349" >> .env

5. Устанавливаем модифицированный плагин:
   $ claude /plugin install ./plugin/telegram-multi

═══ ЗАПУСК ═══

6. $ tmux new -s claude
   $ cd claude-telegram-multi/proxy && npm start
   > Proxy started. Waiting for sessions to connect...

7. Открываем Telegram, пишем боту в General:
   > /new Backend API
   < ✅ Топик "Backend API" создан (thread: 42).
   < Запустите: TELEGRAM_THREAD_ID=42 claude --channels plugin:telegram-multi

8. $ tmux new-window -n api
   $ cd /home/user/projects/api
   $ TELEGRAM_THREAD_ID=42 claude --channels plugin:telegram-multi
   > [Claude Code запускается, плагин подключается к Proxy]
   > Proxy: Session registered for thread 42

9. В Telegram, вкладка "Backend API":
   > Привет! Покажи структуру проекта
   < [Claude Code выполняет tree, отвечает в этот же топик]
   < src/
   <   ├── index.ts
   <   ├── routes/
   <   └── models/
   < ...

═══ ДОБАВЛЕНИЕ ВТОРОЙ СЕССИИ ═══

10. В General:
    > /new Frontend
    < ✅ Топик "Frontend" создан (thread: 87).

11. $ tmux new-window -n frontend
    $ cd /home/user/projects/web
    $ TELEGRAM_THREAD_ID=87 claude --channels plugin:telegram-multi

12. Теперь в Telegram два топика-вкладки.
    Пишем во "Frontend": "Какие есть React-компоненты?"
    Claude Code из сессии frontend отвечает — только в этот топик.

    Переключаемся на "Backend API": "Запусти npm test"
    Claude Code из сессии api отвечает — только в этот топик.
```

### Сценарий 2: Перезапуск сессии

```
1. Сессия "Backend API" зависла или нужно перезапустить.

2. В tmux: Ctrl+C в окне "api" (убить Claude Code).
   Proxy видит: "Session for thread 42 disconnected"
   В Telegram в топике "Backend API":
   (при следующем сообщении) "⚠️ Нет подключённой сессии..."

3. В tmux, то же окно:
   $ TELEGRAM_THREAD_ID=42 claude --channels plugin:telegram-multi
   Proxy: "Session registered for thread 42"

4. Сессия работает снова. Контекст предыдущего разговора потерян
   (если не сохранён в CLAUDE.md).
```

### Сценарий 3: Проверка статуса

```
В General:
> /list

< 📋 Топики:
<
< • Backend API (thread: 42) — 🟢 сессия подключена
< • Frontend (thread: 87) — 🟢 сессия подключена
< • DevOps (thread: 93) — 🔴 нет сессии
```

### Сценарий 4: Отправка фото

```
1. Пользователь отправляет скриншот бага в топик "Frontend" (thread: 87).

2. Proxy:
   - Получает message с photo.
   - Скачивает файл через Bot API.
   - Сохраняет: /tmp/claude-proxy/inbox/790_photo.jpg
   - Пересылает в сессию через IPC:
     { type: "incoming_message", message: { ..., photo: { file_path: "/tmp/..." } } }

3. Плагин в сессии:
   - Получает сообщение с путём к фото.
   - Передаёт в Claude Code: "Получено фото: /tmp/claude-proxy/inbox/790_photo.jpg"
   - Claude Code читает файл, анализирует скриншот.

4. Claude Code отвечает в топик "Frontend":
   "Вижу — кнопка выезжает за границу контейнера. Проблема в overflow..."
```

---

## 19. Чеклист перед началом кодирования

### Обязательные проверки

- [ ] **Threaded Mode работает.** Создать бота, включить Threaded Mode, отправить сообщение в топик. Убедиться, что в Update приходит `message_thread_id`.

- [ ] **Структура плагина изучена.** Склонировать https://github.com/anthropics/claude-plugins-official, изучить `external_plugins/telegram/`. Понять:
  - Какие файлы есть?
  - Где точка входа?
  - Как плагин подключается к Telegram (grammY? Telegraf? raw API?)?
  - Как реализованы tools (reply, react, edit)?
  - Как плагин общается с Claude Code (MCP protocol)?
  - Где обрабатываются входящие сообщения?

- [ ] **Оригинальный плагин работает.** Запустить без изменений, убедиться что связка Claude Code ↔ Telegram работает.

- [ ] **grammY поддерживает Forum Topics.** Установить grammY, написать минимальный скрипт:
  ```typescript
  import { Bot } from "grammy";
  const bot = new Bot("TOKEN");
  bot.on("message", (ctx) => {
    console.log("thread_id:", ctx.message.message_thread_id);
    ctx.reply("echo: " + ctx.message.text, {
      message_thread_id: ctx.message.message_thread_id
    });
  });
  bot.start();
  ```
  Проверить, что сообщения из топиков корректно получают и отправляют thread_id.

- [ ] **Unix sockets работают.** Написать минимальный тест: сервер + клиент, обмен JSON через сокет.

- [ ] **Claude Code принимает кастомные плагины.** Проверить:
  ```bash
  claude /plugin install <path>
  claude /plugin list
  ```

### Возможные проблемы и их решения

| Проблема | Решение |
|----------|---------|
| Threaded Mode не включается | Проверить, доступна ли фича для вашего бота. Возможно, нужна оплата Telegram Stars. |
| grammY не передаёт thread_id | Обновить grammY до последней версии. Forum Topics поддерживаются с v1.x. |
| Claude Code не принимает модифицированный плагин | Изучить формат плагинов. Возможно, плагин должен быть в определённой структуре или опубликован. |
| Unix sockets не работают (Windows) | Использовать TCP localhost:port вместо Unix sockets. Или использовать named pipes Windows. |
| Proxy не может отправить файл из сессии | Убедиться, что Proxy имеет доступ к файловой системе сессии (одна машина = ОК). |
| Бот не получает сообщения из топиков | Проверить, что Threaded Mode включён. Проверить, что бот имеет нужные права. |

---

**Конец спецификации.**