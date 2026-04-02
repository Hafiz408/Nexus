# Phase 27: wire-review-test-e2e - Research

**Researched:** 2026-03-25
**Domain:** VS Code Extension TypeScript / Python FastAPI integration — closing extension-to-backend data flow gaps
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| REVW-01 | Reviewer assembles context from target + callers + callees | reviewer.py is fully implemented; crashes only because target_node_id is None from extension — fixing the extension data flow unblocks this |
| REVW-02 | Reviewer generates structured Finding objects | Same root cause as REVW-01; unit tests pass, E2E blocked by None target_node_id |
| REVW-03 | Targets user-selected code range when provided | selected_file and selected_range must be added to types.ts query message and forwarded through SseStream → SidebarProvider |
| TEST-01 | Detects test framework from repo structure | tester.py is fully implemented; crashes because target_node_id is None — same fix as REVW-01 |
| TEST-02 | Identifies CALLS-edge callees as mock targets | Blocked by same INT-01 crash |
| TEST-03 | Generates runnable test code | Blocked by same INT-01 crash |
| TEST-04 | Derives correct test file path per framework convention | Blocked by same INT-01 crash |
| TEST-05 | Generates correct mock/patch syntax for detected framework | Blocked by same INT-01 crash |
| MCP-01 | GitHub MCP posts reviewer findings as inline PR comments | post_review_comments() is fully implemented; SidebarProvider.ts has a TODO stub — INT-02 fix |
| MCP-03 | Filesystem MCP writes tester output to derived file path | write_test_file() is already called in query_router.py (Phase 26); unblocked by fixing INT-01 |
| EXT-06 | Review panel renders findings with severity badges | ReviewPanel in App.tsx is complete; backend crash is the only blocker |
| EXT-07 | Shows "Post to GitHub PR" button when token configured | ReviewPanel renders the button; SidebarProvider.ts case 'postReviewToPR' is a stub needing real implementation |
| EXT-08 | Test panel renders generated code block | TestPanel in App.tsx is complete; backend crash is the only blocker |
| EXT-09 | Shows "File written to: {path}" badge on MCP success | TestPanel renders the badge; already wired in query_router.py Phase 26 — unblocked by INT-01 fix |
</phase_requirements>

---

## Summary

Phase 27 is a gap-closure phase, not a greenfield build. The entire backend pipeline (reviewer.py, tester.py, orchestrator.py, mcp/tools.py) is fully implemented, unit-tested, and passing. The UI result panels (ReviewPanel, TestPanel, DebugPanel) in App.tsx are fully implemented. The sole blockers are two missing data-flow connections between the VS Code extension and the backend.

**INT-01** (critical): The extension's `WebviewToHostMessage` query type in `types.ts` declares only `{question, intent_hint?}`. It is missing `target_node_id`, `selected_file`, `selected_range`, and `repo_root`. Because the type is missing these fields, `SseStream.ts` cannot include them in the POST body, and `SidebarProvider.ts` cannot forward them from the webview message. When a review or test query reaches the backend with `target_node_id=None`, `reviewer.py:89` raises `ValueError: target_node_id required` and `tester.py:117` raises identically. Both crashes happen before any output is produced.

**INT-02** (major): The `postReviewToPR` case in `SidebarProvider.ts` (line 99–106) is a TODO stub that shows an information message. It needs to call `post_review_comments()` from `app/mcp/tools.py`. However, to do this the extension needs access to: the review findings (currently held in `structuredResult` in React state), PR number, commit SHA, and GitHub token. The backend already confirms token presence via `has_github_token` in the SSE result payload; the extension already receives this flag. The missing piece is how to retrieve PR number and commit SHA — the GitHub MCP tools API signature requires `repo: str, pr_number: int, commit_sha: str, github_token: str`.

**Primary recommendation:** Fix INT-01 first (4 extension TypeScript edits + 2 backend guard improvements), then wire INT-02 using the VS Code `vscode.window.showInputBox()` pattern to collect PR number and commit SHA from the user at post time — the simplest path that avoids requiring a full GitHub API integration in the extension.

