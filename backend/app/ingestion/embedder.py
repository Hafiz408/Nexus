"""Embedding and storage layer for Phase 5.

Sends CodeNode.embedding_text to OpenAI, writes dense vectors to pgvector,
and writes names to SQLite FTS5 for exact-match lookup.
"""

import sqlite3

from openai import OpenAI
from pgvector.psycopg2 import register_vector
from psycopg2.extras import execute_values

from app.config import get_settings
from app.db.database import get_db_connection
from app.models.schemas import CodeNode

EMBED_BATCH_SIZE = 100


def init_pgvector_table() -> None:
    """Create the code_embeddings table and ivfflat index idempotently.

    Uses autocommit (set by get_db_connection()) so no explicit commit needed.
    register_vector() is called per-connection as required by pgvector.
    """
    conn = get_db_connection()
    try:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS code_embeddings (
                    id         TEXT PRIMARY KEY,
                    repo_path  TEXT NOT NULL,
                    name       TEXT NOT NULL,
                    file_path  TEXT NOT NULL,
                    line_start INT,
                    line_end   INT,
                    embedding  vector(1536)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_code_embeddings_ivfflat
                ON code_embeddings
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
            """)
    finally:
        conn.close()


def _sqlite_db_path() -> str:
    """Return the path to the shared SQLite database file."""
    return "data/nexus.db"


def _init_fts_table(db_path: str) -> None:
    """Create the code_fts FTS5 virtual table idempotently.

    FTS5 content='' means the table stores its own copies of indexed text
    (no external content). node_id is UNINDEXED so it is stored but not
    searched; name is the primary search column.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS code_fts
            USING fts5(node_id UNINDEXED, name, file_path UNINDEXED, content='')
        """)
        conn.commit()
    finally:
        conn.close()


def embed_and_store(nodes: list[CodeNode], repo_path: str) -> int:
    """Embed a list of CodeNodes and persist them to pgvector and FTS5.

    The OpenAI client is initialised lazily inside this function body so that
    importing this module does not raise a ValidationError when OPENAI_API_KEY
    is absent (e.g. during test collection).

    Processes nodes in batches of EMBED_BATCH_SIZE (100). Each batch is
    upserted atomically to both stores:
      - pgvector: ON CONFLICT (id) DO UPDATE
      - FTS5:     DELETE + INSERT (FTS5 has no ON CONFLICT support)

    Args:
        nodes:     List of parsed CodeNode objects whose embedding_text fields
                   will be sent to the OpenAI embeddings API.
        repo_path: Repository root path stored alongside each row for
                   provenance filtering.

    Returns:
        Total number of nodes stored (== len(nodes) if all batches succeed).
    """
    # Lazy client init — must NOT be at module level (OPENAI_API_KEY may be absent)
    client = OpenAI(api_key=get_settings().openai_api_key)

    pg_conn = get_db_connection()
    register_vector(pg_conn)

    db_path = _sqlite_db_path()
    _init_fts_table(db_path)
    sqlite_conn = sqlite3.connect(db_path)

    total_stored = 0

    try:
        for i in range(0, len(nodes), EMBED_BATCH_SIZE):
            batch = nodes[i : i + EMBED_BATCH_SIZE]
            texts = [n.embedding_text for n in batch]

            # --- Call OpenAI embeddings API ---
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=texts,
            )
            # Preserve order by sorting on the response index
            embeddings = [
                item.embedding
                for item in sorted(response.data, key=lambda x: x.index)
            ]

            # --- Upsert to pgvector ---
            pg_rows = [
                (n.node_id, repo_path, n.name, n.file_path, n.line_start, n.line_end, emb)
                for n, emb in zip(batch, embeddings)
            ]
            with pg_conn.cursor() as cur:
                execute_values(
                    cur,
                    """
                    INSERT INTO code_embeddings
                        (id, repo_path, name, file_path, line_start, line_end, embedding)
                    VALUES %s
                    ON CONFLICT (id) DO UPDATE SET
                        repo_path  = EXCLUDED.repo_path,
                        name       = EXCLUDED.name,
                        file_path  = EXCLUDED.file_path,
                        line_start = EXCLUDED.line_start,
                        line_end   = EXCLUDED.line_end,
                        embedding  = EXCLUDED.embedding
                    """,
                    pg_rows,
                )

            # --- Upsert to FTS5 (DELETE + INSERT, no ON CONFLICT in FTS5) ---
            sqlite_conn.executemany(
                "DELETE FROM code_fts WHERE node_id = ?",
                [(n.node_id,) for n in batch],
            )
            sqlite_conn.executemany(
                "INSERT INTO code_fts(node_id, name, file_path) VALUES (?, ?, ?)",
                [(n.node_id, n.name, n.file_path) for n in batch],
            )
            sqlite_conn.commit()

            total_stored += len(batch)

    finally:
        pg_conn.close()
        sqlite_conn.close()

    return total_stored
