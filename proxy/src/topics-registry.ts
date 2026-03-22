import { readFileSync, writeFileSync, mkdirSync } from 'fs'
import { join, dirname } from 'path'
import type { TopicEntry } from './types.js'

export class TopicsRegistry {
  private topics: TopicEntry[] = []
  private filePath: string

  constructor(dataDir: string) {
    this.filePath = join(dataDir, 'topics.json')
    mkdirSync(dirname(this.filePath), { recursive: true })
    this.load()
  }

  private load() {
    try {
      const data = readFileSync(this.filePath, 'utf-8')
      this.topics = JSON.parse(data)
    } catch {
      this.topics = []
    }
  }

  private save() {
    writeFileSync(this.filePath, JSON.stringify(this.topics, null, 2))
  }

  add(threadId: number, name: string, meta?: { server?: TopicEntry['server']; workdir?: string; sessionId?: string }) {
    // Don't duplicate
    if (this.topics.some(t => t.threadId === threadId)) return
    this.topics.push({ threadId, name, createdAt: new Date().toISOString(), ...meta })
    this.save()
  }

  updateMeta(threadId: number, meta: { server?: TopicEntry['server']; workdir?: string; sessionId?: string }) {
    const topic = this.topics.find(t => t.threadId === threadId)
    if (!topic) return
    Object.assign(topic, meta)
    this.save()
  }

  get(threadId: number): TopicEntry | null {
    return this.topics.find(t => t.threadId === threadId) ?? null
  }

  remove(threadId: number) {
    this.topics = this.topics.filter(t => t.threadId !== threadId)
    this.save()
  }

  getAll(): TopicEntry[] {
    return [...this.topics]
  }

  getName(threadId: number): string | null {
    return this.topics.find(t => t.threadId === threadId)?.name ?? null
  }

  has(threadId: number): boolean {
    return this.topics.some(t => t.threadId === threadId)
  }
}
