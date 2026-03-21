/** Messages from session → proxy (outgoing to Telegram) */
export type SessionToProxy =
  | { type: 'register'; thread_id: number; chat_id: string }
  | { type: 'send_message'; chat_id: string; thread_id: number; text: string; reply_to?: number; parse_mode?: string }
  | { type: 'send_photo'; chat_id: string; thread_id: number; file_path: string; caption?: string; reply_to?: number }
  | { type: 'send_document'; chat_id: string; thread_id: number; file_path: string; caption?: string; reply_to?: number }
  | { type: 'send_chat_action'; chat_id: string; thread_id: number; action: string }
  | { type: 'react'; chat_id: string; message_id: number; emoji: string }
  | { type: 'edit_message'; chat_id: string; message_id: number; text: string; parse_mode?: string }

/** Messages from proxy → session (incoming from Telegram) */
export type ProxyToSession =
  | { type: 'registered'; thread_id: number; chat_id: string }
  | { type: 'incoming_message'; message: IncomingMessage }

export interface IncomingMessage {
  message_id: number
  thread_id: number
  chat_id: string
  text: string
  caption?: string
  from: {
    id: number
    first_name: string
    username?: string
  }
  photo?: { file_id: string; file_path?: string }
  document?: { file_id: string; file_name: string; file_path?: string }
  voice?: { file_id: string; file_path?: string; duration: number; transcription?: string }
  /** Recent chat messages for context (group chat mode) */
  recent_messages?: Array<{
    from: string
    text: string
    ts: string
  }>
}

export interface TopicEntry {
  threadId: number
  name: string
  createdAt: string
}

export interface ConnectedSession {
  threadId: number
  chatId: string
  socket: import('net').Socket
  connectedAt: Date
}
