"""AST Parser — transforms source files into CodeNode objects using tree-sitter.

Architecture:
  parse_file() dispatches to _parse_python() or _parse_typescript() based on language.
  Language objects are module-level singletons (expensive to create).
  Returns (list[CodeNode], list[raw_edge_tuples]) where raw edges are unresolved
  (source_id, target_name, edge_type) — Graph Builder (Phase 4) resolves them.

tree-sitter API notes (v0.25.x):
  - Parser(Language(...)) constructor — NOT parser.set_language()
  - QueryCursor(Query).captures(node) returns dict[str, list[Node]] — use QueryCursor, NOT query.captures()
  - Language(tspython.language()) — NOT Language('/path/lib.so', 'python')
  - tstypescript uses language_typescript() and language_tsx() — NOT .language()
  - Query() constructor (NOT lang.query()) to avoid deprecation warnings
"""
from __future__ import annotations

from pathlib import Path

import tree_sitter_python as tspython
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Parser, Query, QueryCursor

from app.models.schemas import CodeNode

# ── Module-level language singletons (create once, reuse forever) ──────────
# Language objects are read-only and safe to share across threads.
# Parser objects have internal mutable state — constructed fresh per parse_file() call.
PY_LANGUAGE = Language(tspython.language())
TS_LANGUAGE = Language(tstypescript.language_typescript())
TSX_LANGUAGE = Language(tstypescript.language_tsx())

# ── Query constants ─────────────────────────────────────────────────────────
PY_DEFS_QUERY = Query(PY_LANGUAGE, """
  (function_definition
    name: (identifier) @func.name) @func.def

  (class_definition
    name: (identifier) @class.name) @class.def
""")

PY_CALLS_QUERY = Query(PY_LANGUAGE, """
  (call
    function: (identifier) @call.target)

  (call
    function: (attribute
      attribute: (identifier) @call.method))
""")

PY_IMPORTS_QUERY = Query(PY_LANGUAGE, """
  (import_statement
    name: (dotted_name) @import.name)

  (import_from_statement
    module_name: (dotted_name) @import.from)
""")

TS_DEFS_QUERY = Query(TS_LANGUAGE, """
  (function_declaration
    name: (identifier) @func.name) @func.def

  (class_declaration
    name: (type_identifier) @class.name) @class.def

  (method_definition
    name: (property_identifier) @method.name) @method.def

  (lexical_declaration
    (variable_declarator
      name: (identifier) @arrow.name
      value: (arrow_function) @arrow.def))
""")

COMPLEXITY_KEYWORDS = frozenset(["if", "for", "while", "try", "elif", "and", "or"])


# ── Public API ───────────────────────────────────────────────────────────────
def parse_file(
    file_path: str, repo_root: str, language: str
) -> tuple[list[CodeNode], list[tuple]]:
    """Parse a source file and return (CodeNodes, raw_edges).

    raw_edges: list of (source_node_id, target_name, edge_type) tuples.
    edge_type is "IMPORTS" or "CALLS". target_name is unresolved.

    Parser instances are constructed fresh on each call so that concurrent
    invocations via asyncio.to_thread do not share mutable Parser state.
    """
    # Per-call Parser construction — thread-safe (each call gets its own instances)
    py_parser = Parser(PY_LANGUAGE)
    ts_parser = Parser(TS_LANGUAGE)
    tsx_parser = Parser(TSX_LANGUAGE)

    if language == "python":
        source_bytes = Path(file_path).read_bytes()
        rel_path = str(Path(file_path).relative_to(repo_root)).replace("\\", "/")
        return _parse_python(source_bytes, rel_path, file_path, py_parser)
    elif language == "typescript":
        source_bytes = Path(file_path).read_bytes()
        rel_path = str(Path(file_path).relative_to(repo_root)).replace("\\", "/")
        # Select dialect by extension
        if file_path.endswith(".tsx"):
            return _parse_typescript(source_bytes, rel_path, file_path, tsx_parser, tsx=True)
        return _parse_typescript(source_bytes, rel_path, file_path, ts_parser, tsx=False)
    return [], []


