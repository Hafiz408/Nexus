from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.index_router import router as index_router
from app.api.query_router import router as query_router
from app.db.database import init_db
from app.ingestion.embedder import init_pgvector_table


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_pgvector_table()
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

app.include_router(index_router)
app.include_router(query_router)


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}
