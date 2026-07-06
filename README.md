# AI Agent Platform

Многоканальная платформа персональных ИИ-агентов на принципах Clean Architecture
и асинхронного событийно-ориентированного взаимодействия. Транспорт (Telegram/CLI)
изолирован от когнитивного ядра; каналы подключаются без изменения логики.

Эта сборка — **вертикальный срез (MVP)** на лёгком стеке: полный путь запроса
`transport → gateway → router → agent → planner → executor → llm → memory → database`
работает из коробки, без внешних сервисов и API-ключей.

## Стек (MVP)

| Слой         | MVP-реализация            | Прод-цель (drop-in)         |
|--------------|---------------------------|-----------------------------|
| БД           | SQLite (aiosqlite)        | PostgreSQL (asyncpg)        |
| Session mem  | in-memory sliding window  | Redis                       |
| Semantic mem | in-memory cosine index    | Qdrant                      |
| LLM          | детерминированный mock     | LiteLLM (OpenAI/Claude/...) |
| Транспорт    | CLI                       | Telegram (aiogram) + REST   |

## Структура

```
app/
  core/       конфиг, логгер, исключения, event bus, DI-контейнер, lifecycle
  bot/        тонкие транспорты: CLI (рабочий), Telegram (aiogram, опц.)
  api/        REST-транспорт на FastAPI (/health, /chat) — тот же Gateway-стек
  gateway/    нормализация в UnifiedPayload + санитаризация (anti prompt-injection, PII)
  router/     классификатор типов и маршрутизация по конвейерам
  agent/      оркестратор когнитивного цикла
  planner/    декомпозиция запроса в ExecutionPlan (без побочных эффектов)
  executor/   исполнение плана + сборка безопасного промпта + синтез ответа
  llm/        единый интерфейс generate/vision/embeddings (mock | openrouter) + каталог моделей
  memory/     трёхуровневая память: session / long / semantic
  tools/      реестр инструментов + безопасный калькулятор
  database/   async SQLAlchemy 2.0, модели, репозитории, Outbox + publisher
tests/        pytest: e2e-срез, юниты, Outbox
scripts/      smoke_stdlib.py — проверка без установки зависимостей
```

