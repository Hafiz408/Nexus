# Phase 1: Infrastructure - Research

**Researched:** 2026-03-18
**Domain:** Docker Compose, PostgreSQL 16 + pgvector, Python 3.11 Dockerfile, pydantic-settings, volume persistence
**Confidence:** HIGH

---

## Summary

Phase 1 establishes the local development environment: a Docker Compose stack with PostgreSQL 16 + pgvector, a Python 3.11 backend container, SQLite data persistence, and a clean secrets management setup. All four requirements (INFRA-01 through INFRA-04) are well-supported by mature tooling with no ambiguity.

The pgvector Docker image `pgvector/pgvector:pg16` is the canonical way to run PostgreSQL 16 with the vector extension pre-installed — no custom Dockerfile or init scripts are needed. The backend uses `python:3.11-slim` with a simple `requirements.txt` install (no multi-stage build needed for local dev). pydantic-settings 2.x handles `.env` loading natively. SQLite persistence is achieved via a bind mount of `./data` to the backend container.

**Primary recommendation:** Use `pgvector/pgvector:pg16` image, `pg_isready` health check, bind mount `./data:/app/data` for SQLite, and pydantic-settings `model_config` with `env_file='.env'` — all standard, no hand-rolling required.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INFRA-01 | `docker compose up` starts PostgreSQL 16 + pgvector without errors and passes health checks | `pgvector/pgvector:pg16` image + `pg_isready` healthcheck pattern verified; see Docker Compose pattern below |
| INFRA-02 | Backend Dockerfile builds Python 3.11 environment with all dependencies | `python:3.11-slim` base image + `pip install -r requirements.txt`; official FastAPI Docker docs confirm this pattern |
| INFRA-03 | `.env.example` documents all required secrets; `.env` is in `.gitignore` | pydantic-settings 2.x `BaseSettings` with `model_config = SettingsConfigDict(env_file='.env')` is the verified approach |
| INFRA-04 | `data/` directory is mounted for SQLite persistence across container restarts | Bind mount `./data:/app/data` in compose; data persists through `docker compose down` (volumes removed only with `--volumes` flag) |
</phase_requirements>

---

## Standard Stack

### Core

| Component | Version/Tag | Purpose | Why Standard |
|-----------|-------------|---------|--------------|
| `pgvector/pgvector` Docker image | `pg16` tag | PostgreSQL 16 with pgvector pre-installed | Official pgvector image; no custom init scripts needed |
| `pgvector` Python client | latest (`pgvector` PyPI package) | Register vector types with psycopg2/psycopg3, create indexes | Official Python client for pgvector |
| `psycopg2-binary` | latest | Python ↔ PostgreSQL driver | Most common driver; `-binary` avoids build deps in containers |
| `python:3.11-slim` | 3.11-slim | Backend container base image | Official Python image; slim reduces size without Alpine compat issues |
| `pydantic-settings` | 2.x | Load `.env` into typed Settings object | Verified via Context7; integrates natively with FastAPI |
| Docker Compose | v2 (`docker compose` not `docker-compose`) | Orchestrate postgres + backend services | Built into Docker Desktop; v2 is current standard |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `aiosqlite` | latest | Async SQLite for graph persistence | Required by STORE-01/STORE-02 (Phase 5) but needed in requirements.txt now |
| `numpy` | latest | Encode float arrays for pgvector | Required by pgvector Python client for vector operations |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `pgvector/pgvector:pg16` image | Base `postgres:16` + init SQL to `CREATE EXTENSION vector` | More control but requires custom Dockerfile or init script — unnecessary complexity for local dev |
| `psycopg2-binary` | `psycopg` (v3) | psycopg3 is newer, async-native; v2 is more battle-tested and has broader ecosystem support; either works with pgvector-python |
| bind mount `./data` | Named Docker volume | Named volumes are Docker-managed and more portable; bind mounts are simpler, make the `data/` directory visible in the repo, and match the requirement wording |

**Installation (requirements.txt essentials for Phase 1):**
```
fastapi>=0.115.0
uvicorn[standard]
pydantic-settings>=2.0.0
psycopg2-binary
pgvector
numpy
aiosqlite
```

---

## Architecture Patterns

### Recommended Project Structure (Phase 1 files)

