"""Full end-to-end integration test for Nexus.

Covers:
  1. Extension TypeScript build    — node esbuild.js compiles without error
  2. Backend startup               — uvicorn starts; /api/health returns ok
  3. Config push                   — /api/config accepts provider/key from .env
  4. Explain intent (SSE)          — token events + citations + done
  5. Debug intent (SSE)            — result(debug) + done
  6. Review intent (SSE)           — result(review) + done
  7. Test intent (SSE)             — result(test) + done; written file cleaned up

No mocks. Real LLM calls. Requires API keys in .env.
Corpus: /Users/mohammedhafiz/Desktop/Personal/fastapi (must be pre-indexed).

Usage:
    python eval/test_e2e_http.py

    # Skip extension build if node not available:
    python eval/test_e2e_http.py --skip-extension-build

    # Target a different corpus (must be pre-indexed):
    python eval/test_e2e_http.py --repo /path/to/repo

Exit codes:
    0 — all checks passed
    1 — one or more checks failed
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

# ─── Paths ───────────────────────────────────────────────────────────────────

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "backend"))

_env = _root / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, v = _line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            os.environ.setdefault(k.strip(), v)

DEFAULT_REPO = "/Users/mohammedhafiz/Desktop/Personal/fastapi"
PORT = 8765
BASE_URL = f"http://localhost:{PORT}"

# Target file used for debug / review / test intents
TARGET_FILE = DEFAULT_REPO + "/fastapi/routing.py"
# Node IDs in the graph are relative to repo root (no leading slash, no repo prefix)
TARGET_NODE_ID = "fastapi/routing.py::run_endpoint_function"

# ─── Colours ─────────────────────────────────────────────────────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    mark = f"{GREEN}PASS{RESET}" if condition else f"{RED}FAIL{RESET}"
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)
    return condition


# ─── Extension build ─────────────────────────────────────────────────────────

def run_extension_build() -> bool:
    print(f"\n{BOLD}[1/7] Extension TypeScript build{RESET}")
    ext_dir = _root / "extension"
    node = shutil.which("node")
    if not node:
        print(f"  {YELLOW}SKIP{RESET}  node not found in PATH")
        return True  # not a failure — just skip

    result = subprocess.run(
        ["node", "esbuild.js"],
        cwd=ext_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )
    ok = result.returncode == 0
    check("extension build exits 0", ok, f"rc={result.returncode}")
    if not ok:
        if result.stdout:
            print("  stdout:", result.stdout[-500:])
        if result.stderr:
            print("  stderr:", result.stderr[-500:])
    else:
        print("  extension/out/ compiled successfully")
    return ok


# ─── Backend lifecycle ────────────────────────────────────────────────────────

def start_backend() -> subprocess.Popen:
    """Spawn uvicorn on PORT. Returns the process handle."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_root / "backend")
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "app.main:app",
            "--host", "127.0.0.1",
            "--port", str(PORT),
            "--log-level", "warning",
        ],
        cwd=_root / "backend",
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    return proc


