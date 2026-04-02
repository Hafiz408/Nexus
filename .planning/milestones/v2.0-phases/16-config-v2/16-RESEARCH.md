# Phase 16: config-v2 - Research

**Researched:** 2026-03-21
**Domain:** Python environment-variable configuration with pydantic-settings
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CONF-01 | System can be configured with `github_token`, `max_critic_loops`, `critic_threshold`, `debugger_max_hops`, `reviewer_context_hops` via environment variables, all optional with safe defaults | pydantic-settings BaseSettings field defaults pattern — add fields with typed defaults to existing Settings class |
| CONF-02 | `.env.example` documents all new V2 environment variables | Extend existing `backend/.env.example` with a clearly labelled V2 block |
</phase_requirements>

---

## Summary

Phase 16 is purely a configuration extension — no new libraries, no new modules. The project already uses `pydantic-settings` 2.x (`BaseSettings` + `SettingsConfigDict`) in `backend/app/config.py`. The task is to add five new optional fields with safe defaults to the existing `Settings` class and update `backend/.env.example`.

The existing pattern is correct and must be followed exactly: typed field declarations with inline defaults, loaded via `SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")`. No additional libraries are needed. No new modules are needed. The `get_settings()` function is already cached with `@lru_cache` and is the correct access point for all downstream agents.

The only files that change in this phase are `backend/app/config.py` (add fields) and `backend/.env.example` (document the new variables). Downstream agents (Debugger, Reviewer, Critic, MCP layer) will import `get_settings()` and read the new fields — but that wiring happens in their respective phases.

**Primary recommendation:** Add the five V2 fields to the existing `Settings` class with typed defaults. Extend `.env.example` with a V2 section. No new files, no new dependencies.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic-settings | >=2.0.0 (already in requirements.txt) | BaseSettings — env var loading, type coercion, .env file support | Already the project standard; provides validation, type coercion, and .env loading in one class |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| functools.lru_cache | stdlib | Cache Settings singleton | Already used in get_settings() — do not change |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pydantic-settings BaseSettings | python-dotenv + manual os.getenv | No type coercion, no validation — do not use, pydantic-settings is already the project standard |
| pydantic-settings BaseSettings | dynaconf | Heavier dependency, not already present — do not introduce |

**Installation:**
```bash
# No new installation needed — pydantic-settings>=2.0.0 already in requirements.txt
```

---

## Architecture Patterns

### Recommended Project Structure

No structural change. Only two files are modified:

```
backend/
├── app/
│   └── config.py           # ADD five new fields to Settings class
└── .env.example            # ADD V2 section with new variables
```

### Pattern 1: Adding Optional Fields with Defaults to BaseSettings

**What:** Declare a new field in the `Settings` class body with a Python type annotation and a default value. pydantic-settings will read the matching env var (uppercased field name) if set; otherwise fall back to the default.

**When to use:** Any new runtime knob that must be tunable without code changes.

**Example:**
```python
# Source: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
# In backend/app/config.py — extend the existing Settings class:

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- existing V1 fields (unchanged) ---
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    embedding_provider: str = "mistral"
    llm_provider: str = "mistral"
    mistral_api_key: str = ""
    openai_api_key: str = ""
    model_name: str = "mistral-small-latest"
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "nexus-v1"

    # --- V2 agent tuning knobs ---
    github_token: str = ""
    max_critic_loops: int = 2
    critic_threshold: float = 0.7
    debugger_max_hops: int = 4
    reviewer_context_hops: int = 1
```

**Field mapping (env var → Settings field → default):**

| Env Var | Settings Field | Type | Default | Rationale |
|---------|---------------|------|---------|-----------|
| `GITHUB_TOKEN` | `github_token` | `str` | `""` | Empty string = feature disabled (MCP GitHub skips silently per MCP-01) |
| `MAX_CRITIC_LOOPS` | `max_critic_loops` | `int` | `2` | CRIT-03 hard cap — must default to the required hard cap |
| `CRITIC_THRESHOLD` | `critic_threshold` | `float` | `0.7` | CRIT-02 threshold — defaults to the 0.7 requirement value |
| `DEBUGGER_MAX_HOPS` | `debugger_max_hops` | `int` | `4` | DBUG-01 specifies up to 4 hops — default matches requirement |
| `REVIEWER_CONTEXT_HOPS` | `reviewer_context_hops` | `int` | `1` | REVW-01 specifies 1-hop — default matches requirement |

### Pattern 2: Downstream Access