```
nexus/
├── backend/
│   ├── app/
│   │   ├── config.py          # pydantic-settings BaseSettings
│   │   └── db/
│   │       └── database.py    # connection setup (stub for Phase 1)
│   ├── requirements.txt
│   └── Dockerfile
├── data/                      # bind-mounted; SQLite files live here
├── docker-compose.yml
├── .env                       # git-ignored; actual secrets
└── .env.example               # committed; documents all keys
```

### Pattern 1: PostgreSQL + pgvector Docker Compose with Health Check

**What:** Use the official `pgvector/pgvector:pg16` image; health check with `pg_isready` ensures downstream services wait for postgres to be ready before starting.

**When to use:** Always — `pg_isready` is the standard postgres liveness probe.

```yaml
# Source: https://hub.docker.com/r/pgvector/pgvector + https://github.com/peter-evans/docker-compose-healthcheck
services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: nexus_postgres
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 10
      start_period: 10s

  backend:
    build: ./backend
    depends_on:
      postgres:
        condition: service_healthy
    env_file: .env
    volumes:
      - ./data:/app/data
    ports:
      - "8000:8000"

volumes:
  postgres_data:
```

**Key points:**
- `depends_on` with `condition: service_healthy` is Docker Compose v2 syntax — prevents backend from starting before postgres accepts connections.
- `pgvector/pgvector:pg16` has the vector extension available but it must still be explicitly created in the database: `CREATE EXTENSION IF NOT EXISTS vector;` — done in `database.py` on startup, NOT in the Dockerfile.
- The postgres data uses a **named volume** (most portable); SQLite uses a **bind mount** (`./data:/app/data`) so the files are visible in the project.

### Pattern 2: Python 3.11-slim Dockerfile

**What:** Simple single-stage Dockerfile for local dev. No multi-stage build needed — local dev prioritizes rebuild speed over image size.

```dockerfile
# Source: https://fastapi.tiangolo.com/deployment/docker/
FROM python:3.11-slim

WORKDIR /app

# Copy deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

**Key points:**
- Copy `requirements.txt` before application code — Docker layer cache skips `pip install` if deps haven't changed.
- `--reload` is appropriate for local dev; remove for production.
- `python:3.11-slim` avoids Alpine-specific build issues (missing C headers for psycopg2, numpy) while still being smaller than full Debian.

### Pattern 3: pydantic-settings config.py

**What:** Single `Settings` class that loads all secrets from `.env`. FastAPI uses `@lru_cache` to ensure only one instance is created.

```python
# Source: https://github.com/pydantic/pydantic-settings (Context7 verified)
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    # Database
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # OpenAI
    openai_api_key: str

    # LangSmith (optional)
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "nexus-v1"

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

### Pattern 4: pgvector Extension Initialization

**What:** The `pgvector/pgvector:pg16` image ships the extension binary, but it must be activated in the target database. Do this in `database.py` at startup (not in the Dockerfile or init SQL).

```python
# Source: https://context7.com/pgvector/pgvector-python/llms.txt
import psycopg2
from pgvector.psycopg2 import register_vector

conn = psycopg2.connect(
    host=settings.postgres_host,
    port=settings.postgres_port,
    dbname=settings.postgres_db,
    user=settings.postgres_user,
    password=settings.postgres_password,
)
conn.autocommit = True
conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
register_vector(conn)
```

### Anti-Patterns to Avoid

- **Hardcoded secrets in Dockerfile or compose file:** Never put `POSTGRES_PASSWORD=secret` directly in `docker-compose.yml` — always use `${VAR}` from `.env`.
- **No health check on postgres:** Backend will crash on startup if postgres isn't ready. `depends_on: condition: service_healthy` is mandatory.
- **Committing `.env`:** Add `.env` to `.gitignore` at root level. `.env.example` should contain placeholder values, not real secrets.
- **Missing `CREATE EXTENSION IF NOT EXISTS vector`:** The image provides the binary but you must activate it per-database. `IF NOT EXISTS` makes it idempotent on restarts.
- **Using `pgvector/pgvector:latest`:** Use `:pg16` explicitly. `latest` may point to a different PostgreSQL version in the future, breaking the stack.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Wait for postgres to be ready | Shell sleep loop / custom retry script | `depends_on: condition: service_healthy` + `pg_isready` | Built into Docker Compose v2; handles race conditions correctly |
| Load `.env` into Python | `os.environ` manual parsing | `pydantic-settings` `BaseSettings` | Handles type coercion, validation, missing key errors, and multiple sources |
| Register vector type | Custom SQL type adapter | `pgvector.psycopg2.register_vector()` | Official client handles numpy ↔ vector type conversion |
| Create vector extension | Custom SQL migration script | `CREATE EXTENSION IF NOT EXISTS vector` in startup code | One line; idempotent; no tooling needed at this stage |