# ── Internal: Python ─────────────────────────────────────────────────────────
def _parse_python(
    source_bytes: bytes, rel_path: str, abs_path: str, parser: Parser
) -> tuple[list[CodeNode], list[tuple]]:
    tree = parser.parse(source_bytes)
    root = tree.root_node

    captures = QueryCursor(PY_DEFS_QUERY).captures(root)
    func_nodes = captures.get("func.def", [])
    class_nodes = captures.get("class.def", [])

    nodes: list[CodeNode] = []
    raw_edges: list[tuple] = []

    # Process class nodes first to build class name → line range map for method detection
    class_ranges: list[tuple[int, int]] = []
    for cnode in class_nodes:
        name_nodes = captures.get("class.name", [])
        cname = _first_name_for(name_nodes, cnode, source_bytes)
        if not cname:
            continue
        node_id = f"{rel_path}::{cname}"
        sig = _extract_signature(cnode, source_bytes)
        docstring = _extract_docstring(cnode, source_bytes)
        body_text = _body_text(cnode, source_bytes)
        preview = _body_preview(body_text)
        emb = f"{sig}\n{docstring or ''}\n{preview}"
        nodes.append(
            CodeNode(
                node_id=node_id,
                name=cname,
                type="class",
                file_path=abs_path,
                line_start=cnode.start_point[0] + 1,
                line_end=cnode.end_point[0] + 1,
                signature=sig,
                docstring=docstring,
                body_preview=preview,
                complexity=_compute_complexity(body_text),
                embedding_text=emb,
            )
        )
        class_ranges.append((cnode.start_point[0], cnode.end_point[0]))

    # Process function nodes — determine if method (inside a class range)
    for fnode in func_nodes:
        name_nodes = captures.get("func.name", [])
        fname = _first_name_for(name_nodes, fnode, source_bytes)
        if not fname:
            continue
        node_id = f"{rel_path}::{fname}"
        is_method = any(
            start <= fnode.start_point[0] and fnode.end_point[0] <= end
            for start, end in class_ranges
        )
        node_type = "method" if is_method else "function"
        sig = _extract_signature(fnode, source_bytes)
        docstring = _extract_docstring(fnode, source_bytes)
        body_text = _body_text(fnode, source_bytes)
        preview = _body_preview(body_text)
        emb = f"{sig}\n{docstring or ''}\n{preview}"
        cnode_obj = CodeNode(
            node_id=node_id,
            name=fname,
            type=node_type,
            file_path=abs_path,
            line_start=fnode.start_point[0] + 1,
            line_end=fnode.end_point[0] + 1,
            signature=sig,
            docstring=docstring,
            body_preview=preview,
            complexity=_compute_complexity(body_text),
            embedding_text=emb,
        )
        nodes.append(cnode_obj)

        # CALLS edges
        call_captures = QueryCursor(PY_CALLS_QUERY).captures(fnode)
        for target_node in call_captures.get("call.target", []) + call_captures.get("call.method", []):
            target_name = source_bytes[target_node.start_byte:target_node.end_byte].decode("utf-8")
            raw_edges.append((node_id, target_name, "CALLS"))

    # IMPORTS edges — attached to a synthetic file-level source_id
    file_source_id = f"{rel_path}::__module__"
    import_captures = QueryCursor(PY_IMPORTS_QUERY).captures(root)
    for imp_node in import_captures.get("import.name", []) + import_captures.get("import.from", []):
        target_name = source_bytes[imp_node.start_byte:imp_node.end_byte].decode("utf-8")
        raw_edges.append((file_source_id, target_name, "IMPORTS"))

    return nodes, raw_edges


# ── Internal: TypeScript ─────────────────────────────────────────────────────
def _parse_typescript(
    source_bytes: bytes, rel_path: str, abs_path: str, parser: Parser, *, tsx: bool = False
) -> tuple[list[CodeNode], list[tuple]]:
    language = TSX_LANGUAGE if tsx else TS_LANGUAGE
    tree = parser.parse(source_bytes)
    root = tree.root_node

    # Re-compile query against the correct language dialect
    ts_query = Query(language, """
      (function_declaration
        name: (identifier) @func.name) @func.def

      (class_declaration
        name: (type_identifier) @class.name) @class.def

      (method_definition
        name: (property_identifier) @method.name) @method.def

      (lexical_declaration
        (variable_declarator
          name: (identifier) @arrow.name
          value: (arrow_function) @arrow.def))
    """)

    captures = QueryCursor(ts_query).captures(root)
    nodes: list[CodeNode] = []
    raw_edges: list[tuple] = []

    # Classes
    for cnode in captures.get("class.def", []):
        name_nodes = captures.get("class.name", [])
        cname = _first_name_for(name_nodes, cnode, source_bytes)
        if not cname:
            continue
        node_id = f"{rel_path}::{cname}"
        sig = _ts_signature(cnode, source_bytes)
        body_text = source_bytes[cnode.start_byte:cnode.end_byte].decode("utf-8", errors="replace")
        preview = _body_preview(body_text)
        nodes.append(CodeNode(
            node_id=node_id, name=cname, type="class", file_path=abs_path,
            line_start=cnode.start_point[0] + 1, line_end=cnode.end_point[0] + 1,
            signature=sig, docstring=None, body_preview=preview,
            complexity=_compute_complexity(body_text),
            embedding_text=f"{sig}\n\n{preview}",
        ))

    # Functions
    for fnode in captures.get("func.def", []):
        fname_nodes = captures.get("func.name", [])
        fname = _first_name_for(fname_nodes, fnode, source_bytes)
        if not fname:
            continue
        node_id = f"{rel_path}::{fname}"
        sig = _ts_signature(fnode, source_bytes)
        body_text = source_bytes[fnode.start_byte:fnode.end_byte].decode("utf-8", errors="replace")
        preview = _body_preview(body_text)
        nodes.append(CodeNode(
            node_id=node_id, name=fname, type="function", file_path=abs_path,
            line_start=fnode.start_point[0] + 1, line_end=fnode.end_point[0] + 1,
            signature=sig, docstring=None, body_preview=preview,
            complexity=_compute_complexity(body_text),
            embedding_text=f"{sig}\n\n{preview}",
        ))

    # Methods
    for mnode in captures.get("method.def", []):
        mname_nodes = captures.get("method.name", [])
        mname = _first_name_for(mname_nodes, mnode, source_bytes)
        if not mname:
            continue
        node_id = f"{rel_path}::{mname}"
        sig = _ts_signature(mnode, source_bytes)
        body_text = source_bytes[mnode.start_byte:mnode.end_byte].decode("utf-8", errors="replace")
        preview = _body_preview(body_text)
        nodes.append(CodeNode(
            node_id=node_id, name=mname, type="method", file_path=abs_path,
            line_start=mnode.start_point[0] + 1, line_end=mnode.end_point[0] + 1,
            signature=sig, docstring=None, body_preview=preview,
            complexity=_compute_complexity(body_text),
            embedding_text=f"{sig}\n\n{preview}",
        ))

    # Arrow functions (the arrow.def capture is the arrow_function node itself;
    # arrow.name is the variable declarator name — both come from the same lexical_declaration match)
    arrow_defs = captures.get("arrow.def", [])
    arrow_names = captures.get("arrow.name", [])
    for anode, aname_node in zip(arrow_defs, arrow_names):
        aname = source_bytes[aname_node.start_byte:aname_node.end_byte].decode("utf-8")
        if not aname:
            continue
        node_id = f"{rel_path}::{aname}"
        sig = source_bytes[anode.start_byte:anode.end_byte].decode("utf-8", errors="replace").split("\n")[0][:120]
        body_text = source_bytes[anode.start_byte:anode.end_byte].decode("utf-8", errors="replace")
        preview = _body_preview(body_text)
        nodes.append(CodeNode(
            node_id=node_id, name=aname, type="function", file_path=abs_path,
            line_start=anode.start_point[0] + 1, line_end=anode.end_point[0] + 1,
            signature=sig, docstring=None, body_preview=preview,
            complexity=_compute_complexity(body_text),
            embedding_text=f"{sig}\n\n{preview}",
        ))

    return nodes, raw_edges


