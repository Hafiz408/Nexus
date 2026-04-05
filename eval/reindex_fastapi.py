"""Re-index the FastAPI corpus from scratch.

Wipes the existing graph.db and rebuilds it with the current ingestion
pipeline — picks up CLASS_CONTAINS edges added in v3.1.

Usage:
    cd /Users/mohammedhafiz/Desktop/Personal/nexus
    source venv_eval/bin/activate
    python eval/reindex_fastapi.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

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

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from app.ingestion.pipeline import run_ingestion

REPO_PATH = "/Users/mohammedhafiz/Desktop/Personal/fastapi"
DB_PATH   = REPO_PATH + "/.nexus/graph.db"
LANGUAGES = ["python"]


async def main() -> None:
    print(f"Re-indexing {REPO_PATH} …")
    print("(changed_files=None → full wipe + rebuild)")
    status = await run_ingestion(
        repo_path=REPO_PATH,
        languages=LANGUAGES,
        db_path=DB_PATH,
        changed_files=None,          # full re-index
    )
    print(f"\nDone — status: {status}")

    # Quick sanity check
    import sqlite3, json
    conn = sqlite3.connect(DB_PATH)
    nodes = conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
    total_edges = conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
    cc_edges = conn.execute(
        "SELECT COUNT(*) FROM graph_edges "
        "WHERE json_extract(attrs_json, '$.type') = 'CLASS_CONTAINS'"
    ).fetchone()[0]
    conn.close()
    print(f"\nGraph stats:")
    print(f"  nodes        : {nodes:,}")
    print(f"  total edges  : {total_edges:,}")
    print(f"  CLASS_CONTAINS: {cc_edges:,}")


if __name__ == "__main__":
    asyncio.run(main())
