#!/usr/bin/env python3
"""
ᛗᛁᚨᛋᛗᚨ — standalone desktop window launcher (no browser UI).

Opens the app in a dedicated window:
  1. Chrome/Chromium --app mode (preferred — real engine, fog/WebGL work)
  2. pywebview fallback if no Chrome found

Starts the backend automatically if it isn't already running.
On window close it fires /api/panic (aborts streams, unloads models —
model files and open apps are never touched).

Usage:  python run_desktop.py
"""
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
URL = "http://127.0.0.1:8000"


def port_open(port=8000, host="127.0.0.1"):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def wait_up(timeout=30):
    for _ in range(timeout * 2):
        try:
            urllib.request.urlopen(URL + "/api/status", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def panic():
    try:
        urllib.request.urlopen(
            urllib.request.Request(URL + "/api/panic", method="POST"), timeout=5)
    except Exception:
        pass


def ensure_backend():
    if port_open():
        return
    print("starting backend…")
    subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", "8000"],
        cwd=BACKEND,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not wait_up():
        print("backend failed to start")
        sys.exit(1)


def chrome_app():
    for exe in ("google-chrome", "google-chrome-stable", "chromium",
                "chromium-browser", "microsoft-edge"):
        path = shutil.which(exe)
        if path:
            return path
    return None


def main():
    ensure_backend()

    chrome = chrome_app()
    if chrome:
        print(f"opening ᛗᛁᚨᛋᛗᚨ window → {URL}  ({chrome} --app)")
        try:
            subprocess.run([chrome, "--app=" + URL,
                            "--class=dev.miasma.app",
                            "--user-data-dir=" + os.path.join(ROOT, ".chrome-app-profile"),
                            "--no-first-run", "--disable-session-crashed-bubble"])
        finally:
            panic()
        return

    # fallback: pywebview
    try:
        import webview
    except ImportError:
        print("No Chrome/Chromium found and pywebview is not installed.\n"
              "Install either:  pip install pywebview   (inside .venv)\n"
              "or install Chrome/Chromium and run again.")
        sys.exit(1)
    print(f"opening ᛗᛁᚨᛋᛗᚨ window → {URL}  (pywebview)")
    webview.create_window("ᛗᛁᚨᛋᛗᚨ", URL, width=1440, height=900,
                          min_size=(900, 600))
    try:
        webview.start(private_mode=True, debug=True)
    finally:
        panic()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        panic()
