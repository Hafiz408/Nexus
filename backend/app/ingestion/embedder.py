"""Embedding and storage layer for Phase 5.

Sends CodeNode.embedding_text to the configured embedding provider,
writes dense vectors to pgvector, and writes names to SQLite FTS5
for exact-match lookup. Provider is selected via EMBEDDING_PROVIDER
in .env — see app.core.model_factory for supported providers.
"""

import sqlite3

from pgvector.psycopg2 import register_vector
from psycopg2.extras import execute_values

from app.config import get_settings
from app.core.model_factory import get_embedding_client
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
        dims = get_embedding_client().dimensions
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS code_embeddings (
                    id         TEXT PRIMARY KEY,
                    repo_path  TEXT NOT NULL,
                    name       TEXT NOT NULL,
                    file_path  TEXT NOT NULL,
                    line_start INT,
                    line_end   INT,
                    embedding  vector({dims})
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
            USING fts5(node_id UNINDEXED, name, file_path UNINDEXED)
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
    # Instantiate via factory — provider determined by EMBEDDING_PROVIDER in .env
    embedder = get_embedding_client()

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

            embeddings = embedder.embed(texts)

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


def delete_embeddings_for_repo(repo_path: str) -> None:
    """Delete all pgvector and FTS5 rows for the given repo_path.

    Steps:
    1. Open a pgvector connection, collect all ``id`` values for the repo.
    2. DELETE those rows from ``code_embeddings``.
    3. If any node_ids were found, DELETE matching rows from ``code_fts``
       in SQLite (FTS5 keyed by node_id which equals the pgvector id column).
    """
    pg_conn = get_db_connection()
    register_vector(pg_conn)

    try:
        with pg_conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM code_embeddings WHERE repo_path = %s",
                (repo_path,),
            )
            node_ids = [row[0] for row in cur.fetchall()]
            cur.execute(
                "DELETE FROM code_embeddings WHERE repo_path = %s",
                (repo_path,),
            )
    finally:
        pg_conn.close()

    if node_ids:
        db_path = _sqlite_db_path()
        sqlite_conn = sqlite3.connect(db_path)
        try:
            placeholders = ",".join("?" * len(node_ids))
            sqlite_conn.execute(
                f"DELETE FROM code_fts WHERE node_id IN ({placeholders})",
                node_ids,
            )
            sqlite_conn.commit()
        finally:
            sqlite_conn.close()


def delete_embeddings_for_files(file_paths: list[str], repo_path: str) -> None:
    """Delete pgvector and FTS5 rows for a specific set of files in a repo.

    Used by the incremental re-index path to clean stale embeddings before
    re-parsing changed files.  Deletes by ``file_path`` (not ``node_id``) so
    renamed or removed functions that no longer appear in the AST are fully
    purged.

    Guards against an empty list: returns immediately without opening any DB
    connection when ``file_paths`` is empty.

    Args:
        file_paths: Absolute or repo-relative file paths whose rows should be
                    deleted from both stores.
        repo_path:  Repository root path used to scope the pgvector delete.
    """
    if not file_paths:
        return

    # --- Delete from pgvector code_embeddings ---
    pg_conn = get_db_connection()
    register_vector(pg_conn)
    try:
        placeholders = ", ".join(["%s"] * len(file_paths))
        params = [repo_path, *file_paths]
        with pg_conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM code_embeddings WHERE repo_path = %s AND file_path IN ({placeholders})",
                params,
            )
    finally:
        pg_conn.close()

    # --- Delete from FTS5 code_fts ---
    # file_path is declared UNINDEXED — must use plain WHERE, not MATCH syntax.
    sqlite_conn = sqlite3.connect(_sqlite_db_path())
    try:
        placeholders = ", ".join(["?"] * len(file_paths))
        sqlite_conn.execute(
            f"DELETE FROM code_fts WHERE file_path IN ({placeholders})",
            file_paths,
        )
        sqlite_conn.commit()
    finally:
        sqlite_conn.close()
