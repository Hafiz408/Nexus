---
phase: 16-config-v2
plan: "01"
subsystem: config
tags: [pydantic-settings, environment, configuration, v2-agents]

# Dependency graph
requires: []
provides:
  - "Five V2 agent tuning fields on Settings class: github_token, max_critic_loops, critic_threshold, debugger_max_hops, reviewer_context_hops"
  - "backend/.env.example documenting all V1 + V2 environment variables"
affects:
  - 17-router-agent
  - 18-debugger-agent
  - 19-reviewer-agent
  - 20-critic-agent
  - 21-mcp-layer

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "V2 config fields declared as typed pydantic-settings fields with safe defaults — no os.getenv() usage"
    - "pydantic-settings auto-maps snake_case field names to UPPER_SNAKE_CASE env vars"

key-files:
  created:
    - backend/.env.example
  modified:
    - backend/app/config.py

key-decisions:
  - "All five V2 fields are optional with safe defaults — backend starts without any V2 env vars set"
  - "github_token defaults to empty string (not None) so downstream MCP layer checks truthiness without None handling"
  - "critic_threshold typed as float (not int) to accept values like 0.7 and 0.8"

patterns-established:
  - "Downstream V2 agents access settings via: from app.config import get_settings; s = get_settings(); s.<field>"
  - "Tests override settings by instantiating Settings() directly with explicit field values"
  - "New config fields always go in the # V2 agent tuning knobs comment block at end of Settings class"

requirements-completed: [CONF-01, CONF-02]

# Metrics
duration: 7min
completed: 2026-03-21
---

# Phase 16 Plan 01: Config V2 Summary

**Five V2 agent tuning knobs added to pydantic-settings Settings class with safe defaults, plus full .env.example documenting all V1 + V2 environment variables**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-21T18:24:56Z
- **Completed:** 2026-03-21T18:31:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added `github_token`, `max_critic_loops`, `critic_threshold`, `debugger_max_hops`, `reviewer_context_hops` to Settings class with correct types and safe defaults
- Created `backend/.env.example` with labelled V2 Agent Tuning section — every variable has inline type, description, default, and requirement reference
- Verified env var overrides work correctly and all 93 V1 tests pass with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Add V2 fields to Settings class in config.py** - `82edac7` (feat)
2. **Task 2: Create backend/.env.example with V2 section** - `a05cea2` (feat)

## Files Created/Modified

- `backend/app/config.py` - Added 5 typed V2 fields after `langchain_project` with a `# V2 agent tuning knobs` comment block
- `backend/.env.example` - New file documenting all V1 env vars plus V2 Agent Tuning section with GITHUB_TOKEN, MAX_CRITIC_LOOPS, CRITIC_THRESHOLD, DEBUGGER_MAX_HOPS, REVIEWER_CONTEXT_HOPS

## V2 Fields Reference

| Field | Type | Default | Env Var | Requirement |
|---|---|---|---|---|
| `github_token` | str | `""` | `GITHUB_TOKEN` | MCP-01 |
| `max_critic_loops` | int | `2` | `MAX_CRITIC_LOOPS` | CRIT-03 |
| `critic_threshold` | float | `0.7` | `CRITIC_THRESHOLD` | CRIT-02 |
| `debugger_max_hops` | int | `4` | `DEBUGGER_MAX_HOPS` | DBUG-01 |
| `reviewer_context_hops` | int | `1` | `REVIEWER_CONTEXT_HOPS` | REVW-01 |

## How Downstream Phases Access These Settings

```python
from app.config import get_settings

s = get_settings()
if s.github_token:                  # GitHub MCP enabled only if token set
    ...
for _ in range(s.max_critic_loops): # Critic loop hard cap
    ...
if score >= s.critic_threshold:     # Critic retry gate
    ...
```

## Test Override Pattern for Agent Phases

Agent tests should instantiate Settings directly (not via get_settings) to avoid lru_cache pollution:

```python
from app.config import Settings

s = Settings(
    postgres_user="x", postgres_password="x", postgres_db="x",
    max_critic_loops=1,      # override for test
    critic_threshold=0.5,
)
```

## Decisions Made

- All five V2 fields are optional with safe defaults — `github_token=""` means GitHub MCP is silently disabled, matching MCP-01 spec
- `critic_threshold` is typed as `float` (not `int`) so values like `0.7` and `0.8` are accepted without coercion issues
- No new imports or modules needed — pydantic-settings handles UPPER_SNAKE_CASE env var mapping automatically

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. The test environment had `GITHUB_TOKEN` set as a system env var; verification used `env -i` to confirm clean defaults without env leakage. The Settings class correctly picked up the system value — this is correct behaviour, not a bug.

## Next Phase Readiness

- All V2 config fields are available via `get_settings()` — Phase 17 (router-agent) can import and use them immediately
- `max_critic_loops` and `critic_threshold` are ready for Phase 20 (critic-agent)
- `debugger_max_hops` is ready for Phase 18 (debugger-agent)
- `reviewer_context_hops` is ready for Phase 19 (reviewer-agent)
- `github_token` is ready for Phase 21 (mcp-layer)

---
*Phase: 16-config-v2*
*Completed: 2026-03-21*

## Self-Check: PASSED

- backend/app/config.py: FOUND
- backend/.env.example: FOUND
- 16-01-SUMMARY.md: FOUND
- Commit 82edac7: FOUND
- Commit a05cea2: FOUND
