# Veridict — AI Contract Review

AI-powered legal contract review using a multi-agent LLM pipeline with full auth, multi-tenant workspaces, collaborative comments, and a PDF contract reader with clause highlights.

## Stack

| Layer | Tech |
|---|---|
| Backend API | FastAPI 0.111+, Uvicorn |
| LLM | Local Ollama (`LLM_PROVIDER=ollama`) — swap model via `OLLAMA_MODEL` in `.env` |
| Database | PostgreSQL (`veridict` DB), SQLAlchemy 2.0, Alembic |
| PDF Parsing | Docling + OCR fallback |
| Auth | JWT (12h) + httpOnly refresh tokens (30 days), bcrypt, account lockout |
| Frontend | React 19, TypeScript, Vite 6, Tailwind CSS 4, Framer Motion, TanStack Query |

## Running

From the project root (`Veridict/`):

```bash
# Backend
python3 -m uvicorn app.backend.main:app --host 0.0.0.0 --port 8000 --reload

# Worker (separate terminal)
python3 -m app.backend.worker

# Frontend
cd app/frontend && npm run dev
```

- Frontend: http://localhost:5173
- API: http://localhost:8000

## Setup

### 1. Python environment

```bash
cd app/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Environment variables

Create `.env` in the project root:

```
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.2:3b
OLLAMA_BASE_URL=http://localhost:11434/v1
POSTGRES_DSN=postgresql://user:pass@localhost:5432/veridict
JWT_SECRET=<random secret>
```

### 3. Database

```bash
cd app/backend
alembic upgrade head
```

### 4. Frontend

```bash
cd app/frontend
npm install
npm run dev
```

## Features

### Pipeline (12 stages)

`create_run → ingest_pdf → parse_ocr_normalize → clause_index → harvey_context_load → kira_context_load → harvey_review_block → kira_review_block → admin_merge → final_review_block → awaiting_human_review → finalized`

Two parallel review branches (Harvey: internal policy lineage, Kira: external compliance), admin merge, up to 2 final-review rounds with agreement check, mandatory human approval before verdict is emitted.

### Auth

- Organization creation, invite-based registration (48h single-use email-scoped links)
- Existing accounts: verify password + join workspace instead of rejecting
- Account lockout after 5 failed attempts; org admins can unlock

### Multi-tenant Org Model

3-tier hierarchy: **Organization → Workspace → WorkspaceMember**

- Org roles: `org_admin`, `member`
- Workspace roles: `workspace_admin`, `reviewer`, `viewer`

### Admin Panel

Accessible via the settings gear in the header (org admins only). Tabs: Users (roles, unlock, remove), Workspaces (create, manage members), Invites (generate shareable link, revoke).

### Contract Reader

PDF viewer with clause highlights. Highlights are computed via word-overlap scoring against finding descriptions (≥5-char words, threshold 3, drops to 2 for long words). Finding cards in the right sidebar; verdict below.

### Collaborative Comments

Per-run and per-finding comment threads. Colored avatar initials, job title display, 5s polling, soft delete.

### Workspace-scoped Contracts

- Members see only contracts in their workspaces
- Org admins see all contracts in the org ("All" tab) or filter by workspace
- Contract creation requires selecting a workspace

## Known Pending

- Export Report — not yet implemented
- Email sending for invites — manual link copy only
- Schedule Partner Review — postponed
- Workspace-level comments (currently run-scoped)