**Key insight:** Docker Compose v2's `condition: service_healthy` eliminates the entire class of "postgres not ready" startup bugs that plagued older setups.

---

## Common Pitfalls

### Pitfall 1: `psycopg2` vs `psycopg2-binary` Build Failures

**What goes wrong:** `psycopg2` (non-binary) fails to compile in `python:3.11-slim` because `libpq-dev` and `gcc` are not present.

**Why it happens:** Slim images remove build tools to reduce size.

**How to avoid:** Use `psycopg2-binary` in `requirements.txt`. It bundles the compiled C extension.

**Warning signs:** `pip install` errors mentioning `pg_config`, `libpq`, or `gcc not found`.

### Pitfall 2: pgvector Extension Not Created Per-Database

**What goes wrong:** `CREATE EXTENSION vector` fails with "extension already exists" on one restart, or vector columns fail with "type vector does not exist" on first startup.

**Why it happens:** Extension exists globally in the image but must be created in each database. `CREATE EXTENSION` (without `IF NOT EXISTS`) raises an error if it already exists.

**How to avoid:** Always use `CREATE EXTENSION IF NOT EXISTS vector` in startup code.

**Warning signs:** `ProgrammingError: type "vector" does not exist` on first query.

### Pitfall 3: `.env` Accidentally Committed to Git

**What goes wrong:** Real API keys (OpenAI, LangSmith) pushed to remote repository.

**Why it happens:** `.gitignore` not set up before first `git add .`.

**How to avoid:** Add `.env` to `.gitignore` before any commit. Create `.env.example` with placeholder values at the same time. Verify with `git status` — `.env` must not appear as tracked.

**Warning signs:** `git status` shows `.env` as a new untracked file that you're about to stage.

### Pitfall 4: `docker compose down` Destroys SQLite Data

**What goes wrong:** `docker compose down` removes containers and (with `-v` flag) volumes, wiping the SQLite database.

**Why it happens:** Named volumes are removed by `down -v`. Bind mounts are host-directory-backed and persist regardless.

**How to avoid:** Use a bind mount `./data:/app/data` for SQLite (as required by INFRA-04). The `./data` directory on the host survives any compose command.

**Warning signs:** Empty `./data` directory after `docker compose down && docker compose up`.

### Pitfall 5: Python Container Starts Before Postgres is Ready

**What goes wrong:** Backend container starts, tries to connect to postgres, fails with `connection refused`, exits immediately.

**Why it happens:** `depends_on` without `condition: service_healthy` only waits for container start, not for postgres to accept connections.

**How to avoid:** Use `depends_on: postgres: condition: service_healthy` paired with a working `healthcheck` on the postgres service.

**Warning signs:** Backend logs show `psycopg2.OperationalError: connection refused` within first 2 seconds of `docker compose up`.

---

## Code Examples

Verified patterns from official sources:

### pgvector Verify Inside Container (Post-startup Smoke Test)

```bash
# Source: https://hub.docker.com/r/pgvector/pgvector
docker exec nexus_postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
```

Expected output: one row with `vector` and a version string (e.g., `0.8.0`).

### IVFFlat Index Creation (for Phase 5, but schema awareness needed now)

```python
# Source: https://context7.com/pgvector/pgvector-python/llms.txt
# After inserting rows, create the index (IVFFlat requires data to exist first)
conn.execute(
    "CREATE INDEX IF NOT EXISTS code_embeddings_embedding_idx "
    "ON code_embeddings USING ivfflat (embedding vector_cosine_ops) "
    "WITH (lists = 100)"
)
```

**Note:** IVFFlat index must be created AFTER data is inserted (unlike HNSW which can be created on empty table). For Phase 1 we only need the table; index creation belongs in Phase 5.

### .env.example Template (All Phase 1 Required Keys)

```bash
# PostgreSQL
POSTGRES_USER=nexus
POSTGRES_PASSWORD=changeme
POSTGRES_DB=nexus_db
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# OpenAI (required for Phase 5+ embedding)
OPENAI_API_KEY=sk-...

# LangSmith (optional tracing)
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_TRACING_V2=false
LANGCHAIN_PROJECT=nexus-v1
```

