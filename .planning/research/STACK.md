# Stack Research

**Domain:** Python Telegram bot managing AI agent sessions via Claude Agent SDK
**Researched:** 2026-03-24
**Confidence:** HIGH (all versions verified against PyPI and official docs)

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.11+ | Runtime | 3.11 is the sweet spot: faster than 3.10, widely supported, aiogram 3.26 + claude-agent-sdk 0.1.50 both support it. 3.12/3.13 also fine but 3.11 has widest compatibility with ctranslate2 for faster-whisper. |
| aiogram | 3.26.0 | Telegram Bot framework | The only actively-maintained async Python Telegram library with full forum topics support (`message_thread_id`). Native asyncio, dependency injection, router-based handler organisation. Competitor python-telegram-bot uses threads not asyncio. |
| claude-agent-sdk | 0.1.50 | Claude Code session control | Official Anthropic SDK. Provides `ClaudeSDKClient` for interactive bidirectional sessions, `can_use_tool` for programmatic permission handling, `create_sdk_mcp_server` for in-process MCP tools. No alternatives exist for this capability. |
| aiosqlite | 0.22.1 | Persistent state storage | Async wrapper around sqlite3. Single-file, zero-infra, survives restarts. Right choice for single-owner bot with modest write volume. Pairs directly with asyncio without thread pool contention. |
| uvloop | 0.22.1 | Asyncio event loop | 2-4x faster than built-in asyncio event loop. Drop-in replacement: `uvloop.install()` at startup. Production-proven — Azure Functions adopted it as default in 2025. Required for a bot handling concurrent Claude sessions with streaming. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| faster-whisper | 1.2.1 | Voice transcription | Reimplementation of Whisper via CTranslate2, 4x faster than openai/whisper, 8-bit quantization on CPU and GPU. Use for voice messages → text conversion. Use `medium` model for accuracy/speed balance on CPU. |
| msgspec | 0.20.0 | TCP wire serialisation | Fastest Python MessagePack + JSON serialiser with schema validation via Struct types. Use for encoding/decoding messages between central bot and workers over TCP. Zero-cost type validation prevents wire protocol bugs. |
| python-dotenv | 1.x | Environment config | Load `.env` into `os.environ`. Required for separating secrets (BOT_TOKEN, AUTH_TOKEN, OWNER_USER_ID) from code. |
| structlog | 24.x | Structured logging | JSON-structured log output. Integrates with asyncio contexts. Better than stdlib logging for correlating events per session/topic. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| uv | Dependency management and virtualenv | Fastest Python package manager (replaces pip + venv). `uv sync` is the install command. Creates `pyproject.toml`-based projects. Use `uv add` not `pip install`. |
| ruff | Linting + formatting | Replaces flake8 + black + isort in one tool. 100x faster than black. Configure in `pyproject.toml`. |
| pytest-asyncio | Testing async code | Required for testing aiogram handlers and SDK interactions. Set `asyncio_mode = "auto"` in pytest config. |

## Installation