**What:** Every agent module reads the new fields through the existing `get_settings()` factory. No agent imports Settings directly.

**When to use:** All V2 agent modules (Debugger, Reviewer, Critic, MCP tools).

**Example (how downstream phases will use these settings):**
```python
# In any future agent module:
from app.config import get_settings

settings = get_settings()
max_hops = settings.debugger_max_hops       # int, defaults to 4
threshold = settings.critic_threshold        # float, defaults to 0.7
token = settings.github_token               # str, "" means disabled
```

### Pattern 3: .env.example Extension

**What:** Append a clearly labelled V2 section to the existing `backend/.env.example`. Each variable gets an inline comment with type, description, and default.

**Example:**
```bash
# V2 Agent Tuning
# ---------------------------------------------------------------------------

# GitHub personal access token — required for GitHub MCP PR comments (MCP-01)
# Leave empty to disable GitHub MCP (silently skipped)
GITHUB_TOKEN=

# Maximum critic retry loops before forcing output (CRIT-02, CRIT-03)
# Type: int | Default: 2 | Range: 1-N (hard cap enforced in Critic agent)
MAX_CRITIC_LOOPS=2

# Critic quality gate threshold — score below this triggers a retry (CRIT-02)
# Type: float | Default: 0.7 | Range: 0.0–1.0
CRITIC_THRESHOLD=0.7

# Maximum call graph traversal hops in Debugger agent (DBUG-01)
# Type: int | Default: 4 | Range: 1-N
DEBUGGER_MAX_HOPS=4

# Context hop radius for Reviewer agent (REVW-01)
# Type: int | Default: 1 | Range: 1-N (1 = callers + callees only)
REVIEWER_CONTEXT_HOPS=1
```

### Anti-Patterns to Avoid

- **Reading env vars directly with os.getenv():** All config access must go through `get_settings()`. Direct `os.getenv()` bypasses type coercion and the `.env` file loading.
- **Hardcoding V2 knob values in agent modules:** Values like `max_critic_loops=2` must NOT appear as literals in agent code — they must come from `settings.max_critic_loops`.
- **Calling `Settings()` directly outside `get_settings()`:** The `@lru_cache` on `get_settings()` ensures a single instance per process. Bypassing it creates duplicate instances and can cause test interference.
- **Clearing the lru_cache in tests via monkeypatching the wrong target:** Tests that override config values must patch `app.config.get_settings` or call `get_settings.cache_clear()` + temporarily override env vars. See Pitfall 1.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Type-coercing env var strings to int/float | Custom parsing logic | pydantic-settings field type annotations | pydantic-settings automatically coerces `"4"` → `4` and `"0.7"` → `0.7`; handles validation errors with clear messages |
| Loading .env file | Custom file-reading code | pydantic-settings SettingsConfigDict | Already configured; handles encoding, file-not-found gracefully |
| Singleton config | Manual module-level variable | `@lru_cache` on `get_settings()` | Already the project pattern — one instance per process lifetime |

**Key insight:** pydantic-settings handles all the complexity of env var loading, type coercion, .env file parsing, and default fallback. The only work here is declaring typed fields.

---

## Common Pitfalls

### Pitfall 1: lru_cache Prevents Test Overrides
**What goes wrong:** Tests that set `os.environ["MAX_CRITIC_LOOPS"] = "1"` after `get_settings()` has already been called will see stale cached values.
**Why it happens:** `@lru_cache` returns the same `Settings` instance for the lifetime of the process. The test env var change happens after the cache is populated.
**How to avoid:** In test code, either (a) patch `get_settings` to return a custom Settings instance, or (b) call `get_settings.cache_clear()` before the test and restore it in teardown.
**Warning signs:** Tests pass in isolation but fail when run after other tests that triggered `get_settings()`.

### Pitfall 2: Field Name vs Env Var Name Casing
**What goes wrong:** Declaring `github_token: str` but expecting `GITHUBTOKEN` to work.
**Why it happens:** pydantic-settings uppercases the field name and maps it to the env var. `github_token` → `GITHUB_TOKEN` (pydantic-settings converts underscores to underscores, uppercases).
**How to avoid:** Keep field names snake_case; the env var is always the uppercase equivalent. `github_token` = `GITHUB_TOKEN`, `max_critic_loops` = `MAX_CRITIC_LOOPS`.
**Warning signs:** Environment variable is set but Settings still returns the default value.

