import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.config_router import router as config_router
from app.api.index_router import router as index_router
from app.api.query_router import router as query_router

logger = logging.getLogger(__name__)

# Configure root logger so all module-level loggers (pipeline, walker, etc.) emit output
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)


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
    yield


app = FastAPI(title="Nexus API", version="1.0.0", lifespan=lifespan)

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
