#!/usr/bin/env python3
"""
Build script: produces a Nexus backend binary using PyInstaller.

Strategy: --onedir for fast startup, then tar the output directory into a
single .tar.gz so vsce packaging sees one file (not thousands).

Output:
  extension/bin/nexus-backend-mac.tar.gz   (macOS)
  extension/bin/nexus-backend-win.tar.gz   (Windows)

SidecarManager extracts the archive once into globalStoragePath keyed by
version, then spawns the cached executable on every subsequent launch.
"""
import sys
import subprocess
import platform
import tarfile
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
        '--onedir',   # folder layout: no per-launch extraction → ~1s startup vs ~25s
        '--name', name,
        '--distpath', '../extension/bin',  # output to extension/bin/<name>/ relative to backend/
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
        '--collect-all', 'numpy',
        '--collect-all', 'scipy',
        'run.py',  # entrypoint that calls uvicorn.run(app)
    ]

    print(f"Building {name}...")
    result = subprocess.run(cmd, cwd=str(Path(__file__).parent))
    if result.returncode != 0:
        sys.exit(result.returncode)

    # Tar the --onedir output into a single archive so vsce packaging works.
    # vsce's secret scanner fails with EISDIR when it walks thousands of loose files.
    backend_dir = Path(__file__).parent
    dist_dir = backend_dir.parent / 'extension' / 'bin'
    onedir_path = dist_dir / name          # e.g. extension/bin/nexus-backend-mac/
    archive_path = dist_dir / f'{name}.tar.gz'

    print(f"Archiving {onedir_path} -> {archive_path} ...")
    with tarfile.open(archive_path, 'w:gz') as tar:
        tar.add(onedir_path, arcname=name)

    # Remove the raw directory so only the archive ships in the VSIX.
    import shutil
    shutil.rmtree(onedir_path)
    print(f"Done. Archive size: {archive_path.stat().st_size / 1_048_576:.1f} MB")


if __name__ == '__main__':
    main()
