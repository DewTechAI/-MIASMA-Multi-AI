
# ᛗᛁᚨᛋᛗᚨ (MIASMA) — Multi AI

A calm, private, local-first AI workspace: chat with local or cloud models, build projects in a managed workspace, generate media, and run live avatar pipelines — all from one dark glass dashboard on your own machine.

📋 **Project Board:** [ᛗᛁᚨᛋᛗᚨ (MIASMA) — Multi AI](https://github.com/users/DewTechAI/projects/2)

---

## Overview & Design Philosophy

**ᛗᛁᚨᛋᛗᚨ (MIASMA)** is a local-first AI orchestration workspace designed for privacy, smooth multi-stage execution, and real-world hardware constraints — especially CPU-only laptops and limited-RAM systems.

- **Single-Model RAM Orchestration:** Sequential model handoff stages (`whisper-dark`, `obsidian-mind`, and `void-weaver` across chat, planning, and coding) keep memory usage predictable so heavy models do not pile up in RAM at the same time.
- **Abyssal Blue Dark Glass UI:** Translucent dark glass interface paired with an explorer-style workspace tree for clean navigation and focused daily work.
- **Offline-First with Optional Cloud Bridges:** Works locally via Ollama without requiring cloud accounts, while allowing optional cloud APIs and media keys when configured.

---

## Requirements

- **Python 3.10+**
- **[Ollama](https://ollama.com)** running locally (for local models)
- **Optional:** `CMake` + `g++` (for the C++ telemetry/sandbox layer — the application works without it)

---

## Quick Start

```bash
make install        # pip install -r backend/requirements.txt
./run.sh            # or: python3 run_desktop.py  (desktop window)
# web only: python3 -m uvicorn app.main:app --app-dir backend --port 8000

```

Open `http://127.0.0.1:8000`. On first launch, you'll get a short **Terms → Note → Module** setup walkthrough.

---

## Features

* **Chat** — Local/cloud model routing across sequential handoff stages (`whisper-dark`, `obsidian-mind`, `void-weaver`), agent mode with tools, persistent history, checkpoints/resume, streaming responses, and attachments.
* **Workspace** — Explorer-style workspace tree, create/edit/run files, safe sandboxed execution, and dynamic project folders.
* **Media Studio** — Image, video, lip-sync, and cinema shot prompt workflows (**Gemini**, **Vercel AI Gateway**, or **Freepik** keys in **Settings**).
* **PersonaLive** — Real-time portrait, lip-sync, and talking-head module (optional external service with graceful fallback when offline).
* **Models** — Lazy loading (one heavy model in RAM at a time), Download button with live progress, and lightweight / tiny-model presets for 4 GB and CPU-only machines.
* **System** — CPU/RAM/VRAM telemetry, automatic cleanup, and panic stop.
* **Shell & Web Tools** — Controlled shell commands and web utilities integrated into workspace and agent workflows.

---

## Project Structure

```text
miasma/
├── backend/
│   └── app/
│       ├── __init__.py
│       ├── agent.py          # Agent loop and tool calling
│       ├── config.py         # Application & environment configuration
│       ├── db.py             # Persistent storage & checkpoints
│       ├── main.py           # FastAPI application entrypoint
│       ├── ollama.py         # Local Ollama client & model runner
│       ├── orchestrator.py   # Request routing & sequential model handoffs
│       ├── registry.py       # Model registry, presets & lifecycle
│       ├── sandbox.py        # Sandboxed execution controls
│       ├── telemetry.py      # Resource & runtime telemetry
│       └── workspace.py      # Workspace tree & project file operations
├── cpp/
│   ├── CMakeLists.txt
│   ├── include/
│   │   ├── sandbox.hpp
│   │   └── telemetry.hpp
│   └── src/
│       ├── main.cpp
│       ├── sandbox.cpp
│       ├── sandbox_main.cpp
│       └── telemetry.cpp
├── frontend/
│   └── index.html            # Abyssal Blue dark glass UI & explorer tree
├── modules/
│   ├── media_studio.py       # Image, video, lip-sync & cinema shot workflows
│   ├── persona_live.py       # Live avatar / lip-sync integration
│   ├── shell_tools.py        # Shell tool helpers
│   ├── web_tools.py          # Web tool helpers
│   └── workspace_tools.py    # Workspace tool helpers
├── .env.example              # Sample environment configuration
├── Makefile                  # Build & setup shortcuts
├── multi-ai.service          # systemd service unit for Linux background hosting
├── run.sh                    # Linux launcher script
├── run_desktop.py            # Desktop window launcher
└── run_windows.py            # Windows launcher script

```

---

## Settings

API keys and model preferences live in **Settings → Media Studio API Keys** and **Models**. Everything works fully offline with local Ollama models; cloud providers are optional.

---

## Platforms & Deployment

* **Linux:** Use `./run.sh` or `python3 run_desktop.py` for desktop/CLI runs, or `multi-ai.service` for `systemd` background hosting.
* **Windows:** Use `run_windows.py` — same steps, CMD/PowerShell friendly. See the file for details.
* **Optional C++ Layer:** Build `cpp/` with `CMake` and `g++` if you want native telemetry/sandbox binaries; the app runs cleanly without them.

---

## License

Apache 2.0 — see the [project board](https://github.com/users/DewTechAI/projects/2) and repository license for details.

```

---

### Terminal එකෙන් `README.md` Save කරලා Push කරන්න:

```bash
cd "/home/anu/Documents/miasma_upload"
cat << 'EOF' > README.md
# ᛗᛁᚨᛋᛗᚨ (MIASMA) — Multi AI

A calm, private, local-first AI workspace: chat with local or cloud models, build projects in a managed workspace, generate media, and run live avatar pipelines — all from one dark glass dashboard on your own machine.

📋 **Project Board:** [ᛗᛁᚨᛋᛗᚨ (MIASMA) — Multi AI](https://github.com/users/DewTechAI/projects/2)

---

## Overview & Design Philosophy

**ᛗᛁᚨᛋᛗᚨ (MIASMA)** is a local-first AI orchestration workspace designed for privacy, smooth multi-stage execution, and real-world hardware constraints — especially CPU-only laptops and limited-RAM systems.

- **Single-Model RAM Orchestration:** Sequential model handoff stages (`whisper-dark`, `obsidian-mind`, and `void-weaver` across chat, planning, and coding) keep memory usage predictable so heavy models do not pile up in RAM at the same time.
- **Abyssal Blue Dark Glass UI:** Translucent dark glass interface paired with an explorer-style workspace tree for clean navigation and focused daily work.
- **Offline-First with Optional Cloud Bridges:** Works locally via Ollama without requiring cloud accounts, while allowing optional cloud APIs and media keys when configured.

---

## Requirements

- **Python 3.10+**
- **[Ollama](https://ollama.com)** running locally (for local models)
- **Optional:** `CMake` + `g++` (for the C++ telemetry/sandbox layer — the application works without it)

---

## Quick Start

```bash
make install        # pip install -r backend/requirements.txt
./run.sh            # or: python3 run_desktop.py  (desktop window)
# web only: python3 -m uvicorn app.main:app --app-dir backend --port 8000

```

Open `http://127.0.0.1:8000`. On first launch, you'll get a short **Terms → Note → Module** setup walkthrough.

---

## Features

* **Chat** — Local/cloud model routing across sequential handoff stages (`whisper-dark`, `obsidian-mind`, `void-weaver`), agent mode with tools, persistent history, checkpoints/resume, streaming responses, and attachments.
* **Workspace** — Explorer-style workspace tree, create/edit/run files, safe sandboxed execution, and dynamic project folders.
* **Media Studio** — Image, video, lip-sync, and cinema shot prompt workflows (**Gemini**, **Vercel AI Gateway**, or **Freepik** keys in **Settings**).
* **PersonaLive** — Real-time portrait, lip-sync, and talking-head module (optional external service with graceful fallback when offline).
* **Models** — Lazy loading (one heavy model in RAM at a time), Download button with live progress, and lightweight / tiny-model presets for 4 GB and CPU-only machines.
* **System** — CPU/RAM/VRAM telemetry, automatic cleanup, and panic stop.
* **Shell & Web Tools** — Controlled shell commands and web utilities integrated into workspace and agent flows.

---

## Project Structure

```text
miasma/
├── backend/
│   └── app/
│       ├── __init__.py
│       ├── agent.py          # Agent loop and tool calling
│       ├── config.py         # Application & environment configuration
│       ├── db.py             # Persistent storage & checkpoints
│       ├── main.py           # FastAPI application entrypoint
│       ├── ollama.py         # Local Ollama client & model runner
│       ├── orchestrator.py   # Request routing & sequential model handoffs
│       ├── registry.py       # Model registry, presets & lifecycle
│       ├── sandbox.py        # Sandboxed execution controls
│       ├── telemetry.py      # Resource & runtime telemetry
│       └── workspace.py      # Workspace tree & project file operations
├── cpp/
│   ├── CMakeLists.txt
│   ├── include/
│   │   ├── sandbox.hpp
│   │   └── telemetry.hpp
│   └── src/
│       ├── main.cpp
│       ├── sandbox.cpp
│       ├── sandbox_main.cpp
│       └── telemetry.cpp
├── frontend/
│   └── index.html            # Abyssal Blue dark glass UI & explorer tree
├── modules/
│   ├── media_studio.py       # Image, video, lip-sync & cinema shot workflows
│   ├── persona_live.py       # Live avatar / lip-sync integration
│   ├── shell_tools.py        # Shell tool helpers
│   ├── web_tools.py          # Web tool helpers
│   └── workspace_tools.py    # Workspace tool helpers
├── .env.example              # Sample environment configuration
├── Makefile                  # Build & setup shortcuts
├── multi-ai.service          # systemd service unit for Linux background hosting
├── run.sh                    # Linux launcher script
├── run_desktop.py            # Desktop window launcher
└── run_windows.py            # Windows launcher script

```

---

## Settings

API keys and model preferences live in **Settings → Media Studio API Keys** and **Models**. Everything works fully offline with local Ollama models; cloud providers are optional.

---

## Platforms & Deployment

* **Linux:** Use `./run.sh` or `python3 run_desktop.py` for desktop/CLI runs, or `multi-ai.service` for `systemd` background hosting.
* **Windows:** Use `run_windows.py` — same steps, CMD/PowerShell friendly. See the file for details.
* **Optional C++ Layer:** Build `cpp/` with `CMake` and `g++` if you want native telemetry/sandbox binaries; the app runs cleanly without them.

---

## License

Apache 2.0 — see the [project board](https://github.com/users/DewTechAI/projects/2) and repository license for details.
EOF
git add README.md
git commit -m "Add complete README for MIASMA Multi-AI"
git push origin main

```