```bash
# Create project
uv init telegram-agent-bot
cd telegram-agent-bot

# Core
uv add aiogram==3.26.0
uv add claude-agent-sdk==0.1.50
uv add aiosqlite==0.22.1
uv add uvloop==0.22.1
uv add faster-whisper==1.2.1
uv add msgspec==0.20.0
uv add python-dotenv
uv add structlog

# Dev
uv add --dev ruff pytest pytest-asyncio
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| aiosqlite | SQLModel + SQLAlchemy async | Only if you need ORM query building, multi-table JOINs at scale, or plan to migrate to PostgreSQL. For this project's simple key-value style access (topic→session, session history), aiosqlite with raw SQL is less overhead. |
| aiosqlite | SQLite via asyncio.to_thread | Technically works but loses connection lifecycle management. aiosqlite handles the thread-per-connection model correctly. |
| msgspec | msgpack-python | msgpack-python has no schema validation. msgspec provides both serialisation AND struct validation in one library with better performance. |
| msgspec | JSON over TCP | JSON is text, larger on wire, slower to parse. For internal TCP between bot↔worker, binary msgpack is strictly better. |
| uvloop | asyncio default loop | Fine for development or very low traffic. In production with multiple concurrent Claude sessions + streaming, uvloop's libuv backend handles I/O multiplexing more efficiently. |
| faster-whisper | openai-whisper | openai-whisper is 4x slower and uses more memory. faster-whisper uses CTranslate2 for quantized inference. No reason to use openai-whisper in new code. |
| faster-whisper | Whisper API (cloud) | Cloud transcription has latency, cost per call, and privacy concerns. Local inference is better for a personal bot. |
| systemd | Docker | Docker adds complexity with no benefit for single-server personal bot. systemd is already present on the target servers. Use Docker only if you need cross-OS portability or CI/CD pipelines. |
| systemd | supervisor | supervisor is a Python 2-era tool, still functional but systemd is the modern standard on Linux. Use supervisor only on systems without systemd. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| python-telegram-bot | Uses threading model, not native asyncio. Creates thread-per-update, which causes impedance mismatch when bridging to asyncio-native claude-agent-sdk. | aiogram 3 |
| telepot | Abandoned, Python 2 era, no forum topics support. | aiogram 3 |
| SQLModel | ORM abstraction is overkill for this project. SQLModel's async support requires SQLAlchemy async engine setup, which is significantly more boilerplate for simple read/write patterns. | aiosqlite with raw SQL |
| threading.Thread for SDK sessions | claude-agent-sdk uses asyncio streams internally. Mixing threads with the SDK creates race conditions. All session management must run in the asyncio event loop. | asyncio.create_task + task groups |
| --dangerously-skip-permissions | The old approach. claude-agent-sdk provides `can_use_tool` callback for proper permission control. No reason to bypass. | `can_use_tool` in `ClaudeAgentOptions` |
| openai-whisper | 4x slower than faster-whisper, higher memory usage, no CTranslate2 quantization support. | faster-whisper |
| Celery / task queues | Overkill for single-owner bot. Introduces Redis/RabbitMQ dependency. asyncio task groups handle concurrent sessions natively. | asyncio.TaskGroup |
| WebSockets for bot↔worker | WebSockets add HTTP upgrade handshake overhead and require an HTTP server. Plain asyncio TCP streams are simpler and sufficient for internal IPC. | asyncio.start_server / open_connection |

## Stack Patterns by Variant

**Single-server deployment (bot + worker on same machine):**
- Skip TCP entirely, call worker functions directly via asyncio tasks
- Saves the auth token / TCP framing complexity
- Relevant when you only ever use one server

**Multi-server deployment (bot on VPS, workers on dev machines):**
- TCP with length-prefix framing + msgspec encoding (see Architecture)
- AUTH_TOKEN checked on connection to prevent unauthorized workers
- Each worker connects to bot on startup and holds the connection

**CPU-only voice transcription (no GPU):**
- Use `faster-whisper` with `device="cpu"`, `compute_type="int8"`
- Model: `medium` for accuracy, `small` for speed on weak hardware
- Transcription runs in `asyncio.to_thread()` to avoid blocking event loop

**GPU voice transcription (NVIDIA GPU available):**
- Use `device="cuda"`, `compute_type="float16"`
- Requires CUDA 12 + cuDNN 9 installed on the system
- Significantly faster — can use `large-v3` model

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| faster-whisper 1.2.1 | Python 3.9–3.11 | ctranslate2 only supports CUDA 12 + cuDNN 9 for GPU; for older CUDA, pin `ctranslate2==4.4.0` |
| claude-agent-sdk 0.1.50 | Python 3.10–3.13 | Python 3.10 minimum is a hard requirement from Anthropic |
| aiogram 3.26.0 | Python 3.10–3.14 | Full forum topics support present since 3.x; `message_thread_id` maps to forum topic |
| uvloop 0.22.1 | Python 3.8–3.14 | Not available on Windows; Linux/macOS only — fine for server deployment |
| msgspec 0.20.0 | Python 3.9–3.14 | Binary msgpack encoding; use `Struct` subclasses as message schemas |
| aiosqlite 0.22.1 | Python 3.9+ | Wraps stdlib sqlite3; connection is not thread-safe, must use within single event loop |

## Key Integration Notes

### claude-agent-sdk Session Lifecycle
```python
# ClaudeSDKClient maintains state across multiple query() calls
async with ClaudeSDKClient() as client:
    # can_use_tool fires BEFORE tool execution, returns Allow or Deny
    options = ClaudeAgentOptions(
        can_use_tool=your_permission_handler,  # async callable
        resume="session-id",                   # resume after restart
        working_directory="/path/to/project",
    )
    await client.connect(options=options)
    await client.query("Do the task")
    async for msg in client.receive_response():
        # TextBlock, ToolUseBlock, ToolResultBlock, ResultMessage
        ...
