# ᛗᛁᚨᛋᛗᚨ (MIASMA) — Multi AI

A calm, private, local-first AI workspace: chat with local or cloud models, build projects in a managed workspace, generate media, and run live avatar pipelines — all from one dark glass dashboard on your own machine.

📋 **Project Board:** [ᛗᛁᚨᛋᛗᚨ (MIASMA) — Multi AI](https://github.com/users/DewTechAI/projects/2)

---

## Requirements

- **Python 3.10+**
- **[Ollama](https://ollama.com)** running locally (for local models)
- **Optional:** CMake + g++ (C++ telemetry/sandbox layer — the app works without it)

---

## Quick Start

```bash
make install        # pip install -r backend/requirements.txt
./run.sh            # or: python3 run_desktop.py  (desktop window)
# web only: python3 -m uvicorn app.main:app --app-dir backend --port 8000
