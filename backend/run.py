"""PyInstaller entry point — starts the Nexus backend via uvicorn."""
import argparse
import uvicorn
from app.main import app

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(app, host='127.0.0.1', port=args.port)
