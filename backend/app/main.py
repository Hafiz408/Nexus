from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.database import init_db
from app.ingestion.embedder import init_pgvector_table


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_pgvector_table()
    yield


app = FastAPI(title="Nexus API", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}
