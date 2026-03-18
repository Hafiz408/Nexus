# Phase 3: AST Parser - Research

**Researched:** 2026-03-18
**Domain:** tree-sitter Python bindings, AST traversal, CodeNode extraction
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PARSE-01 | `parse_file(file_path, repo_root, language)` returns `(list[CodeNode], list[raw_edges])` | Function signature pattern, return type structure documented in PRD and verified against CodeNode model |
| PARSE-02 | Extracts Python `function_definition`, `class_definition`, methods inside classes | tree-sitter-python node types confirmed; query pattern for block . expression_statement verified |
| PARSE-03 | Extracts TypeScript `function_declaration`, `arrow_function`, `method_definition`, `class_declaration` | tree-sitter-typescript node types confirmed from grammar source; language_typescript() import verified |
| PARSE-04 | Node ID format: `"relative_file_path::name"` | Format pattern documented; relative path computed via os.path.relpath or Path.relative_to(repo_root) |
| PARSE-05 | Populates `signature`, `docstring`, `body_preview` (first 300 chars), `complexity` (keyword count) | child_by_field_name() API verified; docstring pattern (expression_statement > string) confirmed; complexity as keyword count straightforward |
| PARSE-06 | `embedding_text` = `"{signature}\n{docstring}\n{body_preview}"` | Simple f-string composition — no library dependency; aligns with CodeNode.embedding_text field |
| PARSE-07 | Detects `import` statements and `call_expression`s for raw IMPORTS/CALLS edges | Python: import_statement + import_from_statement; TypeScript: import_declaration + call_expression node types confirmed |
| PARSE-08 | Unit tests pass: 2 functions + 1 class in sample file → correct node count + docstrings | Test file path `tests/test_ast_parser.py`; conftest.py needs updated sample_repo_path fixture with Python sample |
| TEST-03 | `tests/test_ast_parser.py` — Python + TypeScript parsing, docstring extraction, CALLS edge detection | Same as PARSE-08; test must cover both languages and edge types |
</phase_requirements>

---

## Summary

Phase 3 builds `backend/app/ingestion/ast_parser.py`, which is the core transformation step: read a source file, parse it with tree-sitter, and produce `(list[CodeNode], list[raw_edges])`. The PRD specifies the exact library stack (tree-sitter + tree-sitter-python + tree-sitter-typescript), the exact CodeNode schema (defined in `app/models/schemas.py` — not yet created), and the exact function signature.

The modern tree-sitter Python API (0.21+) broke the older Language construction pattern. The current correct API is `Parser(Language(tspython.language()))` — no `set_language()`, no path arguments. The tree-sitter-typescript package exposes `language_typescript()` and `language_tsx()` as separate functions (not a single `.language()` like the Python package). These differences are the most likely source of bugs if the wrong version of tutorials is followed.

The CodeNode Pydantic model (defined in schemas.py) must be created as part of this phase since it does not yet exist. The tests in `tests/test_ast_parser.py` also need a richer conftest fixture that includes a Python file with 2 functions + 1 class and docstrings, plus a TypeScript file with the required node types.

**Primary recommendation:** Use tree-sitter Query API (pattern matching) rather than manual recursive traversal — it is cleaner, less error-prone, and the official recommended approach. Build separate `_parse_python()` and `_parse_typescript()` internal functions dispatched from `parse_file()`.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| tree-sitter | 0.25.2 | Python bindings to tree-sitter parsing library; Language, Parser, Query, Node classes | The official Python wrapper — the only maintained option |
| tree-sitter-python | 0.25.0 | Python grammar as a precompiled capsule object | Official grammar, zero compilation required; exposes `language()` |
| tree-sitter-typescript | 0.23.2 | TypeScript and TSX grammars | Official grammar; exposes `language_typescript()` and `language_tsx()` |
| pydantic | 2.x (already in project) | CodeNode and CodeEdge data models | Already in requirements.txt via pydantic-settings |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | latest (already in project) | Unit tests for test_ast_parser.py | Standard project test runner |
| pathlib.Path | stdlib | Computing relative file paths for node IDs | `Path(file_path).relative_to(repo_root)` |
| re | stdlib | Stripping docstring quotes (`""" """`, `''' '''`) | Needed to clean raw string node text |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| tree-sitter (per grammar packages) | tree-sitter-languages | tree-sitter-languages bundles ALL grammars into one binary wheel — simpler install, but PRD explicitly specifies `tree-sitter-python` + `tree-sitter-typescript` as separate packages |
| tree-sitter | Python built-in `ast` module | Built-in ast only handles Python; no TypeScript support; tree-sitter handles both uniformly |
| tree-sitter Query API | Manual recursive cursor traversal | Manual traversal works but is more code; Query API is officially recommended and more declarative |