```

### aiogram Forum Topics Routing
```python
# message_thread_id IS the forum topic ID
# Use it as the session key in your session manager
@router.message(F.chat.id == GROUP_CHAT_ID)
async def handle_message(message: Message):
    topic_id = message.message_thread_id  # None for main topic
    session = session_manager.get(topic_id)
```

### TCP Wire Protocol (bot ↔ worker)
```python
# Length-prefix framing + msgspec msgpack
import struct
import msgspec

encoder = msgspec.msgpack.Encoder()
decoder = msgspec.msgpack.Decoder(WorkerMessage)

async def send_msg(writer, msg):
    data = encoder.encode(msg)
    writer.write(struct.pack(">I", len(data)) + data)
    await writer.drain()

async def recv_msg(reader):
    length_bytes = await reader.readexactly(4)
    length = struct.unpack(">I", length_bytes)[0]
    data = await reader.readexactly(length)
    return decoder.decode(data)
```

### faster-whisper in Asyncio
```python
# Run in thread to avoid blocking event loop
from faster_whisper import WhisperModel
import asyncio

model = WhisperModel("medium", device="cpu", compute_type="int8")

async def transcribe(audio_path: str) -> str:
    segments, _ = await asyncio.to_thread(
        model.transcribe, audio_path, beam_size=5
    )
    return " ".join(s.text for s in segments)
```

## Sources

- [PyPI: claude-agent-sdk 0.1.50](https://pypi.org/project/claude-agent-sdk/) — version, Python requirements — HIGH confidence
- [Claude Agent SDK Python Reference](https://platform.claude.com/docs/en/agent-sdk/python) — ClaudeSDKClient API, can_use_tool, create_sdk_mcp_server — HIGH confidence
- [PyPI: aiogram 3.26.0](https://pypi.org/project/aiogram/) — version, Python requirements — HIGH confidence
- [aiogram docs: Middlewares](https://docs.aiogram.dev/en/latest/dispatcher/middlewares.html) — middleware patterns — HIGH confidence
- [aiogram docs: Router](https://docs.aiogram.dev/en/latest/dispatcher/router.html) — router patterns — HIGH confidence
- [aiogram docs: Forum Topics](https://docs.aiogram.dev/en/latest/api/types/forum_topic.html) — message_thread_id — HIGH confidence
- [PyPI: aiosqlite 0.22.1](https://pypi.org/project/aiosqlite/) — version, Python requirements — HIGH confidence
- [PyPI: faster-whisper 1.2.1](https://pypi.org/project/faster-whisper/) — version, CUDA requirements — HIGH confidence
- [PyPI: uvloop 0.22.1](https://pypi.org/project/uvloop/) — version, Python requirements — HIGH confidence
- [PyPI: msgspec 0.20.0](https://pypi.org/project/msgspec/) — version, Python requirements — HIGH confidence
- [Python asyncio Streams docs](https://docs.python.org/3/library/asyncio-stream.html) — TCP server/client patterns — HIGH confidence
- WebSearch: aiogram FSM, deployment patterns — MEDIUM confidence (consistent with official docs)

---
*Stack research for: Python Telegram bot managing Claude Code sessions via Agent SDK*
*Researched: 2026-03-24*
