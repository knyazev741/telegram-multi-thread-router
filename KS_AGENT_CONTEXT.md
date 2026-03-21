# КС-Агент: Полный контекст и инструкция

## 1. Что такое Князь-Сервис (КС)

**КС (KnyazService)** — платформа рекламы в Telegram, работающая 8+ лет. Позволяет клиентам размещать рекламу в Telegram-чатах через управляемые аккаунты (сессии).

### Бизнес-процесс
1. Клиент создаёт заказ (рекламный пост + параметры)
2. Система подбирает релевантные чаты (вручную или через AI-Manager)
3. Заказу назначается свободная сессия (Telegram-аккаунт)
4. Worker подключается к Telegram, настраивает профиль сессии, вступает в чаты
5. Worker рассылает посты по расписанию (интервал в секундах)
6. Входящие ЛС пересылаются менеджеру, ответы — обратно клиенту
7. Заказ можно паузить, возобновлять, останавливать

---

## 2. Инфраструктура

### Продакшн КС-сервер
**IP**: `136.243.13.167` | **hostname**: `ks` (Hetzner)
- SSH: `ssh -i ~/.ssh/root_key root@136.243.13.167`
- КС Docker стек: `/opt/ks2/`
- AI-Manager: `/opt/ai-manager/`
- Admin API: `/opt/ks_admin_api/`
- Admin Mini App: `/opt/ks_admin_mini_app/`
- ks-go: `/opt/ks-go/`
- AppOrbit: `/opt/apporbit/`
- Graylog: `/opt/graylog/`
- Traefik: `/opt/traefik/`
- MinIO: `/opt/minio/`
- Metabase: `/opt/metabase/`

**ВАЖНО**: Это ПРОДАКШН. Только чтение! Никаких изменений, билдов, деплоев.

### Сервер менеджеров (ksmanagers)
**IP**: `49.13.171.170` | **hostname**: `ksmanagers` (Hetzner)
- SSH: `ssh -i ~/.ssh/root_key root@49.13.171.170`
- telegram_manager стек: `/opt/managers/`
- БД: MariaDB 10.11 (ks_managers), контейнер `ks_managers_db`

**Контейнеры:**
- `ks_manager_knyazservicesupport` — основной менеджер (ID 2002668410, +79080876288)
- `ks_manager_knyazoriginal` — knyazoriginal (ID 1376673043, +79622064817)
- `ks_manager_knyaz_design` — дизайн (ID 1289336682, +79095939064)
- `ks_manager_bhelp` — помощник (ID 901136096, +79214218891)

**Активные аккаунты:**
- Основной (2002668410): ~150K сообщений, ~130/день, 47 чатов/неделя
- Запасной (7258017655): пока не в системе telegram_manager

### Тестовый стенд
**IP**: `116.203.112.192` (бизнес-сервер)
- SSH: `ssh business-server` (ключ `~/.ssh/root_key`)
- Тестовый КС стек: `/opt/ks/`
- Тестовый AI-Manager: `/root/AI-Manager/`
- AutoPrem (бот + БД): там же

### Docker-контейнеры на продакшн КС-сервере (136.243.13.167)

**КС core:**
| Контейнер | Назначение |
|-----------|-----------|
| `ks-api` | REST API (FastAPI) |
| `ks-bot` | Telegram бот (Pylogram) |
| `ks-orchestrator` | Supervisor для worker процессов (порт 8087) |
| `ks-celery` | Фоновые задачи (Celery + RabbitMQ) |
| `ks-flower` | Celery мониторинг (порт 5555) |
| `ks_admin_api` | Admin API (FastAPI) |
| `ks_admin_mini_app` | TMA фронтенд |
| `ks2-db-1` | MariaDB (порт 3306) |
| `ks2-redis-1` | Redis (порт 6379) |
| `ks2-rabbitmq-1` | RabbitMQ (порт 5672) |
| `ks2-mongo-1` | MongoDB (порт 27017) |