**Installation:**
```bash
pip install tree-sitter tree-sitter-python tree-sitter-typescript
```

---

## Architecture Patterns

### Recommended Project Structure
```
backend/app/
├── models/
│   ├── __init__.py
│   └── schemas.py          # CodeNode, CodeEdge Pydantic models (CREATE THIS PHASE)
├── ingestion/
│   ├── __init__.py
│   ├── walker.py           # already exists (Phase 2)
│   └── ast_parser.py       # CREATE THIS PHASE
backend/tests/
├── conftest.py             # UPDATE: add parser fixtures
└── test_ast_parser.py      # CREATE THIS PHASE
```

### Pattern 1: Module-Level Language Singletons

**What:** Instantiate `Language` objects once at module level, not per call.
**When to use:** Always. Language objects are expensive to create; Parser objects are cheap.
**Example:**
```python
# Source: https://github.com/tree-sitter/py-tree-sitter (README)
import tree_sitter_python as tspython
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tspython.language())
TS_LANGUAGE = Language(tstypescript.language_typescript())
TSX_LANGUAGE = Language(tstypescript.language_tsx())
```

### Pattern 2: Separate Parse Functions Dispatched by Language

**What:** `parse_file()` dispatches to `_parse_python()` or `_parse_typescript()` based on `language` argument.
**When to use:** Whenever a module handles multiple languages — avoids a single function bloated with `if language == "python"` branches scattered throughout.
**Example:**
```python
def parse_file(file_path: str, repo_root: str, language: str) -> tuple[list[CodeNode], list[tuple]]:
    source_bytes = Path(file_path).read_bytes()
    rel_path = str(Path(file_path).relative_to(repo_root))
    if language == "python":
        return _parse_python(source_bytes, rel_path)
    elif language == "typescript":
        return _parse_typescript(source_bytes, rel_path)
    return [], []
```

### Pattern 3: Query API for Node Extraction

**What:** Use tree-sitter's S-expression query pattern matching to find all relevant node types in one pass.
**When to use:** Prefer over manual cursor traversal for extracting named node types.
**Example:**
```python
# Source: https://tree-sitter.github.io/py-tree-sitter/
from tree_sitter import Query

# Python: find all function and class definitions
PY_DEFS_QUERY = PY_LANGUAGE.query("""
  (function_definition
    name: (identifier) @name) @func

  (class_definition
    name: (identifier) @name) @class
""")

captures = PY_DEFS_QUERY.captures(tree.root_node)
```

**Important API note:** In tree-sitter 0.24+, `captures()` returns a `dict[str, list[Node]]` (capture name → nodes). In older versions it returned a list of tuples. Always use the dict-based API.

### Pattern 4: Docstring Extraction from Body Node

**What:** Python docstrings appear as `expression_statement > string` as the first child of the function/class body block.
**When to use:** When populating `CodeNode.docstring`.
**Example:**
```python
# Source: https://github.com/tree-sitter/tree-sitter/discussions/2470
# and https://github.com/tree-sitter/tree-sitter-python/issues/168
def _extract_docstring(body_node, source_bytes: bytes) -> str | None:
    """Extracts docstring from a Python function or class body block node."""
    if body_node is None:
        return None
    for child in body_node.children:
        if child.type == "expression_statement" and len(child.children) == 1:
            string_node = child.children[0]
            if string_node.type == "string":
                raw = source_bytes[string_node.start_byte:string_node.end_byte].decode("utf-8")
                # Strip surrounding triple/single quotes
                return raw.strip('"""').strip("'''").strip('"').strip("'").strip()
        break  # Docstring must be the FIRST statement; stop after first non-docstring
    return None
```