---

## Standard Stack

No new dependencies are required for this phase. All libraries are already installed and in use.

### Core (already installed)

| Component | File | Role |
|-----------|------|------|
| TypeScript types.ts | extension/src/types.ts | Union type for webview→host messages |
| SseStream.ts | extension/src/SseStream.ts | Constructs POST body to /query |
| SidebarProvider.ts | extension/src/SidebarProvider.ts | Routes webview messages, calls streamQuery |
| streamQuery() | extension/src/SseStream.ts | Function signature already accepts intentHint |
| reviewer.py | backend/app/agent/reviewer.py | review() requires target_node_id: str (not Optional) |
| tester.py | backend/app/agent/tester.py | test() requires target_node_id: str (not Optional) |
| post_review_comments() | backend/app/mcp/tools.py | Fully implemented — only call site is missing |
| query_router.py | backend/app/api/query_router.py | Already forwards all 4 fields from QueryRequest to initial_state |
| QueryRequest | backend/app/models/schemas.py | Already has all 4 Optional fields |

### VS Code Extension APIs needed

| API | Purpose | Already used |
|-----|---------|--------------|
| `vscode.window.activeTextEditor` | Get currently open file path and selection | No — needed for Phase 27 |
| `editor.selection` | Get line range of selection | No — needed for Phase 27 |
| `editor.document.uri.fsPath` | Get absolute file path | No — needed for Phase 27 |
| `vscode.window.showInputBox()` | Prompt user for PR number and commit SHA | No — needed for INT-02 |
| `vscode.workspace.workspaceFolders` | Already used for repo_root | Yes |

---

## Architecture Patterns

### Current data flow (broken)

```
App.tsx (React)
  └─ vscode.postMessage({ type:'query', question, intent_hint? })
       │
       └─> SidebarProvider.ts case 'query'
             └─ streamQuery(msg.question, repoPath, webview, backendUrl, ..., msg.intent_hint)
                  │
                  └─> SseStream.ts POST /query
                        body: { question, repo_path, intent_hint }
                        MISSING: target_node_id, selected_file, selected_range, repo_root
```

### Target data flow (fixed)

```
App.tsx (React)
  └─ vscode.postMessage({
       type:'query',
       question,
       intent_hint?,
       target_node_id?,   ← NEW (populated from active editor context in SidebarProvider)
       selected_file?,    ← NEW
       selected_range?,   ← NEW [lineStart, lineEnd]
       repo_root?         ← NEW (same as repoPath for now)
     })
       │
       └─> SidebarProvider.ts case 'query'
             ├─ Captures: editor = vscode.window.activeTextEditor
             ├─ selected_file = editor?.document.uri.fsPath
             ├─ selected_range = [editor.selection.start.line+1, editor.selection.end.line+1]
             ├─ target_node_id = msg.target_node_id (forwarded from webview if provided)
             └─ streamQuery(msg.question, repoPath, webview, backendUrl, citations_cb,
                            msg.intent_hint, target_node_id, selected_file, selected_range, repoPath)
                  │
                  └─> SseStream.ts POST /query
                        body: {
                          question, repo_path, intent_hint,
                          target_node_id, selected_file, selected_range, repo_root
                        }
```

### Pattern 1: Extend WebviewToHostMessage query variant (types.ts)

**What:** Add the 4 missing optional fields to the query union member.
**When to use:** Any time the webview needs to send context about the active editor to the backend.
**Example:**
```typescript
// extension/src/types.ts
export type WebviewToHostMessage =
  | {
      type: 'query';
      question: string;
      intent_hint?: string;
      target_node_id?: string;    // ADD
      selected_file?: string;     // ADD
      selected_range?: [number, number];  // ADD  [line_start, line_end] 1-indexed
      repo_root?: string;         // ADD
    }
  | { type: 'openFile'; filePath: string; lineStart: number }
  | { type: 'indexWorkspace' }
  | { type: 'clearIndex' }
  | { type: 'postReviewToPR' };
```

### Pattern 2: Extend streamQuery() signature (SseStream.ts)

