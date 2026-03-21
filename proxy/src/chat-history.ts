import { Database } from 'bun:sqlite'
import { resolve } from 'path'

export interface ChatMessage {
  id: number
  chat_id: number
  message_id: number
  thread_id: number | null
  user_id: number
  username: string
  first_name: string
  text: string
  ts: string
}

export class ChatHistory {
  private db: Database

  constructor(dataDir: string) {
    const dbPath = resolve(dataDir, 'chat-history.sqlite')
    this.db = new Database(dbPath)
    this.db.exec('PRAGMA journal_mode=WAL')
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        message_id INTEGER NOT NULL,
        thread_id INTEGER,
        user_id INTEGER NOT NULL,
        username TEXT NOT NULL DEFAULT '',
        first_name TEXT NOT NULL DEFAULT '',
        text TEXT NOT NULL DEFAULT '',
        has_photo INTEGER NOT NULL DEFAULT 0,
        has_document INTEGER NOT NULL DEFAULT 0,
        has_voice INTEGER NOT NULL DEFAULT 0,
        ts TEXT NOT NULL,
        UNIQUE(chat_id, message_id)
      )
    `)
    this.db.exec(`
      CREATE INDEX IF NOT EXISTS idx_messages_chat_ts ON messages(chat_id, ts DESC)
    `)
  }

  save(msg: {
    chat_id: number
    message_id: number
    thread_id?: number
    user_id: number
    username?: string
    first_name?: string
    text: string
    has_photo?: boolean
    has_document?: boolean
    has_voice?: boolean
  }): void {
    this.db.run(
      `INSERT OR REPLACE INTO messages (chat_id, message_id, thread_id, user_id, username, first_name, text, has_photo, has_document, has_voice, ts)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        msg.chat_id,
        msg.message_id,
        msg.thread_id ?? null,
        msg.user_id,
        msg.username || '',
        msg.first_name || '',
        msg.text.slice(0, 2000),
        msg.has_photo ? 1 : 0,
        msg.has_document ? 1 : 0,
        msg.has_voice ? 1 : 0,
        new Date().toISOString(),
      ],
    )
  }

  getRecent(chatId: number, limit: number = 15): ChatMessage[] {
    return this.db.query(
      `SELECT id, chat_id, message_id, thread_id, user_id, username, first_name, text, ts
       FROM messages WHERE chat_id = ? ORDER BY ts DESC LIMIT ?`,
    ).all(chatId, limit) as ChatMessage[]
  }
}