**Note for TypeScript:** TypeScript/JS does not have a standard docstring convention in the AST. JSDoc (`/** ... */`) appears as `comment` nodes. For V1, TypeScript `docstring` field can be `None` or a JSDoc extraction — but PRD success criteria only tests Python docstrings explicitly. TypeScript docstring extraction is optional for V1 compliance.

### Pattern 5: Node Text Extraction via Byte Slicing

**What:** Extract text for a node using byte offsets from original source bytes.
**When to use:** For signature, body_preview — never rely on node.text when the source encoding might vary.
**Example:**
```python
# Source: https://github.com/tree-sitter/tree-sitter/issues/725
def node_text(source_bytes: bytes, node) -> str:
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
```

Note: `node.text` property DOES work in current tree-sitter (0.21+) when the parser has access to source bytes — but byte slicing is more explicit and reliable.

### Pattern 6: Complexity Keyword Count

**What:** Count occurrences of complexity-indicating keywords in the body text.
**When to use:** For `CodeNode.complexity` field — simple proxy for cyclomatic complexity.
**Example:**
```python
COMPLEXITY_KEYWORDS = {"if", "for", "while", "try", "elif", "and", "or"}

def _compute_complexity(body_text: str) -> int:
    count = 1  # baseline complexity = 1
    for keyword in COMPLEXITY_KEYWORDS:
        count += body_text.split().count(keyword)
    return count
```

**Important:** Use `.split()` (tokenize by whitespace) rather than substring search to avoid false positives (`elif` inside a string matching `elif`). PRD says "keyword count" — base of 1 is standard cyclomatic complexity convention.

### Pattern 7: Raw Edge Tuple Format

**What:** Raw edges are `(source_id, target_name, edge_type)` tuples. `target_name` is unresolved — just the imported module name or function name called.
**When to use:** For IMPORTS and CALLS edges detected during parsing; Graph Builder (Phase 4) resolves them.
**Example:**
```python
# For Python call: validate_token(user)
raw_edges.append((node_id, "validate_token", "CALLS"))

# For Python import: from auth.utils import helpers
raw_edges.append((node_id, "auth.utils", "IMPORTS"))
```

### Anti-Patterns to Avoid

- **Using `parser.set_language(lang)`:** This is the OLD API (tree-sitter < 0.21). Use `Parser(language)` constructor instead.
- **Passing a path string to `Language()`:** Old API required `Language('/path/to/lib.so', 'python')`. Current API is `Language(tspython.language())`.
- **Building the grammar with `Language.build_library()`:** Completely obsolete — pre-compiled grammar wheels handle this automatically.
- **Calling `.language()` on the tstypescript module directly:** The tstypescript module has `language_typescript()` and `language_tsx()` — NOT a single `.language()` method like the Python grammar.
- **Manual recursive cursor traversal for node type detection:** Use the Query API; manual traversal requires handling all edge cases of anonymous vs named nodes.
- **Searching body text as raw string for call targets:** Tree-sitter's `call_expression` nodes give you the exact call target. Regex scanning the body text for function names produces false positives.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Language grammar loading | Custom .so compilation pipeline | tree-sitter-python / tree-sitter-typescript pre-compiled wheels | Grammar compilation requires C toolchain, language-specific submodules, version matching |
| Pattern matching on AST nodes | Recursive visitor pattern | tree-sitter Query API | Query handles anonymous nodes, optional fields, nested patterns natively |
| Docstring stripping | Custom regex to remove `"""` | Byte-slice from string_content child node OR simple strip | tree-sitter string nodes include the delimiters in their text; strip is straightforward but `string_content` child is cleaner |
| Cyclomatic complexity | Full control flow graph analysis | Keyword count proxy as specified in PRD | Full cyclomatic complexity requires tracking all branch points per CFG; keyword count is an acceptable proxy for V1 |

