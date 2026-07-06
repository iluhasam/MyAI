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
  llm/        единый интерфейс generate/vision/embeddings (mock | litellm)
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

Эндпоинты: `GET /health`, `POST /chat` (`{"user_id": "...", "text": "..."}`).
Интерактивная OpenAPI-документация — на `/docs`. Тот же когнитивный стек, что у CLI/Telegram.

```bash
curl -s http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"u1","text":"(2+3)*4"}'
```

Реальная модель: в `.env` задайте `LLM_PROVIDER=litellm`, `LLM_MODEL`, `LLM_API_KEY`
и установите `pip install litellm`.

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
  крутится вечно. Ретранслируемое событие несёт стабильный id `outbox-<row_id>`, так
  что повторная доставка после сбоя дедуплицируется идемпотентными потребителями.
- **Безопасность промпта**: ввод пользователя санитаризуется и всегда оборачивается
  в делимитеры `<user_input>` — никогда не интерполируется в системный промпт сырым.
- **DI-контейнер** (`app/core/container.py`): ленивые синглтоны, overridable в тестах.
- **Порог семантики 0.82** — фильтр релевантности при извлечении из памяти
  (это не замена защите от инъекций, а отсечение нерелевантного контекста).

## Что дальше (не входит в MVP-срез)

Медиа-модули (Vision, Speech, OCR/docTR, RAG, Parser), внешний Search, Workers на
ARQ со scoped-сессиями, Scheduler, REST API, Admin — подключаются как расширения
через существующие интерфейсы, без изменения ядра.
