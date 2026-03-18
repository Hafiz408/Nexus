import asyncio
import logging
from asyncio import Semaphore

from app.ingestion.walker import walk_repo, EXTENSION_TO_LANGUAGE
from app.ingestion.ast_parser import parse_file
from app.ingestion.graph_builder import build_graph
from app.ingestion.embedder import embed_and_store
from app.ingestion.graph_store import save_graph, delete_nodes_for_files
from app.models.schemas import IndexStatus

logger = logging.getLogger(__name__)
PARSE_CONCURRENCY = 10
_status: dict[str, IndexStatus] = {}


def get_status(repo_path: str) -> IndexStatus | None:
    return _status.get(repo_path)


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
    changed_files: list[str] | None = None,
) -> IndexStatus:
    _status[repo_path] = IndexStatus(status="running")

    try:
        if changed_files is not None:
            delete_nodes_for_files(changed_files, repo_path)
            ext_map: dict[str, str] = {ext.lstrip("."): lang for ext, lang in EXTENSION_TO_LANGUAGE.items()}
            files_to_parse: list[dict] = []
            for f in changed_files:
                if "." in f:
                    suffix = f.rsplit(".", 1)[-1].lower()
                    if suffix in ext_map and ext_map[suffix] in languages:
                        files_to_parse.append({"path": f, "language": ext_map[suffix], "size_kb": 0})
        else:
            files_to_parse = walk_repo(repo_path, languages)

        _status[repo_path] = IndexStatus(status="running", files_processed=len(files_to_parse))

        all_nodes, all_edges = await _parse_concurrent(files_to_parse, repo_path)

        G = build_graph(all_nodes, all_edges)

        await asyncio.to_thread(save_graph, G, repo_path)
        nodes_stored = await asyncio.to_thread(embed_and_store, all_nodes, repo_path)

        result = IndexStatus(
            status="complete",
            nodes_indexed=nodes_stored,
            edges_indexed=G.number_of_edges(),
            files_processed=len(files_to_parse),
        )
    except Exception as exc:
        logger.exception("run_ingestion failed for %s", repo_path)
        result = IndexStatus(status="failed", error=str(exc))

    _status[repo_path] = result
    return result
