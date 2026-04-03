import logging
import os
import signal
import sys
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.config_router import router as config_router
from app.api.index_router import router as index_router
from app.api.query_router import router as query_router

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Idle watchdog — self-terminate after this many seconds with no requests.
# Allows the detached sidecar to clean up when all IDE windows are closed.
# ---------------------------------------------------------------------------
_IDLE_TIMEOUT = 7200  # 120 minutes — fallback for crashed/closed VS Code windows
_last_request_time = time.monotonic()


def _start_idle_watchdog() -> None:
    """Start a daemon thread that sends SIGTERM to this process after _IDLE_TIMEOUT idle seconds."""
    def _watch() -> None:
        while True:
            time.sleep(30)
            if time.monotonic() - _last_request_time > _IDLE_TIMEOUT:
                logger.info("Nexus backend idle for %ds — shutting down.", _IDLE_TIMEOUT)
                os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_watch, daemon=True, name="idle-watchdog").start()


def _prewarm_cross_encoder() -> None:
    """Load the cross-encoder model into memory on startup.

    Runs in a daemon thread so startup time is unaffected. On first install,
    triggers the one-time 66MB model download. On subsequent starts warms
    the in-memory cache (~200ms disk load) before the first request arrives.
    Failures are logged; model loads on demand if pre-warm fails.
    """
    try:
        from app.retrieval.reranker import _get_reranker  # noqa: PLC0415
        _get_reranker()
        logger.info("cross-encoder model pre-warmed")
    except Exception as exc:  # noqa: BLE001
        logger.warning("cross-encoder pre-warm failed (loads on first query): %s", exc)


# Configure root logger so all module-level loggers (pipeline, walker, etc.) emit output
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
# Route warnings.warn() calls through the logging system so they get timestamps too
logging.captureWarnings(True)


def _check_sqlite_vec() -> None:
    """Verify sqlite-vec can be loaded; exit with a clear message if not."""
    import sqlite3 as _sqlite3
    import sqlite_vec as _sqlite_vec
    conn = _sqlite3.connect(":memory:")
    try:
        conn.enable_load_extension(True)
    except AttributeError:
        conn.close()
        logger.error(
            "sqlite3.enable_load_extension is not available in this Python build. "
            "Nexus requires it for vector search.\n"
            "Fix: PYTHON_CONFIGURE_OPTS='--enable-loadable-sqlite-extensions' "
            "pyenv install 3.11.13 --force"
        )
        sys.exit(1)
    _sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_sqlite_vec()
    app.state.graph_cache = {}   # dict[str, nx.DiGraph] — lazy per-repo graph cache
    _start_idle_watchdog()
    threading.Thread(target=_prewarm_cross_encoder, daemon=True, name="ce-prewarm").start()
    yield


app = FastAPI(title="Nexus API", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def _reset_idle_timer(request, call_next):
    global _last_request_time
    _last_request_time = time.monotonic()
    return await call_next(request)


# CORS must be registered before include_router — middleware wraps the full app stack
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_origin_regex=r"vscode-webview://.*",
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(config_router, prefix="/api")
app.include_router(index_router)
app.include_router(query_router)