**Key insight:** tree-sitter grammar packages ship pre-compiled wheels for all major platforms. Never build grammars from source in V1 — it adds C toolchain dependencies to the Docker build and is completely unnecessary.

---

## Common Pitfalls

### Pitfall 1: Wrong TypeScript Import API

**What goes wrong:** `Language(tstypescript.language())` raises `AttributeError: module 'tree_sitter_typescript' has no attribute 'language'`.
**Why it happens:** The tree-sitter-typescript module is structured differently from tree-sitter-python. It has TWO dialects (TypeScript and TSX) exposed as `language_typescript()` and `language_tsx()` — no single `.language()`.
**How to avoid:** Use `Language(tstypescript.language_typescript())` for `.ts`/`.js`/`.jsx` files and `Language(tstypescript.language_tsx())` for `.tsx` files.
**Warning signs:** AttributeError at module import time or when constructing Language objects.

### Pitfall 2: Old Parser Initialization Pattern

**What goes wrong:** Code uses `parser = Parser(); parser.set_language(lang)` — this pattern was deprecated and removed in newer tree-sitter versions.
**Why it happens:** Most tutorials and Stack Overflow answers predate the 0.21 API overhaul. The old pattern still appears widely online.
**How to avoid:** Use `parser = Parser(language)` — pass Language object directly to constructor.
**Warning signs:** `TypeError` or `AttributeError: 'Parser' object has no attribute 'set_language'`.

### Pitfall 3: captures() API Changed Between Versions

**What goes wrong:** Code iterates `for name, node in captures` expecting a list of tuples — but gets a dict in newer versions.
**Why it happens:** tree-sitter 0.21+ changed `captures()` return type from `list[tuple[Node, str]]` to `dict[str, list[Node]]`.
**How to avoid:** Use `captures = query.captures(root_node)` then access as `captures.get("capture_name", [])`.
**Warning signs:** `TypeError: cannot unpack non-sequence dict` or incorrect capture iteration.

### Pitfall 4: Missing CodeNode and CodeEdge Models

**What goes wrong:** `ast_parser.py` imports from `app.models.schemas` which doesn't yet exist — `ImportError` at test time.
**Why it happens:** Phase 3 is the first consumer of the models module, which hasn't been created yet.
**How to avoid:** Create `backend/app/models/__init__.py` and `backend/app/models/schemas.py` as the FIRST task of this phase.
**Warning signs:** ImportError when running any test that imports from `ast_parser`.

### Pitfall 5: Method Nodes Inside Classes Missing from Output

**What goes wrong:** Only top-level functions and classes are returned; class methods are missed.
**Why it happens:** A simple query for `(function_definition)` at root level won't capture nested function definitions inside class bodies.
**How to avoid:** Use a query that searches the ENTIRE tree (not just root children). The Query API on `root_node` recursively matches by default. However, you need to track whether a function is inside a class body to assign `type="method"` vs `type="function"`. Check `parent` node chain: if a `function_definition` has a `block` grandparent which is inside a `class_definition`, it's a method.
**Warning signs:** Test fixture with class + methods returns fewer nodes than expected.

### Pitfall 6: TypeScript Arrow Functions Without Explicit Names

**What goes wrong:** `arrow_function` nodes have no `name` field in the grammar — they're anonymous.
**Why it happens:** Arrow functions in TypeScript are expressions, not declarations. The name comes from the variable they're assigned to: `const myFunc = (x) => x + 1`.
**How to avoid:** For `arrow_function` nodes, look at the parent node. If parent is `variable_declarator`, get the name from the `name` field of the variable_declarator. If no name is available, generate a synthetic name like `<anonymous_arrow_{line}>`.
**Warning signs:** Arrow function nodes with empty or None names cause node ID collisions or duplicates.

