---
phase: 01-infrastructure
plan: 02
subsystem: infra
tags: [pydantic-settings, postgres, pgvector, psycopg2, fastapi, docker]

# Dependency graph
requires: []
provides:
  - "pydantic-settings BaseSettings class loading all env vars from .env with lru_cache singleton factory"
  - "psycopg2 database connection + pgvector extension activation via CREATE EXTENSION IF NOT EXISTS vector"
  - ".env.example template documenting all 9 environment variables with placeholder values"
  - ".gitignore protecting .env from commits and data/* from git tracking"
  - "data/.gitkeep ensuring bind mount target directory is tracked in git"
affects: [phase-5-embedder, phase-6-pipeline, phase-7-index-endpoint, all-backend-phases]

# Tech tracking
tech-stack:
  added: [pydantic-settings, psycopg2-binary, pgvector]
  patterns: [lru_cache settings singleton, FastAPI lifespan for startup initialization, pydantic-settings BaseSettings for typed env loading]

key-files:
  created:
    - backend/app/config.py
    - backend/app/__init__.py
    - backend/app/db/__init__.py
    - backend/app/db/database.py
    - .env.example
    - .gitignore
    - data/.gitkeep
  modified:
    - backend/app/main.py

key-decisions:
  - "Used pydantic_settings (separate package) not pydantic.BaseSettings — required for pydantic v2 compatibility"
  - "lru_cache on get_settings() ensures single Settings instance across entire app lifetime"
  - "openai_api_key defaults to empty string — not required until Phase 5 embedding"
  - "postgres_host defaults to 'postgres' matching Docker Compose service name"
  - "data/* with !data/.gitkeep pattern commits directory structure without committing database files"
  - "conn.autocommit = True on psycopg2 connection so CREATE EXTENSION runs outside transaction block"

patterns-established:
  - "Settings pattern: All env vars flow through Settings class — never read os.environ directly"
  - "Startup pattern: FastAPI lifespan context manager calls init_db() before serving requests"
  - "Package pattern: __init__.py at app/ and app/db/ for clean Python package imports"

requirements-completed: [INFRA-03, INFRA-04]

# Metrics
duration: 3min
completed: 2026-03-18
---

# Phase 1 Plan 02: Secrets Management and DB Init Summary

**pydantic-settings BaseSettings config with lru_cache, psycopg2 + pgvector extension activation on startup, and git-safe .env/.data patterns**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-18T09:37:28Z
- **Completed:** 2026-03-18T09:40:30Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- Typed Settings class via pydantic-settings BaseSettings loading all 9 environment variables from .env, with lru_cache singleton ensuring a single instance across all requests
- psycopg2 database connection with pgvector type registration and idempotent CREATE EXTENSION IF NOT EXISTS vector on every startup
- FastAPI lifespan context manager wiring init_db() into startup, replacing the bare app initialization
- .gitignore with exact `.env` entry and `data/*` + `!data/.gitkeep` pattern preventing secrets and database files from leaking into git history

## Task Commits

Each task was committed atomically:

1. **Task 1: Create config.py with pydantic-settings and .env.example + .gitignore** - `44bc0c1` (feat)
2. **Task 2: Create database.py stub and data/ directory** - `5b37dbf` (feat)

## Files Created/Modified
- `backend/app/config.py` - pydantic-settings BaseSettings class with all postgres/openai/langsmith fields; get_settings() factory with lru_cache
- `backend/app/__init__.py` - Python package init for backend/app
- `backend/app/db/__init__.py` - Python package init for backend/app/db subpackage
- `backend/app/db/database.py` - get_db_connection() raw psycopg2 connection + init_db() with CREATE EXTENSION IF NOT EXISTS vector and register_vector
- `backend/app/main.py` - Updated to use FastAPI lifespan context manager calling init_db() on startup
- `.env.example` - Template with all 9 environment variables (POSTGRES_*, OPENAI_API_KEY, LANGCHAIN_*) with placeholder values
- `.gitignore` - Exact .env entry, data/* with !data/.gitkeep exception, Python cache/venv, IDE, OS artifacts
- `data/.gitkeep` - Empty file to track data/ bind mount target directory in git

## Decisions Made
- Used `pydantic_settings` (separate package) not `pydantic.BaseSettings` — pydantic v2 moved BaseSettings to a separate package; the hyphenated import would fail at runtime
- `lru_cache` on `get_settings()` ensures .env is only read once per process, avoiding repeated file I/O on every request
- `conn.autocommit = True` set on the psycopg2 connection so that CREATE EXTENSION executes outside a transaction block (required by PostgreSQL for DDL operations on extensions)
- `postgres_host` defaults to `"postgres"` matching the Docker Compose service name so the container-to-container connection works without configuration

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Files from a prior partial plan 01 execution were already present in the repository (database.py, main.py, data/.gitkeep committed at 5b37dbf). The prior execution produced identical content matching this plan's specifications, so no re-creation was needed. Task 1 files (config.py, .gitignore, package inits) were created fresh and committed at 44bc0c1.

## User Setup Required
None - no external service configuration required. User must copy .env.example to .env and fill in real values before running `docker compose up`.

## Next Phase Readiness
- Config and database foundation complete; plan 03 can create .env and verify the full stack starts
- All backend phases can import `from app.config import get_settings` for typed environment access
- Phase 5+ can call `init_db()` knowing pgvector extension will be available after startup

---
*Phase: 01-infrastructure*
*Completed: 2026-03-18*
