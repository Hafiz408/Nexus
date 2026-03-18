---
phase: 01-infrastructure
plan: 01
subsystem: infra
tags: [docker, docker-compose, postgres, pgvector, python, fastapi, uvicorn, pydantic-settings]

# Dependency graph
requires: []
provides:
  - Docker Compose stack: postgres (pgvector/pgvector:pg16) + backend (python:3.11-slim)
  - Health-checked postgres with pg_isready (interval 5s, retries 10)
  - Backend service that waits on postgres via condition: service_healthy
  - ./data:/app/data bind mount for SQLite persistence
  - backend/requirements.txt with all 7 Phase 1 dependencies
  - backend/app/main.py FastAPI stub with /health endpoint and lifespan init_db()
  - backend/app/config.py pydantic-settings BaseSettings for secrets management
  - backend/app/db/database.py psycopg2 connection + CREATE EXTENSION IF NOT EXISTS vector
affects:
  - 01-02 (secrets/env config — depends on compose + config.py)
  - 01-03 (data directory — depends on bind mount)
  - all subsequent phases (every phase requires running postgres + backend)

# Tech tracking
tech-stack:
  added:
    - pgvector/pgvector:pg16 (Docker image)
    - python:3.11-slim (Docker base image)
    - fastapi>=0.115.0
    - uvicorn[standard]
    - pydantic-settings>=2.0.0
    - psycopg2-binary
    - pgvector (Python client)
    - numpy
    - aiosqlite
  patterns:
    - Docker Compose v2 service_healthy dependency ordering (prevents postgres startup race)
    - pg_isready health check with start_period to allow postgres initialization
    - requirements.txt copied before app code for Docker layer cache optimization
    - pydantic BaseSettings with env_file for typed secret loading
    - CREATE EXTENSION IF NOT EXISTS vector in lifespan for idempotent pgvector activation

key-files:
  created:
    - docker-compose.yml
    - backend/Dockerfile
    - backend/requirements.txt
    - backend/app/__init__.py
    - backend/app/main.py
    - backend/app/config.py
    - backend/app/db/__init__.py
    - backend/app/db/database.py
    - .env.example
  modified: []

key-decisions:
  - "Host port 5433:5432 for postgres to avoid conflicts with local postgres on default 5432"
  - "Bind mount ./data:/app/data (not named volume) so SQLite files are visible in project dir and survive docker compose down"
  - "psycopg2-binary (not psycopg2) — python:3.11-slim lacks libpq-dev and gcc for source build"
  - "pgvector/pgvector:pg16 (not pgvector/pgvector:latest) — pin to explicit PostgreSQL version"
  - "CREATE EXTENSION IF NOT EXISTS vector in startup lifespan (not Dockerfile or init SQL) — idempotent and requires no extra tooling"

patterns-established:
  - "Pattern: depends_on with condition: service_healthy — all services depending on postgres use this pattern"
  - "Pattern: pydantic BaseSettings with env_file — all secret access goes through get_settings()"
  - "Pattern: FastAPI lifespan for startup initialization (database, extension registration)"

requirements-completed: [INFRA-01, INFRA-02]

# Metrics
duration: 3min
completed: 2026-03-18
---

# Phase 1 Plan 01: Docker Compose Stack and Backend Dockerfile Summary

**Two-service Docker Compose stack with pgvector/pgvector:pg16 health-checked postgres, python:3.11-slim backend, service_healthy dependency ordering, and ./data bind mount for SQLite persistence**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-18T06:57:41Z
- **Completed:** 2026-03-18T07:00:xx Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments

- docker-compose.yml with two services: postgres (pgvector/pgvector:pg16 with pg_isready healthcheck) and backend (depends_on condition: service_healthy)
- backend/Dockerfile using python:3.11-slim with requirements.txt layer cache ordering
- backend/requirements.txt with all 7 Phase 1 dependencies (fastapi, uvicorn, pydantic-settings, psycopg2-binary, pgvector, numpy, aiosqlite)
- FastAPI entry point (app/main.py) with /health endpoint and lifespan-based init_db() call
- pydantic-settings BaseSettings (app/config.py) for typed, validated secret loading from .env
- database.py stub with get_db_connection() and init_db() — registers pgvector type and activates extension per-database

## Task Commits

Each task was committed atomically:

1. **Task 1: Create docker-compose.yml with postgres health check and backend service** - `46c006a` (feat)
2. **Task 2: Create backend/Dockerfile and backend/requirements.txt** - `5b37dbf` (feat)

## Files Created/Modified

- `docker-compose.yml` - Two-service compose stack: postgres (pgvector:pg16, pg_isready health check, port 5433:5432) + backend (service_healthy dep, ./data bind mount, port 8000:8000)
- `backend/Dockerfile` - python:3.11-slim, requirements.txt first for layer cache, uvicorn --reload CMD
- `backend/requirements.txt` - 7 Python dependencies for Phase 1 and future phases
- `backend/app/__init__.py` - Empty package marker
- `backend/app/main.py` - FastAPI app with /health endpoint and lifespan init_db()
- `backend/app/config.py` - pydantic-settings BaseSettings with @lru_cache get_settings()
- `backend/app/db/__init__.py` - Empty package marker
- `backend/app/db/database.py` - psycopg2 get_db_connection() + init_db() activating pgvector extension
- `.env.example` - All required env vars documented with placeholder values

## Decisions Made

- Host port 5433 (not 5432) for postgres: avoids conflicts with any local postgres on the default port. Documented in compose file comment.
- Bind mount ./data (not named volume): SQLite files are visible in project directory and persist through `docker compose down`. Named volumes survive only without `--volumes` flag, making bind mount simpler and more explicit.
- psycopg2-binary over psycopg2: python:3.11-slim omits libpq-dev and gcc, so source-compiled psycopg2 fails. Binary package bundles the compiled C extension.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added .env.example with placeholder values**
- **Found during:** Task 1 (docker-compose.yml validation)
- **Issue:** `docker compose config` requires `env_file: .env` to exist; the plan didn't specify creating `.env.example` but the research (1-RESEARCH.md) documents it as a required artifact alongside the compose file
- **Fix:** Created `.env.example` with all documented keys and placeholder values; created `.env` (git-ignored) with the same structure for local validation
- **Files modified:** `.env.example`
- **Verification:** `docker compose config --quiet` exits 0
- **Committed in:** `46c006a` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 2 — missing critical infrastructure file)
**Impact on plan:** Necessary for `docker compose config` validation and for developers to know which secrets to provide. No scope creep — .env.example was documented in the research as a required output.

## Issues Encountered

- `docker compose config --quiet` returned exit 1 initially because `env_file: .env` was specified in the backend service but `.env` did not exist. Created `.env` (git-ignored) with placeholder values to unblock validation.

## User Setup Required

Developers must create a `.env` file before running `docker compose up`. Copy `.env.example` and fill in real values:

```bash
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD, OPENAI_API_KEY, LANGCHAIN_API_KEY
docker compose up
```

The `.env` file is git-ignored and must never be committed.

## Next Phase Readiness

- docker-compose.yml validated (docker compose config exits 0)
- Backend Dockerfile ready to build — will be built on first `docker compose up`
- All 7 dependencies pinned in requirements.txt
- pydantic-settings config.py ready for Plan 02 (secrets management)
- No blockers for Phase 1 Plan 02 or 03

---
*Phase: 01-infrastructure*
*Completed: 2026-03-18*