### Pitfall 7: node.text Returns None or Fails

**What goes wrong:** `node.text` returns `None` for some nodes.
**Why it happens:** `node.text` requires the parser to have been given the source bytes. In current tree-sitter 0.21+, `node.text` works when bytes were passed to `parser.parse()`. But if a custom read callback was used instead, text may not be available.
**How to avoid:** Always pass `source_bytes` to `parser.parse(source_bytes)` (not a callback). Then use `source_bytes[node.start_byte:node.end_byte].decode("utf-8")` as the reliable fallback.
**Warning signs:** `NoneType` errors when accessing `.text` property.

### Pitfall 8: Docstring Contains Raw Delimiter Characters

**What goes wrong:** Extracted docstring is `'"""This is the docstring."""'` — includes triple-quote delimiters.
**Why it happens:** tree-sitter's `string` node text includes the surrounding `"""` or `'''` delimiters.
**How to avoid:** Either (a) strip delimiters with `.strip('"""').strip("'''").strip()`, or (b) get the `string_content` child node which contains only the inner text. Using the `string_content` child is more robust.
**Warning signs:** Docstrings in test assertions include leading/trailing `"""` or `'''`.

---

## Code Examples

Verified patterns from official sources:

### Language and Parser Initialization
```python
# Source: https://github.com/tree-sitter/py-tree-sitter (README, verified 2026-03)
import tree_sitter_python as tspython
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tspython.language())
TS_LANGUAGE = Language(tstypescript.language_typescript())
TSX_LANGUAGE = Language(tstypescript.language_tsx())

# Parser creation — language passed to constructor (NOT set_language)
py_parser = Parser(PY_LANGUAGE)
ts_parser = Parser(TS_LANGUAGE)
```

### Parsing a File
```python
# Source: https://github.com/tree-sitter/py-tree-sitter (README)
source_bytes = Path(file_path).read_bytes()
tree = py_parser.parse(source_bytes)
root_node = tree.root_node
```

### Query for Python Functions and Classes
```python
# Source: https://tree-sitter.github.io/py-tree-sitter/
PY_DEFS_QUERY = PY_LANGUAGE.query("""
  (function_definition
    name: (identifier) @func.name) @func.def

  (class_definition
    name: (identifier) @class.name) @class.def
""")

captures = PY_DEFS_QUERY.captures(root_node)
# captures is dict[str, list[Node]] in tree-sitter 0.21+
func_defs = captures.get("func.def", [])
class_defs = captures.get("class.def", [])
```

### Query for TypeScript Nodes
```python
# Source: tree-sitter-typescript grammar structure (confirmed from define-grammar.js)
TS_DEFS_QUERY = TS_LANGUAGE.query("""
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
```

### Docstring Extraction (Python)
```python
# Source: https://github.com/tree-sitter/tree-sitter/discussions/2470
# and https://github.com/tree-sitter/tree-sitter-python/issues/168
def _extract_docstring(node, source_bytes: bytes) -> str | None:
    """Extract docstring from function_definition or class_definition node."""
    body = node.child_by_field_name("body")
    if body is None:
        return None
    for child in body.children:
        if child.type == "expression_statement" and len(child.children) == 1:
            string_node = child.children[0]
            if string_node.type == "string":
                # Use string_content child for clean text without delimiters
                content_node = string_node.child_by_field_name("string_content")
                if content_node:
                    return source_bytes[content_node.start_byte:content_node.end_byte].decode("utf-8")
                # Fallback: strip delimiters from full string text
                raw = source_bytes[string_node.start_byte:string_node.end_byte].decode("utf-8")
                return raw.strip('"""').strip("'''").strip('"').strip("'").strip()
        break  # Only check FIRST statement in body
    return None
