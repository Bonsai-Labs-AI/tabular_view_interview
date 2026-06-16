# Async Arbitrator Table Fill

## Quickstart (Docker)

Only Docker is required — no local Python or Node setup.

```bash
cp backend/.env.example backend/.env   # fill in OPENAI_API_KEY and TAVILY_API_KEY
docker compose up --build
```

Open http://localhost:5173

Source code is bind-mounted, so edits to `backend/app/**` and `frontend/src/**` hot-reload inside the containers. The SQLite database lives on a named Docker volume (`db_data`) shared between the API and worker services — wipe it with `docker compose down -v`.

## Quickstart (local, optional)

Requires a Redis instance reachable at `REDIS_URL` (default `redis://localhost:6379/0`) and broker at `CELERY_BROKER_URL` (default `redis://localhost:6379/1`).

### Backend (API)
```bash
cd backend
cp .env.example .env
poetry install
poetry run uvicorn app.main:app --port 8765 --reload
```

### Backend (worker)
```bash
cd backend
poetry run celery -A app.queue worker --loglevel=info --queues=cells --concurrency=4
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

---

## Architecture

```
HTTP                          Redis                       Celery worker process
────                          ─────                       ────────────────────

POST /tables/propose-columns  ─────►  LLM generates column schema (synchronous)
POST /tables                  ─────►  create table + cells (pending)
POST /tables/:id/start        ─────►  orchestrator enqueues cells.fill tasks
                                              │
                                              ▼
                                       Celery broker (db 1)
                                              │
                                              ▼
                                       worker picks up task ──► fill_cell(cell_id)
                                                                       │
                                                                       ├─► OpenAI + Tavily
                                                                       ├─► writes result to SQLite
                                                                       └─► sse.publish ──► Redis pub/sub (db 0)
                                                                                                │
GET  /tables/:id/events        ◄──── streams from ◄─────────────────────────────────────────────┘
GET  /tables/:id               ─────►  full table state (rows, columns, cells)
PATCH /tables/:id/columns/:cid ─────►  rename a column
```

The cell worker runs a four-stage agent loop per cell:

1. **Planner** — gpt-4.1-mini brief plan: which sources to consult
2. **Web subagent** — up to 3 Tavily searches, tools include `submit_findings`
3. **Document subagent** — semantic search over the arbitrator's document corpus via a local FAISS index (chunks embedded with `text-embedding-3-small`), plus a `read_document` tool for full-doc lookups
4. **Synthesis** — final LLM call via `submit_answer` tool, produces answer + confidence + reasoning + sources

The orchestrator (`app/orchestrator.py`) owns the table-level workflow: select pending cells, enqueue, flip status. The single dispatch seam (`enqueue_cell`) is where the route boundary meets Celery.

The RAG layer (`app/rag/`) builds a per-arbitrator FAISS index lazily on first query; each Celery worker process maintains its own in-memory cache.

---

## Services (docker-compose)

| Service | Purpose |
|----------|---------|
| `backend` | FastAPI API on port 8765 |
| `worker` | Celery worker consuming the `cells` queue |
| `redis` | Broker for Celery + pub/sub for SSE (internal only) |
| `frontend` | Vite dev server on port 5173 |

---

## Required env vars

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Column proposal + cell fill LLM calls |
| `TAVILY_API_KEY` | Web search inside each cell worker |
| `DATABASE_URL` | SQLite path; in compose this is `sqlite+aiosqlite:////db/arbitrator.db` (shared volume) |
| `REDIS_URL` | Pub/sub channel for SSE event bridging |
| `CELERY_BROKER_URL` | Celery broker for the `cells` queue |

---

## Tests

```bash
# Backend
cd backend && poetry install --with dev && poetry run pytest

# Frontend
cd frontend && npm install && npm run test:run
```