**AI-Manager:**
| Контейнер | Назначение |
|-----------|-----------|
| `ai-manager-api-1` | FastAPI API (порт 8000) |
| `ai-manager-celery_worker-1` | Основной worker |
| `ai-manager-celery_worker_ai-1` | AI worker (LLM) |
| `ai-manager-celery_worker_fetch-1` | Fetch worker |
| `ai-manager-celery_beat-1` | Планировщик |
| `ai-manager-mysql-1` | MySQL 8.0 |
| `ai-manager-redis-1` | Redis |
| `ai-manager-qdrant-1` | Qdrant (вектора) |
| `ai-manager-backup-service-1` | Бэкапы |
| `ai-manager-backup-monitor-1` | Мониторинг бэкапов |

**Инфраструктура:**
| Контейнер | Назначение |
|-----------|-----------|
| `traefik` | Reverse proxy (80, 443) |
| `grafana` | Дашборды (порт 3000) |
| `prometheus` | Метрики (порт 9090) |
| `graylog` | Логирование (порт 9000) |
| `graylog_elasticsearch` | Поиск логов |
| `graylog_mongodb` | Хранение логов |
| `minio` | S3 файловое хранилище (порт 9000) |
| `metabase` | BI/аналитика |
| `telegram-bot-api` | Локальный Bot API сервер |

**AppOrbit:**
| Контейнер | Назначение |
|-----------|-----------|
| `apporbit` | Бэкенд |
| `apporbit-bot` | Telegram бот |
| `apporbit-celery` | Фоновые задачи |
| `apporbit-frontend` | Фронтенд |
| `apporbit-mongo` | MongoDB |
| `apporbit-maintenance` | Maintenance mode |

**Другое:**
| Контейнер | Назначение |
|-----------|-----------|
| `acc` | ? (порт 80) |
| `tonapi` | TON API |

### Docker-контейнеры AI-Manager
| Контейнер | Назначение |
|-----------|-----------|
| `ai-manager-api-1` | FastAPI API, порт 8000 |
| `ai-manager-celery_worker-1` | Основной worker |
| `ai-manager-celery_worker_ai-1` | AI worker (LLM) |
| `ai-manager-celery_worker_fetch-1` | Fetch worker (KS API) |
| `ai-manager-celery_beat-1` | Планировщик |
| `ai-manager-mysql-1` | MySQL 8.0 |
| `ai-manager-redis-1` | Redis 7 |
| `ai-manager-qdrant-1` | Qdrant (вектора) |

### Docker-контейнеры на тестовом/бизнес-сервере (116.203.112.192)
- `autoprem-bot` — AutoPrem бот
- `autoprem-db` — AutoPrem PostgreSQL
- Тестовый стек КС (ks-api, ks-bot, ks-worker-layer*, ks-admin-api и др.)
- Тестовый AI-Manager
- `traefik` — Reverse proxy (HTTPS)
- `trello-daily-report` — Ежедневный отчёт
- `apporbitstats` — Статистика

### URL-адреса (через Traefik)
| URL | Сервис |
|-----|--------|
| `https://api.knyazservice.com` | KS API (внешний) |
| `https://adminapi.knyazservice.com` | KS Admin API |
| `https://aimanager.knyazservice.com` | AI-Manager API |
| `https://heatup.knyazservice.com` | Heat Up API |
| `https://graylog.knyazservice.com` | Graylog (логи) |

---

## 3. Сервисы КС-экосистемы

### 3.1 KS (основной) — `github.com/knyazservice/KS`

**Ядро платформы.** Монорепозиторий с 8 Python-пакетами:

| Пакет | Назначение | Фреймворк |
|-------|-----------|-----------|
| `ks_api` | REST API — центральный хаб, единственный с доступом к БД | FastAPI |
| `ks_bot` | Telegram бот для управления | Pylogram |
| `ks_worker` | Исполнение заказов на сессиях | Pylogram/Telethon |
| `ks_celery` | Фоновые задачи | Celery + RabbitMQ |
| `ks_orchestrator` | Управление worker-процессами через supervisor | FastAPI |
| `ks_cli` | CLI-интерфейс | Typer |
| `ks_sdk` | Авто-генерированный HTTP-клиент из OpenAPI | — |
| `ks_core` | Общие DTO, enum'ы, модели, RPC | — |

**Архитектура**: Clean Architecture
- `api → application → domain → database`
- Никакой прямой доступ к БД кроме через ks_api
- `ks_bot` → `ks_sdk` → REST API → database
- `ks_worker` → `InternalAPIClient` → REST API → database

**API слои**:
- `/api/external/` — Bearer token auth, для внешних клиентов
- `/api/internal/` — Worker auth (`X-WORKER-ID`), для worker'ов
- `/api/admin/` — Telegram user auth
- `/api/v2/` — Bearer token + роли (Orders, Sessions, Chats, Posts, Billing, RPC, Moderation)

**RPC система**: `POST /api/external/sessions/{uid}/rpc`
- Типы задач: `SingleTask`, `Chain` (последовательно), `Group` (параллельно)
- Исполняются ARQ worker'ом в Redis

### 3.2 ks_admin_api — `github.com/knyazservice/ks_admin_api`

**Admin REST API** для CRUD операций над сущностями.

**Эндпоинты** (`/api/v1/`):
- `/users` — пользователи (TMA auth + API key)
- `/chats` — чаты (CRUD, фильтрация по стране, подписчикам, разрешениям)
- `/sessions` — сессии (CRUD, QR-login, RPC через KS API)
- `/orders` — заказы (CRUD, фильтрация по статусу, клиенту)
- `/posts` — посты (CRUD, привязка к заказам)
- `/order-chats` — связь заказ↔чат (CRUD, bulk, diff)
- `/themes` — темы/категории
- `/clusters` — кластеры чатов
- `/message-types` — типы сообщений
- `/folders` — папки
- `/logs` — логи отправки

**Аутентификация**:
- TMA (Telegram Mini App) — Ed25519 подпись
- API Key — `Authorization: Bearer <key>`

**Стек**: FastAPI, SQLAlchemy (async), MariaDB, Alembic миграции

### 3.3 AI-Manager — `github.com/knyazservice/AI-Manager`

**ИИ-система** модерации чатов и автоматизации заказов.

**Основные функции**:
- **Модерация чатов**: анализ контента через LLM (DeepSeek), извлечение тем, языка, разрешена ли реклама
- **Подбор чатов**: embeddings (OpenAI ada-002) → Qdrant → cosine similarity → пороги (≥0.825 авто, 0.80-0.825 LLM-проверка)
- **Адаптация постов**: автоматическая подгонка под ограничения чатов
- **Пайплайн заказов**: selection → adaptation → start (полностью автоматический для FF16 заказов)

**API**: `https://aimanager.knyazservice.com/api/`
- `/chats/process-single`, `/chats/process-batch` — модерация
- `/chat-selection/start`, `/chat-selection/{task_id}` — подбор чатов
- `/order-start/start` — запуск заказа (полный пайплайн)
- `/posts/generate-alternatives` — адаптация постов
- `/folders` — управление папками чатов
- `/auto-match/*` — автоматический матчинг FF16 заказов
- `/ban-moderator/*` — мониторинг банов
- `/ks-monitoring/*` — мониторинг KS задач