## Запуск

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env        # опционально; дефолты уже рабочие
python -m app.main          # CLI-режим (mock LLM, SQLite)
```

Telegram-режим (нужен токен и `pip install aiogram`):

```bash
LLM_PROVIDER=mock TELEGRAM_BOT_TOKEN=xxx python -m app.main telegram
```

REST API-режим (FastAPI/uvicorn уже в requirements):

```bash
python -m app.main api          # поднимает HTTP на API_HOST:API_PORT (по умолч. 127.0.0.1:8000)
```

Эндпоинты: `GET /health`, `POST /chat` (`{"user_id": "...", "text": "..."}`),
`GET /models` (список доступных моделей), `GET /metrics` (обработанные turns,
подавленные дубли, backlog outbox по статусам).
Интерактивная OpenAPI-документация — на `/docs`. Тот же когнитивный стек, что у CLI/Telegram.

```bash
curl -s http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"u1","text":"(2+3)*4"}'
```

### Выбор модели (несколько моделей, индивидуально на пользователя)

Каталог доступных моделей — [app/llm/catalog.py](app/llm/catalog.py) (алиас → провайдерская
строка). Каждый пользователь выбирает свою модель командой, выбор хранится в БД
(таблица `user_preferences`) и применяется к его следующим запросам:

```
/models              # список моделей, текущая помечена «← сейчас»
/model claude        # переключиться (варианты: gpt-4o-mini, gpt-4o, claude, gemini, llama, deepseek)
```

Выбор индивидуален: у Алисы может быть `claude`, у Боба — `gemini`, не мешая друг другу.

### Персона (манера общения, индивидуально на пользователя)

Каталог стилей — [app/persona.py](app/persona.py). Персона задаёт *как* бот отвечает
(модель — *чем* он думает); их можно комбинировать. Выбор хранится в БД на пользователя:

```
/personas                 # список стилей, текущий помечен «← сейчас»
/persona философ          # варианты: обычный, философ, психолог, программист, наставник, юморист, деловой
/persona свой Ты — саркастичный кот, отвечай с иронией   # свободный стиль текстом
```

Стиль подмешивается в системный промпт **после** базовых правил безопасности, поэтому
не может их переопределить. `GET /personas` — список стилей через REST.

### Реальные модели через OpenRouter (один ключ — много моделей)

```bash
pip install litellm
# .env:
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...      # ключ с openrouter.ai
DEFAULT_MODEL=gpt-4o-mini         # модель по умолчанию для новых пользователей
```

Один ключ OpenRouter даёт доступ к GPT, Claude, Gemini, Llama, DeepSeek и др. Эмбеддинги
семантической памяти используют отдельную embedding-модель (`LLM_EMBEDDING_MODEL`, для
OpenRouter подставляется рабочая по умолчанию) и **не-фатальны** — их сбой не ломает ответ.

**Несколько провайдеров одновременно.** LiteLLM маршрутизирует по префиксу модели: маршруты
`openrouter/*` идут в OpenRouter, `gemini/*` — напрямую в Google. Задав ещё и `GEMINI_API_KEY`,
получаешь алиас `gemini` через прямой Google API (бесплатный tier), а остальные модели — через
OpenRouter; каждый вызов уходит своему провайдеру со своим ключом (ключи читаются из env).

Альтернатива — прямой провайдер: `LLM_PROVIDER=litellm`, `LLM_MODEL`, `LLM_API_KEY`.

## Docker

Один образ обслуживает все режимы; транспорт выбирается переменной `APP_MODE`.

```bash
cp .env.example .env            # впишите ключи (OPENROUTER_API_KEY и т.д.)

# REST API (по умолчанию, токен не нужен):
docker compose up --build       # http://localhost:8000  (/docs, /models, /metrics)

# Telegram-бот: в .env задайте APP_MODE=telegram и TELEGRAM_BOT_TOKEN, затем:
docker compose up --build
```

- Секреты берутся из `.env` во время запуска (`env_file`), **в образ не попадают**
  (`.env` в `.dockerignore`).
- База SQLite сохраняется на хосте через том `./data`, переживает перезапуски.
- `restart: unless-stopped` — контейнер сам поднимается после перезагрузки/сбоя.
- Образ работает от непривилегированного пользователя (`appuser`).

## Тесты

```bash
pytest                          # полный набор (требует зависимости из requirements)
python scripts/smoke_stdlib.py  # быстрая проверка чистой логики без зависимостей
```

## Архитектурные заметки

- **Outbox pattern** (`app/database`): запись диалога и событие `message.answered`
  коммитятся в одной транзакции (`MemorySubsystem.record_turn`); фоновый
  `OutboxPublisher` стартует в `lifespan` и ретранслирует их в event bus at-least-once,
  где их принимает подписчик (`app/core/subscribers.py`). Реле отключается флагом
  `OUTBOX_PUBLISHER_ENABLED=false` (например, в юнит-тестах).
- **Надёжность доставки**: неудачная публикация ретраится на следующих тиках
  (статус `FAILED`); после `OUTBOX_MAX_ATTEMPTS` попыток событие уходит в
  dead-letter (`DEAD`, терминальный) — «ядовитое» событие не блокирует очередь и не
  крутится вечно. Ретранслируемое событие несёт стабильный id `outbox-<row_id>`.
- **Идемпотентность потребителя** (`app/core/idempotency.py`): подписчики оборачиваются
  в `IdempotencyGuard` — повторная доставка (at-least-once) с тем же id выполняет
  побочный эффект ровно один раз. Окно дедупа ограничено (`IDEMPOTENCY_CACHE_SIZE`,
  FIFO-вытеснение); в распределённом деплое заменяется на Redis `SET NX EX`.
- **Безопасность промпта**: ввод пользователя санитаризуется и всегда оборачивается
  в делимитеры `<user_input>` — никогда не интерполируется в системный промпт сырым.
- **DI-контейнер** (`app/core/container.py`): ленивые синглтоны, overridable в тестах.
- **Порог семантики 0.82** — фильтр релевантности при извлечении из памяти
  (это не замена защите от инъекций, а отсечение нерелевантного контекста).

## Что дальше (не входит в MVP-срез)

Медиа-модули (Vision, Speech, OCR/docTR, RAG, Parser), внешний Search, Workers на
ARQ со scoped-сессиями, Scheduler, REST API, Admin — подключаются как расширения
через существующие интерфейсы, без изменения ядра.