# ── Helpers ──────────────────────────────────────────────────────────────────
def _first_name_for(name_nodes: list, def_node, source_bytes: bytes) -> str | None:
    """Find the name node that falls within def_node's byte range."""
    for n in name_nodes:
        if def_node.start_byte <= n.start_byte < def_node.end_byte:
            return source_bytes[n.start_byte:n.end_byte].decode("utf-8")
    return None


def _extract_signature(node, source_bytes: bytes) -> str:
    """Extract function/class signature (everything before the body)."""
    body = node.child_by_field_name("body")
    if body:
        sig_bytes = source_bytes[node.start_byte:body.start_byte]
        return sig_bytes.decode("utf-8").rstrip().rstrip(":")
    full_text = source_bytes[node.start_byte:node.end_byte].decode("utf-8")
    return full_text.split("\n")[0].rstrip(":")


def _ts_signature(node, source_bytes: bytes) -> str:
    """Extract TypeScript signature — first line of the node."""
    full_text = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
    return full_text.split("\n")[0][:120]


def _extract_docstring(node, source_bytes: bytes) -> str | None:
    """Extract Python docstring from function_definition or class_definition."""
    body = node.child_by_field_name("body")
    if body is None:
        return None
    for child in body.children:
        if child.type == "expression_statement" and len(child.children) == 1:
            string_node = child.children[0]
            if string_node.type == "string":
                # Prefer string_content child (no delimiters)
                content_node = string_node.child_by_field_name("string_content")
                if content_node:
                    return source_bytes[content_node.start_byte:content_node.end_byte].decode("utf-8").strip()
                raw = source_bytes[string_node.start_byte:string_node.end_byte].decode("utf-8")
                return raw.strip('"""').strip("'''").strip('"').strip("'").strip()
        break  # Docstring MUST be the first statement
    return None


def _body_text(node, source_bytes: bytes) -> str:
    """Extract body text from a function or class node."""
    body = node.child_by_field_name("body")
    if body:
        return source_bytes[body.start_byte:body.end_byte].decode("utf-8", errors="replace")
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _body_preview(body_text: str, head: int = 1000, tail: int = 3000) -> str:
    """Return a preview of a function body for indexing and LLM context.

    For short bodies (<= head+tail chars), returns the full text.
    For long bodies (e.g. factory functions with large instruction strings),
    returns the first `head` chars + '\\n[...]\\n' + last `tail` chars.
    This ensures both the early setup code AND the key return/construction
    statement at the end (e.g. Team(members=[...])) are captured.
    """
    total = head + tail
    if len(body_text) <= total:
        return body_text
    return body_text[:head] + "\n[...]\n" + body_text[-tail:]


def _compute_complexity(body_text: str) -> int:
    """Keyword count proxy for cyclomatic complexity. Baseline = 1."""
    tokens = body_text.split()
    return 1 + sum(1 for t in tokens if t in COMPLEXITY_KEYWORDS)
