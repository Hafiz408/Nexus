---
status: complete
phase: 28-local-first-privacy
source: [manual — derived from v3.0 feature/v3-local-first-privacy commit]
started: 2026-03-25T00:00:00Z
updated: 2026-03-25T00:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. sqlite-vec in requirements, pgvector removed
expected: requirements.txt contains sqlite-vec and does NOT contain psycopg2-binary or pgvector.
result: pass

### 2. database.py deleted
expected: backend/app/db/database.py no longer exists.
result: pass

### 3. Postgres config fields removed
expected: config.py has no postgres_host/port/db/user/password fields.
result: pass

### 4. IndexRequest and QueryRequest include db_path
expected: Both models in schemas.py have db_path: str field.
result: pass

### 5. graph_store accepts db_path parameter
expected: save_graph() and load_graph() accept db_path — no hardcoded data/nexus.db.
result: pass

### 6. embedder uses sqlite-vec
expected: embedder.py uses sqlite-vec vec0 virtual table — no pgvector/psycopg2 imports.
result: pass

### 7. Extension derives and sends db_path
expected: SidebarProvider.ts has _dbPath getter returning <repoPath>/.nexus/graph.db, passed to all BackendClient calls.
result: pass

### 8. Full test suite green
expected: python -m pytest tests/ -q completes with 193 passed, 0 failed.
result: pass

### 9. No leftover worktrees
expected: git worktree list shows only the main workspace.
result: pass

### 10. docker-compose.yml updated
expected: docker-compose.yml has no postgres service, no postgres_data volume. Backend home-dir mount is :rw (not :ro).
result: pass

### 11. Backend starts without Postgres (manual)
expected: uvicorn app.main:app --reload starts cleanly with no psycopg2/pgvector errors. docker compose up --build reaches healthy without postgres container.
result: pass

## Summary

total: 11
passed: 11
issues: 0
pending: 0
skipped: 0

## Gaps

[none yet]
