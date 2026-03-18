from pydantic import BaseModel


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
