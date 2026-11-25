# ᛗᛁᚨᛋᛗᚨ (MIASMA) — Multi AI

A calm, private, local-first AI workspace: chat with local or cloud models,
build projects in a managed workspace, generate media, and run live avatar
pipelines — all from one dark glass dashboard on your own machine.

Project board: [ᛗᛁᚨᛋᛗᚨ (MIASMA) — Multi AI](https://github.com/users/DewTechAI/projects/2)

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) running locally (for local models)
- Optional: CMake + g++ (C++ telemetry/sandbox layer — the app works without it)

## Quick start

```bash
make install        # pip install -r backend/requirements.txt
./run.sh            # or: python3 run_desktop.py  (desktop window)
# web only: python3 -m uvicorn app.main:app --app-dir backend --port 8000
```

Open `http://127.0.0.1:8000`. On first launch you'll get a short
Terms → Note → Module setup walkthrough.

## Features

- **Chat** — local/cloud model routing, agent mode with tools, persistent
  history, checkpoints/resume, streaming, attachments
- **Workspace** — file explorer, create/edit/run files, safe sandboxed
  execution, dynamic project folders
- **Media Studio** — image/video/lip-sync prompt workflows (Gemini /
  Vercel AI Gateway / Freepik keys in Settings)
- **PersonaLive** — real-time portrait/lip-sync/talking-head module
  (optional external service, graceful fallback when offline)
- **Models** — lazy loading (one module in RAM at a time), Download button
  with live progress, tiny-model presets for 4 GB machines
- **System** — CPU/RAM/VRAM telemetry, auto cleanup, panic stop

## Settings

API keys and model preferences live in **Settings** → Media Studio API Keys
and Models. Everything works fully offline with local Ollama models; cloud
providers are optional.

## Windows

Use `run_windows.py` — same steps, CMD/PowerShell friendly. See the file for
details.

## License

Apache 2.0 — see project board for details.
# -MIASMA-Multi-AI
