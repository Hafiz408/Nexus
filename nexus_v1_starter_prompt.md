# Nexus V1 — Claude Code Starter Prompt

Copy everything below the divider and paste it as your first message in Claude Code.

---

You are building **Nexus V1** — an AI-native codebase intelligence VS Code extension with a FastAPI multi-agent backend. Your full requirements are in `nexus_v1_prd.md` in this directory. Read it completely before doing anything else.

## Your first actions (before writing any code)

1. **Read `nexus_v1_prd.md` in full.** Understand every section: the repo structure, data models, all backend modules, the VS Code extension, Docker setup, test plan, and evaluation setup. Do not skim.

2. **Set up the git repo:**
   ```bash
   git init
   git remote add origin https://github.com/Hafiz408/Nexus.git
   git checkout -b feature/v1
   ```

3. **Run `/gsd:new-project`** to initialise GSD project tracking. When it asks about the project, describe it as:
   > "Nexus V1 — VS Code extension + FastAPI backend that parses a codebase into an AST-based code graph using tree-sitter, then uses graph-traversal RAG (semantic seed search + N-hop graph expansion) to answer questions grounded in actual code structure. Single Explorer agent with LangSmith tracing and RAGAS evaluation. Full spec is in nexus_v1_prd.md."
   
   When GSD asks for requirements or roadmap, point it to the PRD — all decisions are already made. Set the git branch to `feature/v1`.

## How to work

You have **full permissions** — all tool calls, all bash commands, all file writes are pre-approved. Do not stop to ask for permission. Do not ask clarifying questions unless something in the PRD is genuinely contradictory.

Work through the 14 implementation steps from Section 12 of the PRD **in order**, one step at a time using GSD's workflow:

```
For each step:
  /gsd:plan-phase N    → plan the step
  /gsd:execute-phase N → build it
  /gsd:verify-work N   → verify it works
  git commit           → atomic commit per step (meaningful message)
  git push origin feature/v1
```

Use `/gsd:quick` for small sub-tasks within a step (e.g. adding a missing import, fixing a test). Use the full plan → execute → verify cycle for each of the 14 numbered steps.

## Implementation order (from PRD Section 12)

Work through these steps exactly in sequence. Do not skip ahead.

1. Docker Compose up — PostgreSQL + pgvector running and healthy
2. `file_walker.py` + tests — walk a repo, return file list
3. `ast_parser.py` + tests — parse Python files, extract CodeNode objects
4. `graph_builder.py` + tests — build NetworkX graph, resolve edges
5. `embedder.py` — embed nodes into pgvector + FTS5
6. `pipeline.py` — orchestrate steps 2–5 together
7. `/index` endpoint — expose pipeline via FastAPI with background tasks
8. `graph_rag.py` + tests — 3-step graph-traversal RAG (testable without DB)
9. `explorer.py` — LangChain streaming agent with LangSmith tracing
10. `/query` endpoint — SSE streaming endpoint
11. VS Code extension — sidebar, BackendClient, SSE streaming to UI
12. `Highlighter.ts` — file:line decoration in editor
13. `FileWatcher.ts` — incremental re-index on file save
14. RAGAS eval — run baseline, record numbers in `eval/results/`

## Commit discipline

- One atomic commit per implementation step minimum
- Commit message format: `feat(v1): <what was built>` e.g. `feat(v1): ast parser with tree-sitter for Python and TypeScript`
- Push to `origin feature/v1` after every commit
- Never commit `.env` files or API keys — `.env` must be in `.gitignore` from step 1

## Non-negotiables (from PRD Section 11)

- All LLM calls must be traced in LangSmith — set `LANGCHAIN_TRACING_V2=true` from day one
- Explorer agent must never cite a file:line not present in retrieved nodes
- Ingestion must support incremental re-index via `changed_files` parameter
- SSE streaming is required — tokens stream, not batch response
- `graph_rag.py` unit tests must run without a database (use in-memory NetworkX fixture)
- No hardcoded API keys anywhere — all secrets via `.env` + pydantic-settings
- CORS must allow `vscode-webview://*`

## Definition of done

V1 is complete when every checkbox in PRD Section 13 is checked:
- `docker compose up` starts without errors
- Indexing the FastAPI repo completes in under 2 minutes
- POST `/query` returns a streamed, cited answer
- VS Code sidebar shows streaming tokens
- Clicking a citation highlights the correct line in the editor
- File save triggers incremental re-index within 5 seconds
- All pytest tests pass
- LangSmith dashboard shows traces
- RAGAS baseline scores committed to `eval/results/`
- README documents setup, architecture, and eval instructions

## Start now

Read `nexus_v1_prd.md`, run `/gsd:new-project`, then begin Step 1.
