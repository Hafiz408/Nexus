"""Embedding and storage layer for Phase 5.

Sends CodeNode.embedding_text to the configured embedding provider,
writes dense vectors to sqlite-vec, and writes names to SQLite FTS5
for exact-match lookup. Provider is selected via EMBEDDING_PROVIDER
in .env — see app.core.model_factory for supported providers.
"""

import logging
import os
import sqlite3

import sqlite_vec

from app.core.model_factory import get_embedding_client
from app.models.schemas import CodeNode

logger = logging.getLogger(__name__)

# Maximum characters sent per text to the embedding API.
# Keeps each input well under all providers' per-text token limits
# (Gemini: ~2 K tokens, OpenAI: ~8 K, Mistral/Ollama: ~16 K).
MAX_EMBED_TEXT_CHARS = 6_000  # ≈ 1 500 tokens @ 4 chars/token

# Conservative token budget per API request (total across all texts in one call).
# Mistral mistral-embed hard-caps at 16 384 — we target 12 000 to leave headroom.
EMBED_TOKEN_BUDGET = 12_000

# Absolute ceiling on items per batch regardless of token estimate.
EMBED_BATCH_SIZE_MAX = 64


def _build_batches(nodes: list) -> list[list]:
    """Build variable-size batches that stay within the per-request token budget.

    Each text is first capped at MAX_EMBED_TEXT_CHARS to respect per-input limits.
    Batches are then accumulated until the estimated token count would exceed
    EMBED_TOKEN_BUDGET or the item cap EMBED_BATCH_SIZE_MAX, whichever is hit first.

    Token count is estimated as len(text) // 4 (4 chars ≈ 1 token).
    This avoids importing a tokeniser while being conservative enough in practice.
    """
    batches: list[list] = []
    current: list = []
    current_tokens = 0

    for node in nodes:
        text = node.embedding_text[:MAX_EMBED_TEXT_CHARS]
        est = max(1, len(text) // 4)

        flush = (
            current
            and (
                current_tokens + est > EMBED_TOKEN_BUDGET
                or len(current) >= EMBED_BATCH_SIZE_MAX
            )
        )
        if flush:
            batches.append(current)
            current = []
            current_tokens = 0

        current.append(node)
        current_tokens += est

    if current:
        batches.append(current)

    return batches


def _vec_conn(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection with sqlite-vec extension loaded."""
    conn = sqlite3.connect(db_path)
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return conn
    except AttributeError:
        conn.close()
        raise RuntimeError(
            "sqlite3.enable_load_extension is not available in this Python build.\n"
            "Reinstall Python with loadable-extension support:\n"
            "  PYTHON_CONFIGURE_OPTS='--enable-loadable-sqlite-extensions' "
            "pyenv install 3.11.13 --force"
        ) from None
    except Exception:
        conn.close()
        raise


def init_vec_table(db_path: str) -> None:
    """Create code_embeddings_meta and code_embeddings_vec tables idempotently.

    The vec0 virtual table stores only vectors. The companion metadata table
    stores node_id, repo_path, name, file_path, line_start, line_end, and
    a reference (vec_rowid) to the corresponding row in the vec0 table.

    sqlite_vec.load() is called before any vec0 DDL.
    """
    dims = get_embedding_client().dimensions

    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    conn = _vec_conn(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS code_embeddings_meta (
                node_id    TEXT PRIMARY KEY,
                repo_path  TEXT NOT NULL,
                name       TEXT NOT NULL,
                file_path  TEXT NOT NULL,
                line_start INTEGER,
                line_end   INTEGER,
                vec_rowid  INTEGER
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_embed_repo
            ON code_embeddings_meta(repo_path)
        """)
        conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS code_embeddings_vec
            USING vec0(embedding float[{dims}])
        """)
        conn.commit()
    finally:
        conn.close()


def _init_fts_table(db_path: str) -> None:
    """Create the code_fts FTS5 virtual table idempotently.

    Indexed columns: name, embedding_text (signature + docstring + body_preview).
    node_id and file_path are UNINDEXED — stored for lookup but not searched.

    Migration: if the table exists with the old schema (name-only, no embedding_text),
    it is dropped and recreated. FTS data is derived — embed_and_store repopulates
    it on the next ingestion run.
    """
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='code_fts'"
        ).fetchone()
        if row is not None and "embedding_text" not in row[0]:
            # Old schema (name-only) — drop so CREATE below rebuilds with embedding_text
            conn.execute("DROP TABLE code_fts")
            conn.commit()

        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS code_fts
            USING fts5(node_id UNINDEXED, name, file_path UNINDEXED, embedding_text)
        """)
        conn.commit()
    finally:
        conn.close()


