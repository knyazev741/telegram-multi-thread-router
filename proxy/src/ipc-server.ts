import net from 'net'
import { mkdirSync, existsSync, unlinkSync } from 'fs'
import { join } from 'path'
import type { ConnectedSession, SessionToProxy, ProxyToSession } from './types.js'

export class IPCServer {
  private sessions: Map<number, ConnectedSession> = new Map()
  private server: net.Server
  private outgoingHandler: ((msg: SessionToProxy) => Promise<void>) | null = null

  constructor(socketDir: string) {
    mkdirSync(socketDir, { recursive: true })
    const controlSocket = join(socketDir, 'control.sock')

    if (existsSync(controlSocket)) {
      unlinkSync(controlSocket)
    }

    this.server = net.createServer(socket => {
      let buffer = ''

      socket.on('data', data => {
        buffer += data.toString()
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.trim()) continue
          try {
            const msg = JSON.parse(line) as SessionToProxy
            this.handleSessionMessage(socket, msg)
          } catch (e) {
            console.error('[IPC] Invalid JSON from session:', e)
          }
        }
      })

      socket.on('close', () => {
        for (const [threadId, session] of this.sessions) {
          if (session.socket === socket) {
            console.log(`[IPC] Session for thread ${threadId} disconnected`)
            this.sessions.delete(threadId)
            break
          }
        }
      })

      socket.on('error', err => {
        console.error('[IPC] Socket error:', err.message)
      })
    })

    this.server.listen(controlSocket, () => {
      console.log(`[IPC] Listening on ${controlSocket}`)
    })
  }

  private handleSessionMessage(socket: net.Socket, msg: SessionToProxy) {
    switch (msg.type) {
      case 'register': {
        const { thread_id, chat_id } = msg
        this.sessions.set(thread_id, {
          threadId: thread_id,
          chatId: chat_id,
          socket,
          connectedAt: new Date(),
        })
        console.log(`[IPC] Session registered: thread=${thread_id}, chat=${chat_id}`)
        this.sendToSocket(socket, { type: 'registered', thread_id, chat_id })
        break
      }
      case 'send_message':
      case 'send_photo':
      case 'send_document':
      case 'send_chat_action':
      case 'react':
      case 'edit_message':
        if (this.outgoingHandler) {
          this.outgoingHandler(msg).catch(err => {
            console.error(`[IPC] Outgoing handler error:`, err.message)
          })
        }
        break
    }
  }

  getSession(threadId: number): ConnectedSession | undefined {
    return this.sessions.get(threadId)
  }

  sendToSession(threadId: number, msg: ProxyToSession): boolean {
    const session = this.sessions.get(threadId)
    if (!session) return false
    return this.sendToSocket(session.socket, msg)
  }

  private sendToSocket(socket: net.Socket, msg: ProxyToSession): boolean {
    try {
      socket.write(JSON.stringify(msg) + '\n')
      return true
    } catch (e) {
      console.error('[IPC] Failed to write to socket:', e)
      return false
    }
  }

  onOutgoing(handler: (msg: SessionToProxy) => Promise<void>) {
    this.outgoingHandler = handler
  }

  getConnectedSessions(): Array<{ threadId: number; chatId: string; connectedAt: Date }> {
    return Array.from(this.sessions.values()).map(s => ({
      threadId: s.threadId,
      chatId: s.chatId,
      connectedAt: s.connectedAt,
    }))
  }

  closeAll() {
    for (const session of this.sessions.values()) {
      session.socket.end()
    }
    this.server.close()
  }
}