```

### Signature Extraction
```python
def _extract_signature(node, source_bytes: bytes) -> str:
    """Reconstruct the declaration line (everything before the body)."""
    body = node.child_by_field_name("body")
    if body:
        # Take all text up to the body node
        sig_bytes = source_bytes[node.start_byte:body.start_byte]
        return sig_bytes.decode("utf-8").rstrip().rstrip(":")
    # Fallback: first line only
    full_text = source_bytes[node.start_byte:node.end_byte].decode("utf-8")
    return full_text.split("\n")[0].rstrip(":")
```

### Node ID Construction
```python
# Source: PRD Section 5.3 — "relative_file_path::name"
from pathlib import Path

def _node_id(rel_path: str, name: str) -> str:
    # Normalize path separators to forward slash
    return f"{rel_path.replace(chr(92), '/')}::{name}"
```

### Complexity Computation
```python
# Source: PRD Section 5.3 — keyword count proxy
COMPLEXITY_KEYWORDS = frozenset(["if", "for", "while", "try", "elif", "and", "or"])

def _compute_complexity(body_text: str) -> int:
    tokens = body_text.split()
    return 1 + sum(1 for t in tokens if t in COMPLEXITY_KEYWORDS)
```

### CALLS Edge Detection (Python)
```python
# Source: https://tree-sitter.github.io/py-tree-sitter/
PY_CALLS_QUERY = PY_LANGUAGE.query("""
  (call
    function: (identifier) @call.target)

  (call
    function: (attribute
      attribute: (identifier) @call.method))
""")

def _extract_calls(func_node, source_bytes: bytes, source_id: str) -> list[tuple]:
    raw_edges = []
    captures = PY_CALLS_QUERY.captures(func_node)
    for target_node in captures.get("call.target", []) + captures.get("call.method", []):
        target_name = source_bytes[target_node.start_byte:target_node.end_byte].decode("utf-8")
        raw_edges.append((source_id, target_name, "CALLS"))
    return raw_edges
```

### IMPORTS Edge Detection (Python)
```python
# Source: tree-sitter-python grammar node types
PY_IMPORTS_QUERY = PY_LANGUAGE.query("""
  (import_statement
    name: (dotted_name) @import.name)

  (import_from_statement
    module_name: (dotted_name) @import.from)
""")
```

### Test Fixture Pattern
```python
# Location: backend/tests/conftest.py — UPDATE this fixture
@pytest.fixture
def python_sample_file(tmp_path: Path) -> Path:
    """Sample Python file with 2 functions + 1 class for PARSE-08 verification."""
    content = '''
def standalone_function(x: int) -> int:
    """A standalone function."""
    return x * 2

class MyClass:
    """A sample class."""

    def method_one(self):
        """First method."""
        result = standalone_function(42)
        return result
'''
    f = tmp_path / "sample.py"
    f.write_text(content.strip())
    return f
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `Language.build_library('/path/lib.so', ['grammar_dir'])` | `Language(tspython.language())` | tree-sitter 0.21 (2024) | No C compilation needed; grammars are pre-compiled Python wheels |
| `parser = Parser(); parser.set_language(lang)` | `parser = Parser(lang)` | tree-sitter 0.21 (2024) | Cleaner API; set_language removed |
| `captures()` returns `list[tuple[Node, str]]` | `captures()` returns `dict[str, list[Node]]` | tree-sitter 0.21 (2024) | Iteration pattern must change |
| Pass language name string to Language() | Pass capsule object from `tspython.language()` | tree-sitter 0.21 (2024) | Language strings no longer work |

**Deprecated/outdated:**
- `Language.build_library()`: Removed in 0.21+. All grammar packages now ship pre-compiled.
- `parser.set_language()`: Deprecated and removed. Pass language to Parser constructor.
- Integer-based language handle: `tspython.language()` used to return an int; now returns a capsule object.

---

## Open Questions

1. **TypeScript TSX files: should `.tsx` files use TSX parser or TypeScript parser?**
   - What we know: tree-sitter-typescript has both `language_typescript()` and `language_tsx()`. The PRD says `typescript` language covers `.ts/.tsx/.js/.jsx` but the grammars are technically different.
   - What's unclear: Whether the TypeScript parser correctly handles TSX JSX syntax, or whether `.tsx` files need the TSX parser.
   - Recommendation: Map `.tsx` → `TSX_LANGUAGE` and `.ts/.js/.jsx` → `TS_LANGUAGE`. The PRD already groups these under the `typescript` language label, but the parser should internally select the right dialect by extension.