def embed_and_store(nodes: list[CodeNode], repo_path: str, db_path: str) -> int:
    """Embed a list of CodeNodes and persist them to sqlite-vec and FTS5.

    The embedding client is initialised lazily inside this function body so that
    importing this module does not raise a ValidationError when API keys
    are absent (e.g. during test collection).

    Batches are built dynamically by _build_batches() to stay within the
    per-request token budget (EMBED_TOKEN_BUDGET) rather than using a fixed
    item count. This prevents large-repo failures where many long functions
    would overflow the embedding API's token limit.

    Each text is additionally capped at MAX_EMBED_TEXT_CHARS before being sent
    to the API (the full embedding_text is still written to FTS5 for LLM context).

    Each batch is upserted atomically to both stores:
      - sqlite-vec: delete old rows + insert new (vec0 has no ON CONFLICT support)
      - FTS5:       DELETE + INSERT (FTS5 has no ON CONFLICT support)

    Args:
        nodes:     List of parsed CodeNode objects whose embedding_text fields
                   will be sent to the embedding API.
        repo_path: Repository root path stored alongside each row for
                   provenance filtering.
        db_path:   Path to the SQLite database file.

    Returns:
        Total number of nodes stored (== len(nodes) if all batches succeed).
    """
    embedder = get_embedding_client()

    init_vec_table(db_path)
    _init_fts_table(db_path)

    # Deduplicate across the full node list before batching.
    seen: dict[str, CodeNode] = {}
    for n in nodes:
        seen[n.node_id] = n
    deduped = list(seen.values())

    batches = _build_batches(deduped)
    logger.debug(
        "embed_and_store: %d nodes → %d batches (token-aware)",
        len(deduped), len(batches),
    )

    total_stored = 0

    for batch_idx, batch in enumerate(batches):
        # Cap each text at MAX_EMBED_TEXT_CHARS for the API call only.
        texts = [n.embedding_text[:MAX_EMBED_TEXT_CHARS] for n in batch]

        try:
            embeddings = embedder.embed(texts)
        except Exception as exc:
            exc_str = str(exc)
            # Re-raise rate-limit / capacity errors so run_ingestion surfaces them
            # as IndexStatus(status="failed") rather than silently skipping batches.
            if "429" in exc_str or "rate" in exc_str.lower() or "capacity" in exc_str.lower():
                raise
            logger.warning(
                "embed_and_store: batch %d/%d (%d nodes) embed failed (%s) — skipping",
                batch_idx + 1, len(batches), len(batch), exc,
            )
            continue

        # --- Upsert to sqlite-vec ---
        # vec_conn is opened INSIDE the try so any sqlite-vec failure is caught
        # rather than propagating uncaught to run_ingestion.
        try:
            vec_conn = _vec_conn(db_path)
            try:
                for n, emb in zip(batch, embeddings):
                    existing = vec_conn.execute(
                        "SELECT vec_rowid FROM code_embeddings_meta WHERE node_id = ?",
                        (n.node_id,),
                    ).fetchone()
                    if existing is not None:
                        old_vec_rowid = existing[0]
                        if old_vec_rowid is not None:
                            vec_conn.execute(
                                "DELETE FROM code_embeddings_vec WHERE rowid = ?",
                                (old_vec_rowid,),
                            )
                        vec_conn.execute(
                            "DELETE FROM code_embeddings_meta WHERE node_id = ?",
                            (n.node_id,),
                        )

                    embedding_bytes = sqlite_vec.serialize_float32(emb)
                    vec_conn.execute(
                        "INSERT INTO code_embeddings_vec(embedding) VALUES (?)",
                        (embedding_bytes,),
                    )
                    new_vec_rowid = vec_conn.execute("SELECT last_insert_rowid()").fetchone()[0]

                    vec_conn.execute(
                        """
                        INSERT INTO code_embeddings_meta
                            (node_id, repo_path, name, file_path, line_start, line_end, vec_rowid)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (n.node_id, repo_path, n.name, n.file_path, n.line_start, n.line_end, new_vec_rowid),
                    )
                vec_conn.commit()
            finally:
                vec_conn.close()
        except Exception as exc:
            logger.warning(
                "embed_and_store: batch %d/%d sqlite-vec upsert failed (%s) — skipping",
                batch_idx + 1, len(batches), exc,
            )
            continue

        # --- Upsert to FTS5 (DELETE + INSERT, no ON CONFLICT in FTS5) ---
        # FTS5 stores the full embedding_text (not truncated) for LLM context.
        sqlite_conn = sqlite3.connect(db_path)
        try:
            sqlite_conn.executemany(
                "DELETE FROM code_fts WHERE node_id = ?",
                [(n.node_id,) for n in batch],
            )
            sqlite_conn.executemany(
                "INSERT INTO code_fts(node_id, name, file_path, embedding_text) VALUES (?, ?, ?, ?)",
                [(n.node_id, n.name, n.file_path, n.embedding_text) for n in batch],
            )
            sqlite_conn.commit()
        except Exception as exc:
            logger.warning(
                "embed_and_store: batch %d/%d FTS5 upsert failed (%s) — vec stored, FTS skipped",
                batch_idx + 1, len(batches), exc,
            )
        finally:
            sqlite_conn.close()

        total_stored += len(batch)

    return total_stored


def delete_embeddings_for_repo(repo_path: str, db_path: str) -> None:
    """Delete all sqlite-vec and FTS5 rows for the given repo_path.

    Steps:
    1. Open a sqlite-vec connection, collect all vec_rowids for the repo.
    2. DELETE those rowids from code_embeddings_vec.
    3. DELETE matching rows from code_embeddings_meta.
    4. DELETE matching rows from code_fts (FTS5 keyed by node_id).

    Args:
        repo_path: Repository root path used to scope the delete.
        db_path:   Path to the SQLite database file.
    """
    conn = _vec_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT node_id, vec_rowid FROM code_embeddings_meta WHERE repo_path = ?",
            (repo_path,),
        ).fetchall()

        node_ids = [r[0] for r in rows]
        vec_rowids = [r[1] for r in rows if r[1] is not None]

        # Delete vec rows
        for rowid in vec_rowids:
            conn.execute("DELETE FROM code_embeddings_vec WHERE rowid = ?", (rowid,))

        # Delete meta rows
        conn.execute(
            "DELETE FROM code_embeddings_meta WHERE repo_path = ?",
            (repo_path,),
        )

        # Delete FTS5 rows
        if node_ids:
            placeholders = ",".join("?" * len(node_ids))
            conn.execute(
                f"DELETE FROM code_fts WHERE node_id IN ({placeholders})",
                node_ids,
            )

        conn.commit()
    finally:
        conn.close()


def delete_embeddings_for_files(file_paths: list[str], repo_path: str, db_path: str) -> None:
    """Delete sqlite-vec and FTS5 rows for a specific set of files in a repo.

    Used by the incremental re-index path to clean stale embeddings before
    re-parsing changed files. Deletes by file_path (not node_id) so renamed
    or removed functions that no longer appear in the AST are fully purged.

    Guards against an empty list: returns immediately without opening any DB
    connection when file_paths is empty.

    Args:
        file_paths: Absolute or repo-relative file paths whose rows should be
                    deleted from both stores.
        repo_path:  Repository root path used to scope the delete.
        db_path:    Path to the SQLite database file.
    """
    if not file_paths:
        return

    conn = _vec_conn(db_path)
    try:
        placeholders = ", ".join(["?"] * len(file_paths))
        params = [repo_path, *file_paths]

        rows = conn.execute(
            f"SELECT node_id, vec_rowid FROM code_embeddings_meta "
            f"WHERE repo_path = ? AND file_path IN ({placeholders})",
            params,
        ).fetchall()

        node_ids = [r[0] for r in rows]
        vec_rowids = [r[1] for r in rows if r[1] is not None]

        # Delete vec rows
        for rowid in vec_rowids:
            conn.execute("DELETE FROM code_embeddings_vec WHERE rowid = ?", (rowid,))

        # Delete meta rows
        conn.execute(
            f"DELETE FROM code_embeddings_meta WHERE repo_path = ? AND file_path IN ({placeholders})",
            params,
        )

        # Delete from FTS5 code_fts
        # file_path is declared UNINDEXED — must use plain WHERE, not MATCH syntax.
        file_placeholders = ", ".join(["?"] * len(file_paths))
        conn.execute(
            f"DELETE FROM code_fts WHERE file_path IN ({file_placeholders})",
            file_paths,
        )

        conn.commit()
    finally:
        conn.close()