def wait_for_health(timeout: int = 20) -> bool:
    """Poll /api/health until ok or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE_URL}/api/health", timeout=2)
            if r.status_code == 200 and r.json().get("status") == "ok":
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def stop_backend(proc: subprocess.Popen) -> None:
    try:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


# ─── Config push ─────────────────────────────────────────────────────────────

def _detect_config() -> dict:
    """Build a ConfigRequest payload from env variables."""
    chat_provider = os.environ.get("CHAT_PROVIDER", "ollama")
    chat_model = os.environ.get("CHAT_MODEL", "qwen2.5:7b")
    embed_provider = os.environ.get("EMBEDDING_PROVIDER", "ollama")
    embed_model = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
    ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

    api_keys: dict[str, str] = {}
    for key_env, provider in [
        ("OPENAI_API_KEY", "openai"),
        ("MISTRAL_API_KEY", "mistral"),
        ("ANTHROPIC_API_KEY", "anthropic"),
        ("GEMINI_API_KEY", "gemini"),
    ]:
        val = os.environ.get(key_env)
        if val:
            api_keys[provider] = val

    return {
        "chat_provider": chat_provider,
        "chat_model": chat_model,
        "embedding_provider": embed_provider,
        "embedding_model": embed_model,
        "ollama_base_url": ollama_url,
        "api_keys": api_keys,
    }


def push_config(repo: str) -> bool:
    print(f"\n{BOLD}[3/7] Config push{RESET}")
    cfg = _detect_config()
    cfg["db_path"] = repo + "/.nexus/graph.db"
    print(f"  chat: {cfg['chat_provider']}/{cfg['chat_model']}")
    print(f"  embed: {cfg['embedding_provider']}/{cfg['embedding_model']}")
    try:
        r = httpx.post(f"{BASE_URL}/api/config", json=cfg, timeout=10)
        data = r.json()
        ok = r.status_code == 200 and data.get("status") == "ok"
        check("config push returns ok", ok, f"status={r.status_code} body={data}")
        if data.get("reindex_required"):
            print(f"  {YELLOW}WARNING:{RESET} embedding model mismatch — reindex required before queries will be accurate")
        return ok
    except Exception as exc:
        check("config push returns ok", False, str(exc))
        return False


# ─── SSE helpers ─────────────────────────────────────────────────────────────

def _parse_sse_events(raw: str) -> list[dict]:
    """Parse raw SSE text into list of event dicts."""
    events = []
    for block in raw.split("\n\n"):
        for line in block.strip().splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    pass
    return events


def query_sse(
    question: str,
    repo: str,
    intent_hint: str | None,
    target_node_id: str | None = None,
    selected_file: str | None = None,
    timeout: int = 180,
) -> list[dict]:
    """Fire a /query SSE request and return all parsed events."""
    body: dict = {
        "question": question,
        "repo_path": repo,
        "db_path": repo + "/.nexus/graph.db",
        "max_nodes": 10,
        "hop_depth": 1,
    }
    if intent_hint is not None:
        body["intent_hint"] = intent_hint
    if target_node_id is not None:
        body["target_node_id"] = target_node_id
    if selected_file is not None:
        body["selected_file"] = selected_file

    raw_parts: list[str] = []
    with httpx.stream(
        "POST",
        f"{BASE_URL}/query",
        json=body,
        timeout=timeout,
        headers={"Accept": "text/event-stream"},
    ) as resp:
        for chunk in resp.iter_text():
            raw_parts.append(chunk)

    return _parse_sse_events("".join(raw_parts))


# ─── Intent checks ────────────────────────────────────────────────────────────

def _event_types(events: list[dict]) -> list[str]:
    return [e.get("type", "?") for e in events]


def _summarise_types(types: list[str]) -> str:
    """Collapse long token lists: token×N + other types."""
    token_count = types.count("token")
    others = [t for t in types if t != "token"]
    if token_count:
        return f"[token×{token_count}] + {others}"
    return str(types)


def _print_errors(events: list[dict]) -> None:
    for e in events:
        if e.get("type") == "error":
            print(f"  {RED}error event:{RESET} {e.get('message', e)}")


def check_explain(repo: str) -> bool:
    print(f"\n{BOLD}[4/7] Explain intent{RESET}")
    print("  query: How does FastAPI handle dependency injection?")
    try:
        events = query_sse(
            question="How does FastAPI handle dependency injection?",
            repo=repo,
            intent_hint="explain",
        )
    except Exception as exc:
        check("explain: no exception", False, str(exc))
        return False

    types = _event_types(events)
    _print_errors(events)
    print(f"  events received: {_summarise_types(types)}")

    ok = True
    ok &= check("explain: at least 1 token event", "token" in types, "")
    ok &= check("explain: citations event present", "citations" in types, "")
    ok &= check("explain: done event present", "done" in types, "")

    done_event = next((e for e in events if e.get("type") == "done"), None)
    if done_event:
        rstats = done_event.get("retrieval_stats") or {}
        if rstats:
            ok &= check(
                "explain: cross_encoder_used in retrieval_stats",
                "cross_encoder_used" in rstats,
                f"stats keys: {list(rstats.keys())}",
            )
            ok &= check(
                "explain: cross_encoder_used is True",
                rstats.get("cross_encoder_used") is True,
                f"got {rstats.get('cross_encoder_used')}",
            )
            print(f"  retrieval: seeds={rstats.get('seed_count')} returned={rstats.get('returned_count')}")
        else:
            print("  (no retrieval_stats in done event — CE check skipped)")

    cit_event = next((e for e in events if e.get("type") == "citations"), None)
    if cit_event:
        citations = cit_event.get("citations", [])
        ok &= check(
            "explain: citations non-empty",
            len(citations) > 0,
            f"got {len(citations)}",
        )
        if citations:
            print(f"  top citation: {citations[0].get('file_path')}:{citations[0].get('line_start')}")

    return ok


def check_debug(repo: str) -> bool:
    print(f"\n{BOLD}[5/7] Debug intent{RESET}")
    print(f"  target: {TARGET_FILE}")
    try:
        events = query_sse(
            question="Why might route registration fail?",
            repo=repo,
            intent_hint="debug",
            target_node_id=TARGET_NODE_ID,
            selected_file=TARGET_FILE,
        )
    except Exception as exc:
        check("debug: no exception", False, str(exc))
        return False

    types = _event_types(events)
    _print_errors(events)
    print(f"  events received: {_summarise_types(types)}")

    ok = True
    ok &= check("debug: result event present", "result" in types, "")
    ok &= check("debug: done event present", "done" in types, "")

    result_event = next((e for e in events if e.get("type") == "result"), None)
    if result_event:
        ok &= check(
            "debug: result.intent = debug",
            result_event.get("intent") == "debug",
            f"got {result_event.get('intent')}",
        )
        result_body = result_event.get("result", {})
        ok &= check(
            "debug: suspects list present",
            isinstance(result_body.get("suspects"), list),
            f"keys={list(result_body.keys())}",
        )
        suspects = result_body.get("suspects", [])
        if suspects:
            print(f"  top suspect: {suspects[0].get('node_id')} score={suspects[0].get('anomaly_score')}")

    return ok


def check_review(repo: str) -> bool:
    print(f"\n{BOLD}[6/7] Review intent{RESET}")
    print(f"  target: {TARGET_FILE}")
    try:
        events = query_sse(
            question="Review this routing code for correctness and edge cases.",
            repo=repo,
            intent_hint="review",
            target_node_id=TARGET_NODE_ID,
            selected_file=TARGET_FILE,
        )
    except Exception as exc:
        check("review: no exception", False, str(exc))
        return False

    types = _event_types(events)
    _print_errors(events)
    print(f"  events received: {_summarise_types(types)}")

    ok = True
    ok &= check("review: result event present", "result" in types, "")
    ok &= check("review: done event present", "done" in types, "")

    result_event = next((e for e in events if e.get("type") == "result"), None)
    if result_event:
        ok &= check(
            "review: result.intent = review",
            result_event.get("intent") == "review",
            f"got {result_event.get('intent')}",
        )
        result_body = result_event.get("result", {})
        ok &= check(
            "review: findings list present",
            isinstance(result_body.get("findings"), list),
            f"keys={list(result_body.keys())}",
        )
        findings = result_body.get("findings", [])
        if findings:
            f0 = findings[0]
            print(f"  top finding: [{f0.get('severity')}] {f0.get('category')} — {str(f0.get('suggestion',''))[:80]}")

    return ok


def check_test(repo: str) -> bool:
    print(f"\n{BOLD}[7/7] Test intent{RESET}")
    print(f"  target: {TARGET_FILE}")
    written_path: str | None = None
    try:
        events = query_sse(
            question="Generate tests for the route registration logic.",
            repo=repo,
            intent_hint="test",
            target_node_id=TARGET_NODE_ID,
            selected_file=TARGET_FILE,
        )
    except Exception as exc:
        check("test: no exception", False, str(exc))
        return False

    types = _event_types(events)
    _print_errors(events)
    print(f"  events received: {_summarise_types(types)}")

    ok = True
    ok &= check("test: result event present", "result" in types, "")
    ok &= check("test: done event present", "done" in types, "")

    result_event = next((e for e in events if e.get("type") == "result"), None)
    if result_event:
        ok &= check(
            "test: result.intent = test",
            result_event.get("intent") == "test",
            f"got {result_event.get('intent')}",
        )
        result_body = result_event.get("result", {})
        ok &= check(
            "test: test_code present",
            bool(result_body.get("test_code")),
            f"keys={list(result_body.keys())}",
        )
        written_path = result_event.get("written_path")
        if result_event.get("file_written") and written_path:
            print(f"  test file written: {written_path}")

    # Cleanup any generated test file so we don't pollute the corpus
    if written_path and Path(written_path).exists():
        Path(written_path).unlink()
        print(f"  test file cleaned up: {written_path}")

    return ok


# ─── Main ─────────────────────────────────────────────────────────────────────

def main(repo: str, skip_extension_build: bool) -> bool:
    if not Path(repo + "/.nexus/graph.db").exists():
        print(f"{RED}ERROR:{RESET} corpus not indexed at {repo}/.nexus/graph.db")
        print("  Run 'Nexus: Index Workspace' on this repo first.")
        sys.exit(1)

    all_ok = True

    # 1. Extension build
    if not skip_extension_build:
        all_ok &= run_extension_build()
    else:
        print(f"\n{BOLD}[1/7] Extension build{RESET}  {YELLOW}SKIPPED{RESET} (--skip-extension-build)")

    # 2. Start backend
    print(f"\n{BOLD}[2/7] Backend startup{RESET}")
    proc = start_backend()
    try:
        alive = wait_for_health(timeout=20)
        if not check("backend /api/health returns ok", alive, f"port={PORT}"):
            stderr_tail = proc.stderr.read(1000).decode(errors="replace") if proc.stderr else ""
            if stderr_tail:
                print("  stderr:", stderr_tail)
            all_ok = False
            return all_ok

        version = httpx.get(f"{BASE_URL}/api/health", timeout=5).json().get("version", "?")
        print(f"  backend running  version={version}  port={PORT}")

        # 3. Config
        all_ok &= push_config(repo)

        # 4-7. Intent queries
        all_ok &= check_explain(repo)
        all_ok &= check_debug(repo)
        all_ok &= check_review(repo)
        all_ok &= check_test(repo)

    finally:
        stop_backend(proc)
        print(f"\n  backend stopped")

    return all_ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nexus end-to-end integration test")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="Pre-indexed corpus path")
    parser.add_argument(
        "--skip-extension-build",
        action="store_true",
        help="Skip TypeScript extension build step",
    )
    args = parser.parse_args()

    passed = main(repo=args.repo, skip_extension_build=args.skip_extension_build)

    print()
    if passed:
        print(f"{GREEN}{BOLD}All e2e checks passed.{RESET}")
        sys.exit(0)
    else:
        print(f"{RED}{BOLD}Failures:{RESET}")
        for f in _failures:
            print(f"  • {f}")
        sys.exit(1)