**What:** Add 4 new optional parameters after intentHint; include them in POST body.
**When to use:** streamQuery is the single POST construction point.
**Example:**
```typescript
// extension/src/SseStream.ts  — updated signature
export async function streamQuery(
  question: string,
  repoPath: string,
  webview: vscode.Webview,
  backendUrl: string,
  onCitations?: (citations: Citation[]) => void,
  intentHint?: string,
  targetNodeId?: string,      // NEW
  selectedFile?: string,      // NEW
  selectedRange?: [number, number],  // NEW
  repoRoot?: string,          // NEW
): Promise<void> {
  // ...
  body: JSON.stringify({
    question,
    repo_path: repoPath,
    max_nodes: maxNodes,
    hop_depth: hopDepth,
    ...(intentHint    ? { intent_hint: intentHint }       : {}),
    ...(targetNodeId  ? { target_node_id: targetNodeId }  : {}),
    ...(selectedFile  ? { selected_file: selectedFile }   : {}),
    ...(selectedRange ? { selected_range: selectedRange } : {}),
    ...(repoRoot      ? { repo_root: repoRoot }           : {}),
  }),
```

### Pattern 3: Capture active editor context in SidebarProvider.ts

**What:** Read `vscode.window.activeTextEditor` at the time the query message is received, extract file/selection context, forward to streamQuery.
**When to use:** The review and test intents need to know what the user is looking at.
**Example:**
```typescript
// extension/src/SidebarProvider.ts  — case 'query' updated
case 'query':
  if (this._repoPath) {
    const config = vscode.workspace.getConfiguration('nexus');
    const backendUrl = config.get<string>('backendUrl', 'http://localhost:8000');
    this._highlight.clearHighlights();

    // Capture active editor context for review/test intents
    const editor = vscode.window.activeTextEditor;
    const selectedFile = editor?.document.uri.fsPath;
    const sel = editor?.selection;
    const selectedRange: [number, number] | undefined =
      sel && !sel.isEmpty
        ? [sel.start.line + 1, sel.end.line + 1]  // convert 0-indexed to 1-indexed
        : undefined;

    await streamQuery(
      msg.question,
      this._repoPath,
      webviewView.webview,
      backendUrl,
      (citations) => { void this._highlight.highlightCitations(citations); },
      msg.intent_hint,
      msg.target_node_id,          // forwarded from webview (may be undefined)
      selectedFile,                // from active editor
      selectedRange,               // from active selection
      this._repoPath,              // repo_root = repo_path (workspace root)
    );
  }
```

### Pattern 4: Wire postReviewToPR in SidebarProvider.ts (INT-02)

**What:** Replace the TODO stub with a real invocation that collects PR context via input boxes then calls the backend MCP endpoint.
**Decision required:** The backend `post_review_comments()` needs `pr_number`, `commit_sha`, and `github_token`. The token is already held by the backend (confirmed by `has_github_token` flag). The cleanest extension-side approach is to have the extension call a dedicated backend endpoint to post the review, or to call `post_review_comments` via the backend's `/query` response flow.

**Recommended approach:** The extension cannot call `post_review_comments` directly (it is a backend Python function). The cleanest path is to add a lightweight `POST /review/post-pr` endpoint (or reuse the SSE endpoint with a special intent) that the extension calls with `{findings, repo, pr_number, commit_sha}`. Alternatively, prompt the user for `pr_number` and `commit_sha` in the extension and POST to a new endpoint.

**Simplest viable path (Phase 27 scope):** The extension calls a new backend endpoint `POST /review/post-pr` with `{findings: [...], repo: "owner/repo", pr_number: int, commit_sha: str}`. The backend calls `post_review_comments()` using the token from settings.

**Alternative (no new endpoint):** Prompt user for `repo`, `pr_number`, `commit_sha` via `vscode.window.showInputBox()` and POST to a new tiny endpoint. This keeps all GitHub API logic on the server side (correct — the token stays server-side).

### Anti-Patterns to Avoid

