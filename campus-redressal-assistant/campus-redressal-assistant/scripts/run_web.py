"""Start the browser MVP with its own disposable indexes."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    args = parser.parse_args()

    runtime = ROOT / ".web-runtime"
    os.environ.setdefault("CHROMA_PERSIST_DIR", str(runtime / "chroma"))
    os.environ.setdefault("SQLITE_DIRECTORY_DB", str(runtime / "directory.db"))
    uvicorn.run("web_app:app", host=args.host, port=args.port, access_log=False)
