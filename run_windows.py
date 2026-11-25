#!/usr/bin/env python3
"""
ᛗᛁᚨᛋᛗᚨ — Windows & cross-platform launcher.

Starts the FastAPI backend (which also serves the frontend) on http://localhost:8000
and opens it in the default browser. Works on Windows, Linux, and macOS.

Usage:
    python run_windows.py            # host 127.0.0.1, port 8000
    python run_windows.py --port 8080 --host 0.0.0.0

Requirements: pip install -r backend/requirements.txt
"""
import argparse
import os
import sys
import threading
import time
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)


def main():
    ap = argparse.ArgumentParser(description="ᛗᛁᚨᛋᛗᚨ launcher")
    ap.add_argument("--host", default=os.environ.get("MIASMA_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("MIASMA_PORT", "8000")))
    ap.add_argument("--no-browser", action="store_true", help="don't auto-open browser")
    args = ap.parse_args()

    os.chdir(BACKEND)  # backend uses relative paths (workspace/, .env)

    import uvicorn
    from app import config  # noqa: F401  (loads .env / defaults)

    url = f"http://{args.host}:{args.port}"
    print(f"ᛗᛁᚨᛋᛗᚨ starting on {url}  (Ctrl+C to stop)")

    if not args.no_browser:
        def _open():
            time.sleep(1.5)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    try:
        uvicorn.run("app.main:app", host=args.host, port=args.port,
                    reload=False, log_level="info")
    except KeyboardInterrupt:
        print("\nbye.")


if __name__ == "__main__":
    main()