- **Do not move the GitHub token to the extension:** The token is a server-side env var by design (Phase 16). The extension only receives a boolean flag confirming it is set.
- **Do not add selected_range as a tuple in the JSON body:** JSON does not have a tuple type. Send as `[start, end]` array from TypeScript; `QueryRequest.selected_range: Optional[tuple]` in Pydantic accepts a JSON array.
- **Do not attempt to derive target_node_id from the active editor filename alone:** The `node_id` format is `"relative_file_path::function_name"` (from AST parser). Without knowing the function the user intends to target, the extension cannot reliably construct a node_id. The correct approach for Phase 27 is to let `selected_file` + `selected_range` drive the review context, and leave `target_node_id` as an optional enhancement (user can provide it via the query text, or the backend can look it up from selected_file/selected_range).
- **Do not call reviewer.py or tester.py with an empty string for target_node_id:** The guard `if target_id not in G: raise ValueError` will still fire. For Phase 27, either the extension must provide a valid node_id, or the backend needs a fallback that derives target_node_id from selected_file/selected_range by searching the graph.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Getting active file in VS Code extension | Custom event listeners | `vscode.window.activeTextEditor` | The VS Code API provides this synchronously at call time |
| JSON serialization of Python tuple | Custom serializer | Send as list `[a, b]` from TypeScript; `Optional[tuple]` in Pydantic accepts JSON arrays | Pydantic already handles this; `Optional[tuple]` coerces JSON array to Python tuple |
| GitHub PR comment batching | Custom retry logic | `post_review_comments()` already implemented | 10-cap, overflow, 422 fallback, tenacity 5xx retry all done in Phase 23 |
| Test file writing with safety | Custom file I/O | `write_test_file()` already implemented | Path traversal guard, extension allowlist, overwrite protection all done in Phase 23 |
| TypeScript union narrowing | Manual type guards | TypeScript discriminated unions on `type` field | The existing `WebviewToHostMessage` pattern already works; just add fields |

**Key insight:** 90% of the work for this phase is already done. The entire implementation surface is 6 small edits (4 extension TypeScript files + 1 new backend endpoint + 1 test file update).

---

## Common Pitfalls

### Pitfall 1: target_node_id from extension will often be undefined for review/test
**What goes wrong:** A user selects "Review" intent without clicking on a specific function. `target_node_id` is `undefined` in the extension, which serializes as absent from the POST body, which means `QueryRequest.target_node_id` is `None`, which crashes reviewer.py:89.
**Why it happens:** The extension has no way to know which graph node corresponds to the user's cursor position without a lookup against the graph.
**How to avoid:** Add a backend-side fallback in `_review_node` and `_test_node` in `orchestrator.py`: if `target_node_id` is None but `selected_file` is provided, attempt to find the node in the graph whose `file_path` matches `selected_file` and `line_start/line_end` overlaps `selected_range`. If still no match, return a `ReviewResult` with an empty findings list and a summary explaining the target was not found (instead of crashing).
**Warning signs:** Backend returns `event: error` with `ValueError: target_node_id 'None' not found in graph`.

### Pitfall 2: selected_range as Python tuple from JSON array
**What goes wrong:** TypeScript sends `selected_range: [10, 20]`. Python's Pydantic receives it fine as a list, but `reviewer.py` type-hints `selected_range: tuple[int, int] | None`. If Pydantic does not coerce the list to a tuple, the reviewer range clause may fail.
**Why it happens:** `Optional[tuple]` in Pydantic v2 does NOT automatically coerce a list to a tuple.
**How to avoid:** In `schemas.py`, type `selected_range` as `Optional[list[int]] = None` (list of 2 ints) instead of `Optional[tuple]`. Then update reviewer.py's signature to accept `list[int] | None` for `selected_range`, or index it as `selected_range[0]`, `selected_range[1]`. Alternatively, keep `Optional[tuple]` and add a Pydantic validator using `@field_validator('selected_range', mode='before')` that coerces.
**Warning signs:** `TypeError: cannot unpack non-sequence` or `ValidationError` on `selected_range`.

