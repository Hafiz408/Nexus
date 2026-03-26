import asyncio
import logging
from asyncio import Semaphore

from app.ingestion.walker import walk_repo, EXTENSION_TO_LANGUAGE
from app.ingestion.ast_parser import parse_file
from app.ingestion.graph_builder import build_graph
from app.ingestion.embedder import embed_and_store, delete_embeddings_for_files
from app.ingestion.graph_store import save_graph, delete_nodes_for_files
from app.ingestion.meta_store import set_embedding_meta
from app.core.runtime_config import get_runtime_config
from app.core.model_factory import get_embedding_client
from app.models.schemas import IndexStatus

logger = logging.getLogger(__name__)
PARSE_CONCURRENCY = 10
_status: dict[str, IndexStatus] = {}


def get_status(repo_path: str) -> IndexStatus | None:
    return _status.get(repo_path)


def restore_status_from_db() -> None:
    """No-op: status is restored when the extension sends a status request with db_path."""
    pass


def clear_status(repo_path: str) -> None:
    _status.pop(repo_path, None)


async def _parse_concurrent(files: list[dict], repo_path: str) -> tuple[list, list]:
    sem = Semaphore(PARSE_CONCURRENCY)
    all_nodes: list = []
    all_edges: list = []

    async def _one(entry: dict):
        async with sem:
            return await asyncio.to_thread(parse_file, entry["path"], repo_path, entry["language"])

    results = await asyncio.gather(*[_one(e) for e in files], return_exceptions=True)

    for r in results:
        if isinstance(r, Exception):
            logger.warning("parse_file failed: %s", r)
            continue
        else:
            nodes, edges = r
            all_nodes.extend(nodes)
            all_edges.extend(edges)

    return (all_nodes, all_edges)


async def run_ingestion(
    repo_path: str,
    languages: list[str],
    db_path: str,
    changed_files: list[str] | None = None,
) -> IndexStatus:
    _status[repo_path] = IndexStatus(status="running")

    try:
        logger.info("run_ingestion started: repo=%s languages=%s incremental=%s",
                    repo_path, languages, changed_files is not None)

        if changed_files is not None:
            logger.info("incremental re-index: %d changed files", len(changed_files))
            delete_nodes_for_files(changed_files, repo_path, db_path)
            delete_embeddings_for_files(changed_files, repo_path, db_path)
            ext_map: dict[str, str] = {ext.lstrip("."): lang for ext, lang in EXTENSION_TO_LANGUAGE.items()}
            files_to_parse: list[dict] = []
            for f in changed_files:
                if "." in f:
                    suffix = f.rsplit(".", 1)[-1].lower()
                    if suffix in ext_map and ext_map[suffix] in languages:
                        files_to_parse.append({"path": f, "language": ext_map[suffix], "size_kb": 0})
        else:
            files_to_parse = walk_repo(repo_path, languages)

        logger.info("files to parse: %d", len(files_to_parse))
        if not files_to_parse:
            logger.warning(
                "no source files found in %s for languages %s — "
                "check that the path exists and contains .py/.ts/.tsx/.js/.jsx files",
                repo_path, languages,
            )

        _status[repo_path] = IndexStatus(status="running", files_processed=len(files_to_parse))

        all_nodes, all_edges = await _parse_concurrent(files_to_parse, repo_path)
        logger.info("parsed %d nodes, %d raw edges from %d files",
                    len(all_nodes), len(all_edges), len(files_to_parse))

        # Drop nodes with empty/None node_id — faulty parsers can produce these
        # and they would fail the SQL NOT NULL / PRIMARY KEY constraint.
        valid_nodes = [n for n in all_nodes if n.node_id]
        if len(valid_nodes) < len(all_nodes):
            logger.warning(
                "dropped %d nodes with empty node_id",
                len(all_nodes) - len(valid_nodes),
            )
        all_nodes = valid_nodes

        # Deduplicate nodes by node_id — the AST parser can emit the same
        # node_id from multiple files (re-exports, __init__.py re-imports,
        # or same function name appearing in nested scopes of a single file).
        # ON CONFLICT DO UPDATE fails when a single batch contains duplicate ids.
        seen: dict[str, object] = {}
        for node in all_nodes:
            seen[node.node_id] = node
        if len(seen) < len(all_nodes):
            logger.warning(
                "deduped %d duplicate node_ids (kept last seen); "
                "original count %d → %d",
                len(all_nodes) - len(seen), len(all_nodes), len(seen),
            )
        all_nodes = list(seen.values())

        G = build_graph(all_nodes, all_edges)
        logger.info("graph built: %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges())

        await asyncio.to_thread(save_graph, G, repo_path, db_path)
        nodes_stored = await asyncio.to_thread(embed_and_store, all_nodes, repo_path, db_path)
        logger.info("embedded and stored %d nodes", nodes_stored)

        # Persist embedding config so mismatch can be detected on next config change
        cfg = get_runtime_config()
        embedder = get_embedding_client()
        set_embedding_meta(db_path, cfg.embedding_provider, cfg.embedding_model, embedder.dimensions)

        if nodes_stored == 0:
            logger.warning(
                "indexing complete but 0 nodes stored for %s — "
                "no functions/classes were extracted. "
                "Verify the repo contains Python or TypeScript source files.",
                repo_path,
            )

        result = IndexStatus(
            status="complete",
            nodes_indexed=nodes_stored,
            edges_indexed=G.number_of_edges(),
            files_processed=len(files_to_parse),
        )
        logger.info("run_ingestion complete: %d nodes, %d edges, %d files",
                    nodes_stored, G.number_of_edges(), len(files_to_parse))
    except Exception as exc:
        logger.exception("run_ingestion failed for %s", repo_path)
        result = IndexStatus(status="failed", error=str(exc))

    # Only persist result if DELETE hasn't cleared this repo's status concurrently
    if repo_path in _status:
        _status[repo_path] = result
    return result
