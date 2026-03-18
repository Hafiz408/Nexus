import psycopg2
from pgvector.psycopg2 import register_vector

from app.config import get_settings


def get_db_connection():
    """Create a raw psycopg2 connection and register the pgvector type adapter."""
    settings = get_settings()
    conn = psycopg2.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )
    conn.autocommit = True
    return conn


def init_db():
    """
    Initialize the database: activate pgvector extension and register vector type.

    The pgvector/pgvector:pg16 Docker image ships the extension binary, but
    CREATE EXTENSION must be called per-database. IF NOT EXISTS makes this
    idempotent on every startup.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(conn)
    finally:
        conn.close()