**Verified:** `QueryRequest.selected_range: Optional[tuple] = None` — this is the current definition in `schemas.py`. This needs careful handling.

### Pitfall 3: Lazy import patch target for V2 endpoint tests
**What goes wrong:** Tests that exercise the `/query` V2 path must patch `app.api.query_router.build_graph` (the lazy-import binding site), not `app.agent.orchestrator.build_graph`.
**Why it happens:** The `from app.agent.orchestrator import build_graph` is inside `v2_event_generator()` body. When Python executes that import, it binds `build_graph` in the `query_router` module namespace. Patching at the source module does NOT intercept this binding.
**How to avoid:** Confirmed pattern from STATE.md Phase 24: `patch("app.agent.orchestrator.build_graph")` at the source module. Wait — STATE.md says "build_graph patched at source module (app.agent.orchestrator.build_graph)". Verify: test_query_router_v2.py uses `patch("app.agent.orchestrator.build_graph")`. This is correct because the lazy import inside the generator body executes `from app.agent.orchestrator import build_graph` freshly each call, so patching the source binding intercepts it.
**Warning signs:** `mock_graph.invoke` is never called; real orchestrator graph runs during tests.

### Pitfall 4: postReviewToPR needs the review findings stored somewhere accessible
**What goes wrong:** When the user clicks "Post to GitHub PR", App.tsx calls `vscode.postMessage({ type: 'postReviewToPR' })` with no payload. `SidebarProvider.ts` receives this message but has no access to the findings (they are in React state inside the webview).
**Why it happens:** The extension host and the webview are separate processes. The extension host only saw the `result` SSE event, which it forwarded to the webview. It did not store the findings.
**How to avoid:** Either (a) SidebarProvider stores the most recent ReviewResult when it receives the SSE `result` event and forwards it to the webview — SseStream.ts already forwards `result` events to the webview AND posts them to `webview.postMessage`. However, SidebarProvider never stores the result itself. OR (b) extend `postReviewToPR` message to include the findings from the webview: `{ type: 'postReviewToPR', findings: [...] }`. This is the simplest path — the webview already has the findings in `structuredResult.result.findings`.
**Warning signs:** `SidebarProvider` receives `postReviewToPR` but has no findings data to send.

**Recommended fix for INT-02:** Extend `postReviewToPR` message type to include findings, repo, pr_number, commit_sha from the webview. The extension host receives them and calls a new backend `POST /review/post-pr` endpoint. This endpoint calls `post_review_comments()` using `settings.github_token`.

### Pitfall 5: Line number indexing (0-indexed vs 1-indexed)
**What goes wrong:** VS Code's `editor.selection.start.line` is 0-indexed. reviewer.py expects 1-indexed line numbers (consistent with `line_start` in the graph node attributes, which are 1-indexed per `schemas.py`).
**How to avoid:** Always add 1 when converting from VS Code selection to `selected_range`: `sel.start.line + 1`.

### Pitfall 6: Tech debt cleanup — unused imports
**What goes wrong:** reviewer.py has `from pydantic import BaseModel, Field` but `Field` is unused. tester.py has `from typing import Literal` but `Literal` is unused. These will trigger linter warnings.
**How to avoid:** Remove the unused imports as part of Phase 27 cleanup.

---

## Code Examples

### Exact current crash sites

```python
# backend/app/agent/reviewer.py:88-89
def _assemble_context(G: nx.DiGraph, target_id: str) -> tuple[list[str], set[str]]:
    if target_id not in G:   # target_id is None → None not in G → raises ValueError
        raise ValueError(f"target_node_id {target_id!r} not found in graph")
```

```python
# backend/app/agent/tester.py:116-117
def _get_callees(G: nx.DiGraph, target_id: str) -> list[dict]:
    if target_id not in G:   # target_id is None → same crash
        raise ValueError(f"target_node_id {target_id!r} not found in graph")
```

Both are called with `state["target_node_id"]` from the orchestrator, which is `None` because the extension never sends it.

### Verified: QueryRequest already has all 4 fields

