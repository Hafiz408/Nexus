#!/usr/bin/env python3
"""
Build script: produces a single-file Nexus backend binary using PyInstaller.
Output: nexus-backend-mac (macOS) or nexus-backend-win.exe (Windows)
"""
import sys
import subprocess
import platform
from pathlib import Path


def main():
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
        'run.py',  # entrypoint that calls uvicorn.run(app)
    ]

    print(f"Building {name}...")
    result = subprocess.run(cmd, cwd=str(Path(__file__).parent))
    sys.exit(result.returncode)


if __name__ == '__main__':
    main()