### .gitignore Minimum Entries

```
.env
data/
__pycache__/
*.pyc
.venv/
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `docker-compose` (v1, separate binary) | `docker compose` (v2, built-in plugin) | Docker Desktop 3.x+ | Use `docker compose` not `docker-compose`; v2 supports `condition: service_healthy` |
| `ankane/pgvector` Docker image | `pgvector/pgvector` official image | 2023 | `pgvector/pgvector` is the official maintained image; `ankane/pgvector` still works but is unofficial |
| Manual `python-dotenv` + `os.environ` | `pydantic-settings` `BaseSettings` | pydantic v2 / 2023 | `pydantic-settings` is now separate package (`pip install pydantic-settings`); not bundled with pydantic v2 |
| `psycopg2` (v2) for pgvector | Either `psycopg2` or `psycopg` (v3) | 2023+ | pgvector-python supports both; v2 is more widely documented, v3 has async-native support. Use v2 for simplicity in V1. |

**Deprecated/outdated:**
- `from pydantic import BaseSettings`: Moved to separate `pydantic-settings` package in pydantic v2. Must `pip install pydantic-settings` separately.
- `ankane/pgvector` Docker image: Functional but superseded by official `pgvector/pgvector` image.
- `docker-compose` (hyphenated, v1): Replaced by `docker compose` (space, v2 plugin). All new documentation uses v2.

---

## Open Questions

1. **Python package manager: pip vs uv**
   - What we know: PRD and requirements specify `requirements.txt`. pip is standard.
   - What's unclear: `uv` is 10-100x faster and gaining traction for Docker builds in 2025.
   - Recommendation: Use `pip` for Phase 1 to match PRD spec. `uv` adoption is a V2 improvement.

2. **HNSW vs IVFFlat for production**
   - What we know: PRD specifies `ivfflat` index (EMBED-02). IVFFlat requires data to be present before index creation.
   - What's unclear: HNSW (added in pgvector 0.5.0) has better query performance and doesn't require pre-populated data.
   - Recommendation: Honor the PRD spec (ivfflat) in Phase 5. Flag for V2 upgrade to HNSW if performance matters.

3. **Port conflicts on developer machines**
   - What we know: `5432` is the default postgres port; `8000` is the default uvicorn port.
   - What's unclear: Developer may have local postgres already running on 5432.
   - Recommendation: Document in README that local postgres on 5432 will conflict. Consider using a non-standard port like `5433:5432` in compose to avoid conflicts.

---

## Sources

### Primary (HIGH confidence)

- `/pgvector/pgvector-python` (Context7) — psycopg2/psycopg3 setup, register_vector, ivfflat index creation patterns
- `/pydantic/pydantic-settings` (Context7) — BaseSettings, model_config, env_file configuration patterns
- https://hub.docker.com/r/pgvector/pgvector — Official pgvector Docker image; `pg16` tag confirmed available and actively maintained (updated within last 30 days)
- https://fastapi.tiangolo.com/deployment/docker/ — Official FastAPI Docker documentation; python:3.11-slim + requirements.txt pattern
- https://docs.docker.com/get-started/workshop/05_persisting_data/ — Official Docker volume persistence docs

### Secondary (MEDIUM confidence)

- https://github.com/peter-evans/docker-compose-healthcheck — `depends_on: condition: service_healthy` pattern; widely referenced
- https://github.com/langchain-ai/langchain-postgres/blob/main/docker-compose.yml — Real-world pgvector compose reference; uses `pg_isready` health check
- https://betterstack.com/community/guides/scaling-python/fastapi-docker-best-practices/ — FastAPI Docker best practices 2025

### Tertiary (LOW confidence)

- Various Medium blog posts on pgvector + Docker — Used only for cross-verification of pg16 tag availability, not as primary source

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Docker image tags verified on Docker Hub; Python client verified via Context7; pydantic-settings verified via Context7
- Architecture: HIGH — All patterns from official documentation sources
- Pitfalls: MEDIUM — Most from official docs; port conflict pitfall from general Docker knowledge (training data)

**Research date:** 2026-03-18
**Valid until:** 2026-04-18 (stable tooling; pgvector image tags and Docker Compose patterns change slowly)