```python
# backend/app/models/schemas.py — ALREADY DONE (no changes needed)
class QueryRequest(BaseModel):
    question: str
    repo_path: str
    max_nodes: int = 10
    hop_depth: int = 1
    intent_hint: Optional[str] = None
    target_node_id: Optional[str] = None   # already present
    selected_file: Optional[str] = None    # already present
    selected_range: Optional[tuple] = None # already present — NOTE: tuple type needs care
    repo_root: Optional[str] = None        # already present
```

### Verified: query_router.py already forwards all 4 fields

```python
# backend/app/api/query_router.py lines 67-75 — ALREADY DONE (no changes needed)
initial_state = {
    "question": request_body.question,
    "repo_path": request_body.repo_path,
    "intent_hint": request_body.intent_hint,
    "G": G,
    "target_node_id": request_body.target_node_id,   # already forwarded
    "selected_file": request_body.selected_file,     # already forwarded
    "selected_range": request_body.selected_range,   # already forwarded
    "repo_root": request_body.repo_root,             # already forwarded
    ...
}
```

### Verified: orchestrator.py _review_node and _test_node already read these fields

```python
# backend/app/agent/orchestrator.py lines 164-172 — ALREADY DONE
def _review_node(state: NexusState) -> dict:
    result = review(
        state["question"],
        G,
        state["target_node_id"],              # reads from state — will be None if extension doesn't send it
        selected_file=state.get("selected_file"),
        selected_range=state.get("selected_range"),
    )

# lines 175-187
def _test_node(state: NexusState) -> dict:
    result = run_test(
        state["question"],
        G,
        state["target_node_id"],              # reads from state — will be None if extension doesn't send it
        repo_root=state.get("repo_root"),
    )
```

### Verified: SidebarProvider.ts TODO stub location

```typescript
// extension/src/SidebarProvider.ts lines 98-106
case 'postReviewToPR': {
  // TODO(Phase 27): Post review findings to the open GitHub PR via GitHub MCP.
  // Requires: active PR URL, GitHub token (already confirmed present when button is shown).
  // For now, inform the user this feature is coming.
  vscode.window.showInformationMessage(
    'Post to GitHub PR is not yet implemented. Coming in a future release.'
  );
  break;
}
```

### Node_id format (for reference)

```python
# backend/app/ingestion/ast_parser.py — node_id format
node_id = f"{rel_path}::{fname}"   # e.g. "app/agent/reviewer.py::review"
```

The extension does not currently compute node_ids. For Phase 27, the approach is to derive target from active editor context (file + selection), not require the user to type a node_id.

---

## Implementation Plan Summary

Phase 27 breaks into 4 logical work units:

**Unit A — Extension type and POST body (fixes INT-01)**
1. `types.ts`: add `target_node_id?`, `selected_file?`, `selected_range?: [number, number]`, `repo_root?` to query variant
2. `SseStream.ts`: add 4 new optional params; include in POST body
3. `SidebarProvider.ts`: capture `activeTextEditor` at query time; derive `selectedFile`, `selectedRange`; pass to `streamQuery`
4. `App.tsx`: `vscode.postMessage` for `query` already works — no change needed (fields are optional)

**Unit B — Backend guard improvement (prevents crashes when target_node_id is still None)**
5. `orchestrator.py` `_review_node`: if `target_node_id` is None, attempt to find node by `selected_file` + line range, or return graceful error ReviewResult
6. `orchestrator.py` `_test_node`: same guard

**Unit C — MCP call site (fixes INT-02)**
7. `types.ts`: extend `postReviewToPR` to carry `{ findings, repo, pr_number, commit_sha }`
8. `App.tsx` ReviewPanel: collect `repo` and `pr_number`/`commit_sha` via input, include in `postReviewToPR` message
9. `SidebarProvider.ts`: implement `postReviewToPR` case — call new backend endpoint
10. New backend endpoint `POST /review/post-pr` in `query_router.py` or `review_router.py`

**Unit D — Tech debt cleanup**
11. Remove unused `Field` import in `reviewer.py`
12. Remove unused `Literal` import in `tester.py`
13. Fix stale docstring in `test_query_router_v2.py`

