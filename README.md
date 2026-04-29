# Async Arbitrator Table Fill

## Quickstart (Docker)

Only Docker is required — no local Python or Node setup.

```bash
cp backend/.env.example backend/.env   # fill in OPENAI_API_KEY and TAVILY_API_KEY
docker compose up --build
```

Open http://localhost:5173

Source code is bind-mounted, so edits to `backend/app/**` and `frontend/src/**` hot-reload inside the containers. The SQLite database is ephemeral — it's recreated each time the backend container starts.

## Quickstart (local, optional)

### Backend
```bash
cd backend
cp .env.example .env
poetry install
poetry run uvicorn app.main:app --port 8765 --reload
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
POST /tables/propose-columns   → LLM generates column schema
POST /tables                   → create table + cells (pending)
POST /tables/:id/start         → dispatch one asyncio task per cell
GET  /tables/:id/events        → SSE stream of cell_working / cell_done events
GET  /tables/:id               → full table state (rows, columns, cells)
PATCH /tables/:id/columns/:cid → rename a column
```

Each cell worker runs a small agentic loop:
- up to 3 Tavily web searches
- final LLM synthesis via `submit_answer` tool (gpt-4.1-mini)
- publishes SSE events on status changes

---

## Required env vars

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Column proposal + cell fill LLM calls |
| `TAVILY_API_KEY` | Web search inside each cell worker |
| `DATABASE_URL` | SQLite path (default: `sqlite+aiosqlite:///./arbitrator.db`) |

The SQLite database is created automatically on first startup.