**Стек**: FastAPI, Celery (3 типа worker'ов), MySQL, Redis, Qdrant, DeepSeek + OpenAI

### 3.4 AutoPrem — `github.com/knyazservice/autoprem`

**Автоматическая покупка Telegram Premium** для сессий.

**Способы покупки**:
- Fragment/TON (международный, без KYC) — всегда 3 месяца
- Банковские карты (Россия) — через Smart Glocal + 3DS

**Интерфейсы**:
- Telegram бот (aiogram 2.x) — OpenAI Agent с function calling
- HTTP API: `POST /api/sessions/register` — регистрация сессии с премиумом

**Интеграция с KS**:
- `POST /api/external/sessions/{uid}/rpc/set_username` — установка username перед Fragment
- `POST /api/external/sessions/{uid}/revise` — обновление Premium статуса
- Получает warmed сессии от Heat Up

**Стек**: aiogram 2.x, aiohttp, OpenAI Agent (GPT), PostgreSQL, tonsdk

### 3.5 Heat Up — `github.com/knyazev741/heat_up`

**Сервис прогрева сессий** (14 дней).

**Что делает**: Симулирует естественное поведение — подписки на каналы, чтение сообщений, реакции, взаимодействие с ботами. 2-5 сессий прогрева в день, 3-7 действий за сессию.

**API**: `https://heatup.knyazservice.com`
- `POST /warmup/{session_id}` — запуск прогрева (async)
- `POST /warmup-sync/{session_id}` — синхронный прогрев
- `GET /sessions/{session_id}/history` — история действий
- `/accounts/*` — управление аккаунтами
- `/scheduler/*` — автоматический планировщик

**Интеграция с KS**: синхронизация статусов сессий через Admin API (frozen/deleted/banned)

**Стек**: FastAPI, SQLite, DeepSeek (LLM), TGStat API

### 3.6 ks-go — `github.com/knyazservice/ks-go`
Компонент на Go. Активно обновляется (19 марта). Детали требуют исследования.

### 3.7 ks-admin-mini-app — `github.com/knyazservice/ks-admin-mini-app`
Telegram Mini App (TypeScript) — фронтенд для Admin API.

### 3.8 session_manager — `github.com/knyazservice/session_manager`
Менеджер сессий (Python). Активно обновляется (17 марта).

### 3.9 web — `github.com/knyazservice/web`
Сайт КС (TypeScript). Не обновлялся с 2022.

---

## 4. Модель данных (ks-core)

### Основные сущности

**Session** (Telegram-аккаунт):
- phone_number, telegram_id, auth_string, status
- Статусы: FREE, IN_USE, BAN, COOLDOWN, IDLE, BROKEN, IMPORTED, DISABLED
- is_premium, premium_end_date
- Привязка к Proxy, SessionConfig
- country, provider (SIM)
- api_id, api_hash, device_model, app_version

**Order** (рекламная кампания):
- client (Client), boss_id (менеджер)
- status: INITIAL → STARTED → PAUSED → FINISHED
- interval (секунды между отправками), chats_limit
- Кастомизация сессии: session_name, session_bio, session_avatar, session_reply_text
- features_flags: SEND_MESSAGE_INSTEAD_OF_FORWARD, IGNORE_ANTISPAM_CHATS, TELETHON_ORDER_RUNNER

**Chat** (чат/канал):
- id (Telegram chat ID), username, title, invite_link
- Разрешения: can_send_messages, can_embed_links, can_send_media и т.д.
- repeat_after, minimal_send_interval
- is_blocked, custom_action, message_symbols_limit

**Post** (рекламный контент):
- text, formatted_text, media, gif, video
- forward_message_id (для форвардов)
- alternative_for (альтернативные версии)

**Worker** (исполнитель = Session + Order):
- session, order, status (FREE, JOIN_ONLY, ORDER, COOLDOWN, IDLE)

**Client** (заказчик):
- id (Telegram user ID), username, premoderation, role

**User** (админ/модератор):
- role: USER, CHAT_MODERATOR, ADMIN, ROOT

### Связи (junction tables)
- ChatTheme, SessionChat, OrderChat, OrderTheme, PostTheme
- SessionContact, SessionEvent, SessionPersonality
- Folder, ChatFolder

---

## 5. Ключевые API для агента

### KS API (`https://api.knyazservice.com`)
- Auth: Bearer token
- `GET /api/v2/orders` — список заказов
- `POST /api/v2/orders/{id}/start` — запуск заказа
- `POST /api/v2/orders/{id}/pause` — пауза
- `POST /api/v2/orders/{id}/finish` — остановка
- `GET /api/v2/sessions` — список сессий
- `POST /api/external/sessions/{id}/rpc` — RPC вызовы
- `GET /api/v2/chats` — список чатов

### Admin API (`https://adminapi.knyazservice.com`)
- Auth: Bearer token или TMA
- CRUD для всех сущностей (chats, sessions, orders, posts, themes, clusters, folders, logs)
- Bulk операции (order-chats)

### AI-Manager API (`https://aimanager.knyazservice.com`)
- Auth: X-API-KEY
- Модерация, подбор чатов, пайплайны заказов

### Graylog (`https://graylog.knyazservice.com`)
- Stream ID: `65017e157ca5b53bfd83eaf8`
- Ключевые поля: order_id, level, message, timestamp

### Heat Up API (`https://heatup.knyazservice.com`)
- Bearer token
- Прогрев сессий, статистика

### AutoPrem API
- `POST /api/sessions/register` — покупка Premium
- X-API-KEY auth

---

## 6. Правила и ограничения агента

### ТАБУ (никогда не делать)
1. **Продакшн сервер — только чтение**. Никаких билдов, деплоев, изменений на проде
2. **Изменения в коде — только через Pull Request** в соответствующий репозиторий
3. **SSH на прод — только для чтения** логов/статусов, если API недоступен

### Приоритеты доступа
1. **API** — основной способ получения данных
2. **Graylog** — для логов
3. **SSH (read-only)** — fallback, если API не даёт нужную информацию

### Уровни доступа
- Чтение: полный доступ ко всем API
- Запись: создание/изменение заказов, сессий через API (с подтверждением)
- Код: только через PR (форк → ветка → PR)

### Пользователи
- Все сотрудники в рабочем чате КС
- Обращение к агенту через @тег бота
- Агент должен уметь читать reply (контекст сообщения, на которое сделан reply с тегом)

---

## 7. Возможности агента (целевые)

### Мониторинг и информация
- [ ] Статус заказов: сколько запущено, сколько должно быть (связь с Google Docs таблицей)
- [ ] Статус сессий: свободные, в работе, забаненные, на прогреве
- [ ] Логи: поиск ошибок через Graylog API
- [ ] Мониторинг AI-Manager: статусы задач, подбор чатов
- [ ] Клиентские сообщения: что написали клиенты в последнее время

### Действия
- [ ] Запуск/пауза/остановка заказов через KS API
- [ ] Покупка Premium через AutoPrem
- [ ] Запуск прогрева сессий через Heat Up
- [ ] Запуск подбора чатов через AI-Manager
- [ ] RPC вызовы на сессиях (ревизия, установка username)

### Разработка
- [ ] Чтение кода из репозиториев
- [ ] Создание PR с изменениями (ks_admin_api — добавление эндпоинтов, KS, AI-Manager и др.)
- [ ] Чтение истории чата (MCP plugin с поиском)

### Интеграции (потребуются)
- [ ] Google Docs MCP — для таблицы заказов
- [ ] Telegram MCP — сохранение истории чата в БД
- [ ] Graylog API клиент
- [ ] Расширение Admin API — маршруты для чтения диалогов клиентов

---

## 8. Репозитории knyazservice (полный список)

### Активные (ядро)
| Репо | Язык | Описание | Обновлён |
|------|------|----------|----------|
| KS | Python | Основная платформа | 2026-03-19 |
| ks-go | Go | Go-компонент | 2026-03-19 |
| AI-Manager | Python | ИИ модерация и подбор | 2026-03-19 |
| session_manager | Python | Менеджер сессий | 2026-03-17 |
| autoprem | Python | Покупка Premium | 2026-03-15 |
| ks_admin_api | Python | Admin REST API | 2026-02-24 |
| ks_core | Python | Общие схемы | 2026-01-22 |
| telegram_manager | Python | Telegram менеджер | 2026-01-03 |
| ks-admin-mini-app | TypeScript | TMA фронтенд | 2025-06-25 |

### Вспомогательные
| Репо | Язык | Описание |
|------|------|----------|
| ks_emulator | Python | Эмулятор |
| apporbit | Python | AppOrbit |
| apporbit-frontend | TypeScript | AppOrbit фронт |
| apporbit-admin-mini-app | TypeScript | AppOrbit TMA |
| apporbitstats | JavaScript | Статистика |
| ton-chats-api / ton-chats | Python/TS | TON чаты |
| KS-gifts | Python | Подарки |
| simple_billing_proxy | Python | Биллинг прокси |
| web | TypeScript | Сайт (2022) |
| stack | Shell | Инфраструктура |
| KS-helper | Python | Помощник |
| session_registrator | Python | Регистрация сессий |
| user_checker_api | Python | Проверка юзеров |
| incom_bot | Python | Incom бот |
| video-translator-tool | Python | Перевод видео |

---

## 9. Конфигурация (env-переменные)

### KS (`ks.env`)
- `KS_BOT_API_ID`, `KS_BOT_API_HASH`, `KS_BOT_TOKEN`
- `KS_API_PORT=8085`, `KS_API_SECRET_HEADER`
- `KS_MYSQL_HOST`, `KS_MYSQL_PORT`, `KS_MYSQL_USER`, `KS_MYSQL_PASSWORD`, `KS_MYSQL_DATABASE`
- `KS_REDIS_HOST`, `KS_REDIS_PORT`
- `KS_RABBITMQ_HOST`, `KS_RABBITMQ_PORT`
- `KS_AI_MANAGER_BASE_URL`, `KS_AI_MANAGER_API_KEY`

### Admin API (`ks_admin_api.env`)
- `KS_ADMIN_API_DATABASE_URL` (MariaDB)
- `KS_ADMIN_API_API_KEY`
- `KS_ADMIN_API_KS_API_URL`, `KS_ADMIN_API_KS_API_TOKEN`

### Graylog
- `GRAYLOG_URL=https://graylog.knyazservice.com`
- `GRAYLOG_TOKEN`
- `GRAYLOG_STREAM_ID=65017e157ca5b53bfd83eaf8`

---

## 10. Архитектура агента (план)

```
┌─────────────────────────────────────────────────────────┐
│              Рабочий чат КС (Telegram)                  │
│  Сотрудники обращаются через @tag + reply               │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│          Telegram Multi-Thread Router (Proxy)            │
│          Развёрнут на бизнес-сервере                     │
│          Перенаправляет сообщения в сессию Claude        │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│              Claude Code сессия (КС-агент)               │
│                                                          │
│  MCP-серверы:                                            │
│  ├─ telegram-multi (чат, reply, история)                 │
│  ├─ KS API клиент                                       │
│  ├─ Admin API клиент                                     │
│  ├─ AI-Manager API клиент                                │
│  ├─ Graylog клиент                                       │
│  ├─ GitHub (PR, код)                                     │
│  ├─ Google Docs (таблица заказов)                        │
│  └─ SSH (read-only fallback)                             │
│                                                          │
│  CLAUDE.md: полная инструкция + контекст                 │
└──────────────────────────────────────────────────────────┘
```

---

## 11. Дополнительные сервисы

### MTB (Metabase)
- URL: `https://mtb.knyazservice.com/`
- Что это: Metabase v0.50.7 — BI-платформа, обёртка над БД КС
- Контейнер: `metabase` на КС-сервере (136.243.13.167)
- Подключён к: `ks2-db-1` (MariaDB), `ks2-mongo-1`, `apporbit-mongo` через Docker network
- Назначение: дашборды, SQL-запросы, аналитика поверх данных КС

### telegram_manager (ks-managers)
- Репо: `github.com/knyazservice/telegram_manager`
- Менеджмент Telegram-операций

### Google Sheets (таблица заказов)
- URL: `https://docs.google.com/spreadsheets/d/1ULm5ExIAkXj34SyYNnuT0EJ-hFYZnHV8s7JF7f0dSYU/edit?gid=1817506727`
- Назначение: трекинг заказов (сколько запущено / должно быть запущено)
- Интеграция: через MCP-сервер `mcp-gsheets` (npm)

### Подключение Google Sheets к агенту
1. Создать GCP проект, включить Google Sheets API
2. Создать Service Account, скачать JSON-ключ
3. Расшарить таблицу на email сервис-аккаунта (Viewer)
4. Добавить MCP-сервер:
```json
{
  "mcpServers": {
    "mcp-gsheets": {
      "command": "npx",
      "args": ["-y", "mcp-gsheets@latest"],
      "env": {
        "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account-key.json"
      }
    }
  }
}
```

---

## 12. Развёртывание агента

### Telegram бот
- Новый бот (токен будет предоставлен)
- Работает в общем рабочем чате КС
- Вызывается через @тег бота
- Читает reply-контекст (сообщение, на которое сделан reply с тегом)

### Где развернуть
- Бизнес-сервер (116.203.112.192) — отдельно от личного агента
- Docker-контейнер с Telegram Multi-Thread Router (proxy + plugin)
- Claude Code сессия для обработки запросов

### MCP-серверы агента
1. `telegram-multi` — чат (reply, история, поиск)
2. `mcp-gsheets` — Google Sheets таблица заказов
3. `github` — PR, код репозиториев knyazservice
4. Кастомные HTTP-клиенты: KS API, Admin API, AI-Manager, Graylog, Heat Up, AutoPrem

### Необходимые доработки
1. **telegram-multi plugin**: добавить сохранение истории сообщений в БД + поиск по истории
2. **ks_admin_api**: добавить маршруты для чтения клиентских диалогов (данные уже в БД)
3. **CLAUDE.md для агента**: адаптировать KS_AGENT_CONTEXT.md в рабочую инструкцию

---

## 13. Менеджерские аккаунты и диалоги

### Текущее состояние (на 21.03.2026)
- 30 активных заказов (status=1)
- 64 сессии обслуживают заказы (по 1 заказу на сессию)
- Почти все сессии Premium (кроме 2)

### Как работают диалоги
1. Клиент пишет ЛС сессии (менеджерскому аккаунту)
2. Worker пересылает сообщение в OrderPrivateChat (приватный чат заказа)
3. Менеджер видит сообщение и отвечает reply'ем
4. Worker пересылает ответ обратно клиенту

### Хранение диалогов
- **Central MySQL** (таблица `log`): order_id, session_id, chat_id, message_id, datetime
- **Worker SQLite** (локально): message_id, chat_id, user_id, source_message_id

### PR: Новые эндпоинты для чтения диалогов
- PR #1 в ks_admin_api: https://github.com/knyazservice/ks_admin_api/pull/1
- `GET /orders/{id}/private-chat` — инфо о приватном чате
- `GET /orders/{id}/logs` — логи сообщений (пагинация, фильтры)
- `GET /sessions/{id}/active-orders` — активные заказы сессии

---

## 14. Открытые вопросы

- [ ] Что за контейнер `acc` на проде?
- [ ] Токен нового Telegram бота (ждём)
- [x] JSON-ключ Google Service Account — настроен, доступ к таблице подтверждён
- [x] Эндпоинты диалогов в admin API — PR #1 создан
