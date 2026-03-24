# Phase 5: Voice and File I/O - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Delivers voice transcription (faster-whisper), photo/document input forwarding to Claude, and custom MCP tools for Claude to send output back to Telegram (reply, send_file, react, edit_message).

</domain>

<decisions>
## Implementation Decisions

### Voice & File Input
- Voice transcription via faster-whisper in-process using asyncio.to_thread
- Whisper model: medium (matches current project setting)
- Concurrent transcription: Semaphore(1) — one at a time to prevent OOM
- Files downloaded to session workdir, path sent as text via client.query()

### MCP Output Tools
- Implemented via create_sdk_mcp_server() with @tool decorator — runs in-process
- 4 tools: reply(text), send_file(path), react(emoji, message_id), edit_message(text, message_id)
- Bot reference passed via closure when creating MCP server
- File size limit: 50MB check before sending (Telegram limit)

### Claude's Discretion
- Exact faster-whisper initialization parameters (beam_size, compute_type, language)
- MCP tool parameter schemas and descriptions
- How to format transcription result before sending to Claude
- Error handling for failed transcriptions or file downloads

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/sessions/runner.py` — SessionRunner with ClaudeAgentOptions, can add mcp_servers
- `src/bot/routers/session.py` — session router, add voice/photo/document handlers
- `src/bot/dispatcher.py` — build_dispatcher() with DI

### Established Patterns
- aiogram message handlers with content type filters
- Bot.download for file downloads
- asyncio.to_thread for blocking operations
- ClaudeAgentOptions.mcp_servers for in-process MCP servers

### Integration Points
- SessionRunner needs MCP server passed to ClaudeAgentOptions.mcp_servers
- Session router needs voice, photo, document message handlers
- MCP tools need Bot + thread_id to send messages back

</code_context>

<specifics>
## Specific Ideas

- faster-whisper: WhisperModel("medium", compute_type="int8", device="cpu")
- Voice handler: download .ogg → transcribe → send text to runner.enqueue()
- Photo handler: download → save to workdir → "User sent photo: {path}" to runner.enqueue()
- Document handler: download → save to workdir → "User sent file: {name} at {path}" to runner.enqueue()

</specifics>

<deferred>
## Deferred Ideas

None — phase scope is well-defined

</deferred>
