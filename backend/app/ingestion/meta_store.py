"""nexus_meta table — persists active embedding config for mismatch detection."""
import sqlite3
import os


def _get_conn(db_path: str) -> sqlite3.Connection:
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nexus_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def get_meta(db_path: str, key: str) -> str | None:
    if not os.path.exists(db_path):
        return None
    conn = _get_conn(db_path)
    row = conn.execute("SELECT value FROM nexus_meta WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row[0] if row else None


def set_meta(db_path: str, key: str, value: str) -> None:
    conn = _get_conn(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO nexus_meta(key, value) VALUES (?, ?)",
        (key, value)
    )
    conn.commit()
    conn.close()


def get_embedding_meta(db_path: str) -> dict | None:
    """Return stored embedding provider, model, dimensions. None if no index exists."""
    provider = get_meta(db_path, "embedding_provider")
    model = get_meta(db_path, "embedding_model")
    dims = get_meta(db_path, "embedding_dimensions")
    if provider is None:
        return None
    return {"provider": provider, "model": model, "dimensions": dims}


def set_embedding_meta(db_path: str, provider: str, model: str, dimensions: int) -> None:
    """Write embedding config after a successful index."""
    set_meta(db_path, "embedding_provider", provider)
    set_meta(db_path, "embedding_model", model)
    set_meta(db_path, "embedding_dimensions", str(dimensions))
