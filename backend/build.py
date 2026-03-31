#!/usr/bin/env python3
"""
Build script: produces a single-file Nexus backend binary using PyInstaller.
Output: nexus-backend-mac (macOS) or nexus-backend-win.exe (Windows)
"""
import sys
import subprocess
import platform
from pathlib import Path


def _check_sqlite_vec_support() -> None:
    """Abort the build if the current Python cannot load SQLite extensions.

    sqlite-vec requires enable_load_extension, which is only available when
    Python is compiled with --enable-loadable-sqlite-extensions. Catching this
    here prevents shipping a binary that fails on every user's machine.
    """
    import sqlite3
    conn = sqlite3.connect(":memory:")
    try:
        conn.enable_load_extension(True)
        conn.close()
    except AttributeError:
        conn.close()
        print(
            "ERROR: sqlite3.enable_load_extension is not available in this Python build.\n"
            "The produced binary would fail for all users. Rebuild Python first:\n"
            "  PYTHON_CONFIGURE_OPTS='--enable-loadable-sqlite-extensions' "
            "pyenv install 3.11.13 --force\n"
            "Then recreate your venv and retry.",
            file=sys.stderr,
        )
        sys.exit(1)


def main():
    _check_sqlite_vec_support()
    system = platform.system()
    if system == 'Darwin':
        name = 'nexus-backend-mac'
    elif system == 'Windows':
        name = 'nexus-backend-win'
    else:
        print(f"Unsupported platform: {system}", file=sys.stderr)
        sys.exit(1)

    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--onefile',
        '--name', name,
        '--distpath', '../extension/bin',  # output to extension/bin/ relative to backend/
        '--workpath', 'build/_pyinstaller',
        '--specpath', 'build',
        '--hidden-import', 'uvicorn.logging',
        '--hidden-import', 'uvicorn.loops',
        '--hidden-import', 'uvicorn.loops.auto',
        '--hidden-import', 'uvicorn.protocols',
        '--hidden-import', 'uvicorn.protocols.http',
        '--hidden-import', 'uvicorn.protocols.http.auto',
        '--hidden-import', 'uvicorn.protocols.websockets',
        '--hidden-import', 'uvicorn.protocols.websockets.auto',
        '--hidden-import', 'uvicorn.lifespan',
        '--hidden-import', 'uvicorn.lifespan.on',
        '--hidden-import', 'app.api.config_router',
        '--hidden-import', 'app.api.index_router',
        '--hidden-import', 'app.api.query_router',
        # Collect all files (including .dylib/.so/.abi3.so data files) for
        # packages that load native extensions at runtime via __file__ paths.
        '--collect-all', 'sqlite_vec',
        '--collect-all', 'tree_sitter',
        '--collect-all', 'tree_sitter_python',
        '--collect-all', 'tree_sitter_typescript',
        'run.py',  # entrypoint that calls uvicorn.run(app)
    ]

    print(f"Building {name}...")
    result = subprocess.run(cmd, cwd=str(Path(__file__).parent))
    sys.exit(result.returncode)


if __name__ == '__main__':
    main()