---

## Open Questions

1. **How should the extension derive target_node_id?**
   - What we know: Node IDs are `"relative_path::function_name"` format. The active editor gives us file path and line number. The graph has `line_start`/`line_end` attributes on each node.
   - What's unclear: Should the extension call a backend `/nodes/at-location?file=...&line=...` endpoint to look up the node_id, or should the backend derive it from `selected_file`+`selected_range` internally?
   - Recommendation: Handle entirely on the backend side. In `_review_node` and `_test_node`, if `target_node_id` is None and `selected_file` is provided, scan `G.nodes` to find the node whose `file_path` matches and whose `line_start`/`line_end` bracket the selection. If found, use that node. This keeps the extension simple.

2. **What data does postReviewToPR need from the user?**
   - What we know: `post_review_comments()` requires `repo: str` (owner/repo format), `pr_number: int`, `commit_sha: str`, `github_token: str` (from settings). The extension cannot access the GitHub token.
   - What's unclear: Should the extension prompt for all three values, or can some be inferred from workspace context?
   - Recommendation: Use `vscode.window.showInputBox()` to prompt for `repo` (e.g. "owner/repo"), then `pr_number`, then `commit_sha`. Post to a new `POST /review/post-pr` endpoint that uses server-side `github_token`. This is the minimal viable implementation.

3. **Does selected_range need to be validated as a 2-element array?**
   - What we know: `QueryRequest.selected_range: Optional[tuple]` — Pydantic v2 with `Optional[tuple]` accepts a JSON array but the type annotation is loose.
   - What's unclear: Does the `tuple` type annotation in Pydantic v2 constrain element count?
   - Recommendation: Add a Pydantic `@field_validator` or change the type to `Optional[list[int]]` to avoid silent data corruption. This is a low-risk change with high safety value.

---

## Sources

### Primary (HIGH confidence)
- Direct code inspection of all 6 key files — findings are authoritative (no external sources needed for implementation research on this phase)
  - `extension/src/types.ts` — confirmed missing fields
  - `extension/src/SseStream.ts` — confirmed POST body construction
  - `extension/src/SidebarProvider.ts` — confirmed TODO stub location and streamQuery call
  - `backend/app/agent/reviewer.py` — confirmed crash site at line 88-89
  - `backend/app/agent/tester.py` — confirmed crash site at line 116-117
  - `backend/app/api/query_router.py` — confirmed all 4 fields already forwarded
  - `backend/app/models/schemas.py` — confirmed QueryRequest already has all 4 fields
  - `backend/app/agent/orchestrator.py` — confirmed _review_node and _test_node read from state
  - `backend/app/mcp/tools.py` — confirmed post_review_comments() signature and behavior
  - `extension/src/webview/App.tsx` — confirmed ReviewPanel renders postReviewToPR button
- `.planning/v2.0-MILESTONE-AUDIT.md` — confirmed INT-01 and INT-02 root cause analysis
- `.planning/STATE.md` — confirmed locked decisions (lazy import patterns, patch strategies)

### Secondary (MEDIUM confidence)
- VS Code Extension API: `vscode.window.activeTextEditor`, `editor.selection` — well-documented API, consistent across VS Code 1.x

---

## Metadata

**Confidence breakdown:**
- INT-01 root cause: HIGH — code verified directly; crash paths traced end-to-end
- INT-02 root cause: HIGH — TODO stub confirmed in SidebarProvider.ts line 99
- Fix approach for INT-01: HIGH — 4 specific file edits fully specified with exact code
- Fix approach for INT-02: MEDIUM — requires design decision on how to collect PR context (input boxes vs dedicated endpoint vs other)
- Backend guard approach: MEDIUM — the graph scan approach is reasonable but not yet prototyped
- selected_range tuple/list issue: MEDIUM — Pydantic v2 behavior with Optional[tuple] not fully verified against live runtime

**Research date:** 2026-03-25
**Valid until:** 2026-04-25 (stable codebase; no fast-moving external dependencies)