### Pitfall 3: Overriding postgres_* Required Fields in Tests
**What goes wrong:** Adding new V2 fields may surface an existing issue where tests fail if `postgres_user` etc. are not set when Settings is instantiated.
**Why it happens:** `postgres_user`, `postgres_password`, `postgres_db` have no default — they are required. If test environments don't have these set, instantiating Settings fails.
**How to avoid:** When writing tests for config, use `Settings(postgres_user="x", postgres_password="x", postgres_db="x")` or ensure a .env file exists. Confirm existing test strategy — the V1 test suite passes in 0.37s so there's likely an existing approach.
**Warning signs:** `ValidationError` in tests when only testing V2 config fields.

### Pitfall 4: Not Using `float` for critic_threshold
**What goes wrong:** Declaring `critic_threshold: int = 0` instead of `critic_threshold: float = 0.7`.
**Why it happens:** Typo or confusion — `0.7` as integer truncates to `0`.
**How to avoid:** Declare as `float` explicitly.

---

## Code Examples

Verified patterns from official sources:

### Complete Updated config.py
```python
# Source: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # PostgreSQL (required — no defaults)
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # Provider selection (model-agnostic factory)
    embedding_provider: str = "mistral"
    llm_provider: str = "mistral"

    # API keys
    mistral_api_key: str = ""
    openai_api_key: str = ""

    # LLM model name
    model_name: str = "mistral-small-latest"

    # LangSmith (optional tracing)
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "nexus-v1"

    # V2 agent tuning knobs (all optional, safe defaults)
    github_token: str = ""
    max_critic_loops: int = 2
    critic_threshold: float = 0.7
    debugger_max_hops: int = 4
    reviewer_context_hops: int = 1


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

### Test Pattern for Config Overrides
```python
# Preferred approach: patch get_settings to return a custom instance
from unittest.mock import patch
from app.config import Settings

def test_critic_uses_threshold_from_config():
    custom = Settings(
        postgres_user="x", postgres_password="x", postgres_db="x",
        critic_threshold=0.8,
    )
    with patch("app.config.get_settings", return_value=custom):
        # ... test critic uses 0.8 threshold
        pass
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| pydantic v1 `BaseSettings` (pydantic built-in) | `pydantic-settings` standalone package | pydantic v2 release | Must import from `pydantic_settings`, not `pydantic` |
| Manual os.getenv with type casting | pydantic-settings type annotations | pydantic-settings 2.0 | No casting code needed |

**Deprecated/outdated:**
- `from pydantic import BaseSettings`: Removed in pydantic v2 — use `from pydantic_settings import BaseSettings`. Project already does this correctly.

---

## Open Questions

1. **Where is .env.example located — root or backend/?**
   - What we know: It currently lives at `backend/.env.example` (confirmed by reading the file)
   - What's unclear: Whether a root-level `.env.example` is also expected
   - Recommendation: Update `backend/.env.example` only — that is where all V1 vars already live

2. **Do V2 tests need to override config values?**
   - What we know: All V2 tests must use mock LLM + mock graph (STATE.md); individual agent tests will need specific threshold/hop values
   - What's unclear: Whether a shared `mock_settings` fixture should be added to conftest.py in this phase or in each agent phase
   - Recommendation: Phase 16 adds only a `# NOTE` comment to conftest.py pointing to the patch pattern; actual `mock_settings` fixtures are created in the agent phases that need them

---

## Sources

### Primary (HIGH confidence)
- https://docs.pydantic.dev/latest/concepts/pydantic_settings/ — BaseSettings field defaults, SettingsConfigDict, env_file, case mapping
- `backend/app/config.py` (read directly) — existing Settings class, SettingsConfigDict usage, lru_cache pattern
- `backend/requirements.txt` (read directly) — pydantic-settings>=2.0.0 already present
- `backend/.env.example` (read directly) — existing variable naming conventions and comment style
- `.planning/REQUIREMENTS.md` (read directly) — CONF-01, CONF-02 exact requirements
- `.planning/STATE.md` (read directly) — locked decisions, V2 context
- `.planning/PROJECT.md` (read directly) — tech stack, key decisions

### Secondary (MEDIUM confidence)
- WebSearch results for pydantic-settings 2.x optional fields — confirmed against official docs

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — pydantic-settings is already the project's config library; verified via requirements.txt and config.py
- Architecture: HIGH — existing config.py pattern is clear; only adding fields following the established pattern
- Pitfalls: HIGH — lru_cache cache-clearing pitfall is a known pydantic-settings testing pattern; field naming convention verified against official docs

**Research date:** 2026-03-21
**Valid until:** 2026-06-21 (pydantic-settings 2.x is stable; 90-day validity)