2. **Arrow function names in TypeScript: what if not assigned to a variable?**
   - What we know: `const foo = () => {}` has a name via the variable_declarator parent. `export default () => {}` does not.
   - What's unclear: PRD says extract `arrow_function` nodes — does this include unnamed ones?
   - Recommendation: Skip unnamed arrow functions (no viable node ID can be formed). Only extract arrow functions that are assigned to a named variable or exported with a name. Generate `<anonymous>` fallback only if needed for test compliance.

3. **Are `tree-sitter` and `tree-sitter-python`/`tree-sitter-typescript` version-locked to each other?**
   - What we know: tree-sitter-python 0.23.0 broke with tree-sitter <0.23.0 due to the capsule vs. integer return type change.
   - What's unclear: Whether `tree-sitter==0.25.2` + `tree-sitter-python==0.25.0` + `tree-sitter-typescript==0.23.2` are all compatible.
   - Recommendation: Pin all three to the latest known-compatible versions in requirements.txt. Validate compatibility by running `Language(tspython.language())` in a smoke test before implementing the full parser.

---

## Sources

### Primary (HIGH confidence)
- `https://github.com/tree-sitter/py-tree-sitter` — Parser constructor API, Language API, captures() return type, Query usage
- `https://tree-sitter.github.io/py-tree-sitter/` — Official API reference; version 0.25.2 confirmed
- `https://tree-sitter.github.io/py-tree-sitter/classes/tree_sitter.Parser.html` — Parser class: constructor signature `Parser(language, ...)`, parse() method
- `https://raw.githubusercontent.com/tree-sitter/tree-sitter-typescript/master/bindings/python/tree_sitter_typescript/__init__.py` — Confirmed `language_typescript` and `language_tsx` as exported names
- `https://github.com/tree-sitter/tree-sitter/discussions/2470` — Docstring as expression_statement > string pattern confirmed
- `https://github.com/tree-sitter/tree-sitter-python/issues/280` — Breaking change: tspython.language() returns capsule object in 0.23+; fix is upgrading tree-sitter to matching version
- PRD Section 5.3 — All exact node types, field names, CodeNode schema, complexity definition

### Secondary (MEDIUM confidence)
- `https://github.com/tree-sitter/tree-sitter-python/issues/168` — Docstring AST structure: `(function_definition body: (block . (expression_statement (string) @docstring)))` pattern
- `https://github.com/tree-sitter/py-tree-sitter/discussions/231` — Correct TypeScript import: `from tree_sitter_typescript import language_typescript, language_tsx`
- `https://dev.to/shrsv/diving-into-tree-sitter-parsing-code-with-python-like-a-pro-17h8` — child_by_field_name() usage, node.text, start_point/end_point examples

### Tertiary (LOW confidence)
- `https://pypi.org/project/tree-sitter/` — Latest version 0.25.2 (as of research date; version may advance)
- `https://pypi.org/project/tree-sitter-python/` — Latest version 0.25.0
- `https://pypi.org/project/tree-sitter-typescript/` — Latest version 0.23.2

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Official docs confirmed; Library IDs verified on PyPI; PRD explicitly specifies these packages
- Architecture: HIGH — PRD specifies exact function signatures, node types, field names, CodeNode schema
- Pitfalls: HIGH — All version breaking changes verified against official issues and release notes; docstring AST pattern confirmed via official discussion
- TypeScript arrow function naming: MEDIUM — Grammar structure inferred; edge cases not fully verified
- TSX vs TS parser selection: MEDIUM — Two dialects confirmed; exact boundary between them not officially documented for `.jsx` files

**Research date:** 2026-03-18
**Valid until:** 2026-04-18 (stable libraries; tree-sitter releases are infrequent)
