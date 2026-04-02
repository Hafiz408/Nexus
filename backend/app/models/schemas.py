from typing import Optional

from pydantic import BaseModel, field_validator


class CodeNode(BaseModel):
    node_id: str          # "relative_file_path::name" format (PARSE-04)
    name: str             # function/class/method name
    type: str             # "function", "method", "class"
    file_path: str        # absolute path to source file
    line_start: int       # 1-indexed start line
    line_end: int         # 1-indexed end line
    signature: str        # declaration line(s) before body
    docstring: str | None = None   # extracted docstring (PARSE-05)
    body_preview: str = ""         # first 300 chars of body (PARSE-05)
    complexity: int = 1            # keyword count proxy, min 1 (PARSE-05)
    embedding_text: str = ""       # "{signature}\n{docstring}\n{body_preview}" (PARSE-06)


class CodeEdge(BaseModel):
    source_id: str        # node_id of the source node
    target_name: str      # unresolved name (module or function name)
    edge_type: str        # "IMPORTS" or "CALLS"


class IndexStatus(BaseModel):
    status: str  # "running" | "complete" | "failed"
    nodes_indexed: int = 0
    edges_indexed: int = 0
    files_processed: int = 0
    error: str | None = None


class IndexRequest(BaseModel):
    repo_path: str
    languages: list[str] = ["python", "typescript"]
    changed_files: list[str] | None = None
    db_path: str  # path to .nexus/graph.db in user's workspace

    @field_validator("db_path")
    @classmethod
    def db_path_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("db_path must be a non-empty path to .nexus/graph.db")
        return v


class QueryRequest(BaseModel):
    question: str
    repo_path: str
    max_nodes: int = 15
    hop_depth: int = 1
    intent_hint: Optional[str] = None
    target_node_id: Optional[str] = None
    selected_file: Optional[str] = None
    selected_range: Optional[list[int]] = None
    repo_root: Optional[str] = None
    db_path: str  # path to .nexus/graph.db in user's workspace

    @field_validator("db_path")
    @classmethod
    def db_path_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("db_path must be a non-empty path to .nexus/graph.db")
        return v
