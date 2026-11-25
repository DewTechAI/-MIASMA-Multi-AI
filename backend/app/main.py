"""FastAPI backend: REST + WebSocket endpoints, serves the dashboard."""
import asyncio
import json
import logging
import time

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from . import config, db, ollama, orchestrator, registry, sandbox, telemetry, workspace

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("multi_ai")

app = FastAPI(title="Multi-AI Dashboard", version="0.2.0")


@app.on_event("startup")
def _startup():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    db.init_db()
    modules = registry.scan_modules()
    healthy = sum(1 for m in modules.values() if m.get("healthy"))
    log.info("data_dir=%s workspace=%s auth=%s modules=%d/%d healthy",
             config.DATA_DIR, config.WORKSPACE_DIR,
             "enabled" if config.AUTH_TOKEN else "disabled (localhost only)",
             healthy, len(modules))


# ---------------- middleware ----------------

@app.middleware("http")
async def security_and_logging(request: Request, call_next):
    # Bearer-token auth for /api/* (skip /api/health).
    if config.AUTH_TOKEN and request.url.path.startswith("/api/") \
            and request.url.path != "/api/health":
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {config.AUTH_TOKEN}":
            return JSONResponse({"detail": "unauthorized"}, status_code=401)

    start = time.monotonic()
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    log.info("%s %s -> %s (%.0fms)", request.method, request.url.path,
             response.status_code, (time.monotonic() - start) * 1000)
    return response


if config.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )


# ---------------- REST ----------------

@app.get("/api/health")
def health():
    """Liveness + readiness probe (unauthenticated, no sensitive data)."""
    try:
        snap = telemetry.snapshot()
        hw_ok = "error" not in snap
    except Exception:
        hw_ok = False
    return {
        "status": "ok",
        "ollama": ollama.is_running(),
        "hwmon": hw_ok,
    }


@app.get("/api/status")
def status():
    return orchestrator.status()


@app.get("/api/telemetry")
def get_telemetry():
    return telemetry.assess()


@app.get("/api/models")
def models():
    """Models actually installed on this machine's Ollama."""
    return {"host": __import__("socket").gethostname(),
            "ollama": config.OLLAMA_HOST,
            "models": ollama.model_details() if ollama.is_running() else []}


@app.get("/api/modules")
def list_modules():
    return registry.list_modules()


@app.post("/api/modules/rescan")
def rescan_modules():
    return registry.scan_modules()


class SettingIn(BaseModel):
    key: str
    value: object

    @field_validator("key")
    @classmethod
    def _known_key(cls, v):
        allowed = {"local_model", "coding_model", "reasoning_model", "cloud_model", "auto_run_code",
                   "module_prefs", "custom_providers"}
        if v not in allowed:
            raise ValueError(f"unknown setting '{v}'")
        return v


@app.get("/api/settings")
def get_settings():
    return {
        "local_model": db.get_setting("local_model", config.DEFAULT_LOCAL_MODEL),
        "coding_model": db.get_setting("coding_model", config.CODING_LOCAL_MODEL),
        "reasoning_model": db.get_setting("reasoning_model", config.REASONING_LOCAL_MODEL),
        "cloud_model": db.get_setting("cloud_model", config.DEFAULT_CLOUD_MODEL),
        "auto_run_code": db.get_setting("auto_run_code", False),
        "module_prefs": db.get_setting("module_prefs", {}),
        "custom_providers": db.get_setting("custom_providers", {}) or {},
        "providers": db.vault_list(),
        "auth_enabled": bool(config.AUTH_TOKEN),
    }


@app.put("/api/settings")
def put_setting(s: SettingIn):
    db.set_setting(s.key, s.value)
    return {"ok": True}


class KeyIn(BaseModel):
    provider: str
    api_key: str

    @field_validator("provider")
    @classmethod
    def _provider(cls, v):
        import re
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", v):
            raise ValueError("provider must be a slug (a-z, 0-9, _ or -)")
        return v

    @field_validator("api_key")
    @classmethod
    def _key_len(cls, v):
        if not (8 <= len(v) <= 512):
            raise ValueError("api_key length out of range")
        return v


@app.put("/api/keys")
def put_key(k: KeyIn):
    db.vault_set(k.provider, k.api_key)
    log.info("stored api key for provider=%s", k.provider)
    return {"ok": True, "provider": k.provider}


@app.delete("/api/keys/{provider}")
def del_key(provider: str):
    db.vault_delete(provider)
    return {"ok": True}


# ---------- custom AI providers (OpenAI-compatible) ----------

class ProviderIn(BaseModel):
    name: str
    base_url: str = ""
    model: str = ""
    api_key: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        import re
        v = v.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", v):
            raise ValueError("name must be a slug (a-z, 0-9, _ or -)")
        return v

    @field_validator("base_url")
    @classmethod
    def _base(cls, v):
        v = (v or "").strip().rstrip("/")
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return v


def _custom_cfg():
    return db.get_setting("custom_providers", {}) or {}


@app.put("/api/providers")
def put_provider(p: ProviderIn):
    if p.name in ("deepseek", "openai", "ollama", "agent"):
        raise HTTPException(400, "reserved provider name")
    cfg = _custom_cfg()
    cfg[p.name] = {"base_url": p.base_url, "model": p.model.strip()}
    db.set_setting("custom_providers", cfg)
    if p.api_key:
        db.vault_set(p.name, p.api_key)
        log.info("stored credentials for custom provider=%s", p.name)
    return {"ok": True, "provider": p.name}


@app.delete("/api/providers/{name}")
def del_provider(name: str):
    cfg = _custom_cfg()
    cfg.pop(name, None)
    db.set_setting("custom_providers", cfg)
    db.vault_delete(name)
    return {"ok": True}


@app.post("/api/providers/test")
def test_provider(p: ProviderIn):
    """Lightweight connectivity check via the provider's /models endpoint."""
    import httpx as _hx
    cfg = _custom_cfg().get(p.name, {})
    base = p.base_url or cfg.get("base_url", "")
    key = p.api_key or db.vault_get(p.name) or ""
    if not base:
        return {"ok": False, "error": "no base_url configured"}
    if not key:
        return {"ok": False, "error": "no API key stored"}
    try:
        r = _hx.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"},
                    timeout=10.0)
        return {"ok": r.status_code < 400, "status": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}


@app.get("/api/history/{session_id}")
def history(session_id: str):
    return db.get_history(session_id, limit=200)


@app.delete("/api/history/{session_id}")
def clear_history(session_id: str):
    db.clear_history(session_id)
    return {"ok": True}


@app.get("/api/chats")
def list_chats():
    return db.list_sessions()


@app.post("/api/abort")
def abort_all():
    """Kill in-flight streams; models stay warm for the next turn."""
    streams = ollama.abort_active_streams()
    return {"ok": True, "streams_aborted": streams, "models_kept_warm": True}


@app.post("/api/panic")
def panic():
    """Hard stop: abort every stream and unload all resident models now."""
    streams = ollama.abort_active_streams()
    unloaded = ollama.unload_all_models() if ollama.is_running() else 0
    log.warning("panic: aborted %d streams, unloaded %d models", streams, unloaded)
    return {"ok": True, "streams_aborted": streams, "models_unloaded": unloaded}


# ---------------- Activity registry (survives page refresh) ----------------
import threading as _threading
_activity = {"count": 0, "label": "", "lock": _threading.Lock()}


def _act_start():
    with _activity["lock"]:
        _activity["count"] += 1


def _act_stop():
    with _activity["lock"]:
        _activity["count"] = max(0, _activity["count"] - 1)
        if _activity["count"] == 0:
            _activity["label"] = ""


def _act_label(text):
    with _activity["lock"]:
        _activity["label"] = text[:80]


@app.get("/api/activity")
def activity():
    with _activity["lock"]:
        return {"active": _activity["count"] > 0,
                "count": _activity["count"],
                "label": _activity["label"]}


# ---------------- Checkpoints ----------------

class CheckpointIn(BaseModel):
    session_id: str
    note: str


@app.get("/api/checkpoint/{session_id}")
def get_checkpoint(session_id: str):
    note = workspace.load_checkpoint(session_id)
    return {"note": note} if note is not None else {"note": None}


@app.post("/api/checkpoint")
def put_checkpoint(c: CheckpointIn):
    if len(c.note) > 50000:
        raise HTTPException(400, "checkpoint too large")
    return {"ok": True, **workspace.save_checkpoint(c.session_id, c.note)}


@app.delete("/api/checkpoint/{session_id}")
def del_checkpoint(session_id: str):
    return {"deleted": workspace.delete_checkpoint(session_id)}


# ---------------- Workspace ----------------

@app.get("/api/workspaces")
def list_workspaces():
    return workspace.roots()


class WorkspaceIn(BaseModel):
    path: str


@app.post("/api/workspaces")
def add_workspace(w: WorkspaceIn):
    try:
        return {"ok": True, **workspace.add_root(w.path)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/workspaces/{name}")
def remove_workspace(name: str):
    try:
        workspace.remove_root(name)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/files")
def files(root: str | None = None):
    try:
        return workspace.tree(root)
    except ValueError as e:
        raise HTTPException(400, str(e))


class FileIn(BaseModel):
    path: str
    content: str

    @field_validator("content")
    @classmethod
    def _size(cls, v):
        if len(v.encode()) > config.MAX_FILE_BYTES:
            raise ValueError("file too large")
        return v


@app.get("/api/files/{path:path}")
def read_file(path: str):
    try:
        return {"path": path, "content": workspace.read_file(path)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.put("/api/files/{path:path}")
def write_file(path: str, f: FileIn):
    try:
        return workspace.write_file(path, f.content)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.delete("/api/files/{path:path}")
def delete_file(path: str):
    return {"deleted": workspace.delete_file(path)}


class RunIn(BaseModel):
    path: str
    mem_mb: int = config.SANDBOX_MEM_MB
    wall_seconds: int = config.SANDBOX_WALL_SECONDS

    @field_validator("mem_mb")
    @classmethod
    def _mem(cls, v):
        if not (16 <= v <= 8192):
            raise ValueError("mem_mb out of range")
        return v

    @field_validator("wall_seconds")
    @classmethod
    def _wall(cls, v):
        if not (1 <= v <= 600):
            raise ValueError("wall_seconds out of range")
        return v


@app.post("/api/run")
def run_file(r: RunIn):
    """Execute a workspace file in the C++ sandbox."""
    try:
        script = config.WORKSPACE_DIR / r.path
        # Ensure the resolved path stays inside the workspace.
        script.resolve().relative_to(config.WORKSPACE_DIR.resolve())
    except Exception:
        return JSONResponse({"error": "invalid path"}, status_code=400)
    log.info("sandbox run: %s (mem=%dMB wall=%ds)", r.path, r.mem_mb, r.wall_seconds)
    result = sandbox.run(["python3", str(script)],
                         mem_mb=r.mem_mb,
                         cpu_seconds=min(r.wall_seconds, config.SANDBOX_CPU_SECONDS),
                         wall_seconds=r.wall_seconds,
                         cwd=str(config.WORKSPACE_DIR))
    for k in ("stdout", "stderr"):
        if len(result.get(k, "")) > config.MAX_OUTPUT_CHARS:
            result[k] = result[k][:config.MAX_OUTPUT_CHARS] + "\n...[truncated]"
    return result


# ---------------- WebSocket: chat ----------------

def _ws_authorized(ws: WebSocket) -> bool:
    if not config.AUTH_TOKEN:
        return True
    auth = ws.headers.get("authorization", "")
    # Browsers can't set headers on WebSocket; also accept ?token=
    token = ws.query_params.get("token", "")
    return auth == f"Bearer {config.AUTH_TOKEN}" or token == config.AUTH_TOKEN


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    if not _ws_authorized(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    current_cancel = None  # threading.Event for the in-flight generation

    async def run_prompt(msg: dict):
        nonlocal current_cancel
        prompt = workspace.expand_mentions((msg.get("prompt") or "").strip())
        budget = max(0, config.MAX_PROMPT_CHARS - len(prompt) - 500)
        for a in (msg.get("attachments") or [])[:8]:
            if budget <= 0:
                break
            name = str(a.get("name", "file"))[:120]
            content = str(a.get("content", ""))[:min(60000, budget)]
            budget -= len(content)
            if content:
                prompt += f"\n\n[attached file: {name}]\n{content}"
        if not prompt:
            return
        if len(prompt) > config.MAX_PROMPT_CHARS:
            await ws.send_json({"type": "error",
                                "content": f"prompt exceeds {config.MAX_PROMPT_CHARS} chars"})
            return
        session_id = str(msg.get("session_id", "default"))[:64]
        provider = msg.get("provider")
        system = msg.get("system")
        preferred_model = msg.get("model")

        loop = asyncio.get_event_loop()
        queue = asyncio.Queue()
        import threading
        cancel = threading.Event()
        current_cancel = cancel

        def producer():
            _act_start()
            try:
                gen = orchestrator.chat_stream(
                    prompt, session_id=session_id,
                    force_provider=provider, system=system,
                    preferred_model=preferred_model)
                for ev in gen:
                    if ev.get("type") == "meta":
                        _act_label(str(ev.get("model") or ev.get("provider") or "working"))
                    if cancel.is_set():
                        gen.close()  # propagates GeneratorExit -> closes httpx stream
                        loop.call_soon_threadsafe(
                            queue.put_nowait, {"type": "stopped"})
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, ev)
            except Exception as e:
                if cancel.is_set():
                    loop.call_soon_threadsafe(
                        queue.put_nowait, {"type": "stopped"})
                else:
                    log.exception("orchestrator error")
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        {"type": "error", "content": f"orchestrator crashed: {e}"})
            finally:
                _act_stop()
                loop.call_soon_threadsafe(queue.put_nowait, None)

        loop.run_in_executor(None, producer)

        async def _cancelled():
            while not cancel.is_set():
                await asyncio.sleep(0.1)
            return True

        try:
            while True:
                get_task = asyncio.ensure_future(queue.get())
                cancel_task = asyncio.ensure_future(_cancelled())
                done, pending = await asyncio.wait(
                    {get_task, cancel_task},
                    return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
                if cancel_task in done and get_task not in done:
                    # Cancelled while blocked inside the model stream:
                    # tell the client now; the producer thread finishes in
                    # the background and its events go nowhere.
                    try: await ws.send_json({"type": "stopped"})
                    except Exception: pass
                    break
                ev = get_task.result()
                if ev is None:
                    break
                try: await ws.send_json(ev)
                except Exception: break
        finally:
            current_cancel = None

    import asyncio as _aio
    from . import agent as _agent
    _loop = _aio.get_running_loop()
    def _perm_push(ev):
        try: _aio.run_coroutine_threadsafe(ws.send_json(ev), _loop)
        except Exception: pass
    _agent.PERM_EMIT = _perm_push
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "content": "invalid JSON"})
                continue
            if msg.get("type") == "stop":
                if current_cancel is not None:
                    current_cancel.set()
                    # Force-close in-flight HTTP streams so a blocked read
                    # unblocks immediately instead of waiting for next token.
                    ollama.abort_active_streams()
                continue
            if msg.get("type") == "perm":
                from . import agent as _agent
                _agent.resolve_perm(str(msg.get("id", "")), str(msg.get("choice", "never")))
                continue
            # Each prompt runs as its own task so 'stop' can arrive mid-run.
            asyncio.create_task(run_prompt(msg))
    except WebSocketDisconnect:
        pass
    finally:
        _agent.PERM_EMIT = None


@app.websocket("/ws/telemetry")
async def ws_telemetry(ws: WebSocket):
    if not _ws_authorized(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        while True:
            snap = await asyncio.get_event_loop().run_in_executor(None, telemetry.assess)
            await ws.send_json(snap)
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        pass
    finally:
        _agent.PERM_EMIT = None


# ---------------- Static frontend ----------------

@app.get("/")
def index():
    r = FileResponse(config.FRONTEND_DIR / "index.html")
    r.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return r


if (config.FRONTEND_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR / "static"), name="static")


# ---------------- Model pull (guide auto-download) ----------------
import subprocess as _sp
_pulls: dict = {}
_pull_prog: dict = {}
_pull_done: dict = {}


@app.post("/api/models/pull")
def pull_model(body: dict):
    name = str(body.get("name", "")).strip()[:120]
    if not name or ".." in name:
        return JSONResponse({"ok": False, "error": "invalid model name"}, status_code=400)
    if name in _pulls and _pulls[name].poll() is None:
        return {"ok": True, "already": True}
    def _run():
        p = _sp.Popen(["ollama", "pull", name],
                      stdout=_sp.PIPE, stderr=_sp.STDOUT, text=True, bufsize=1)
        _pulls[name] = p
        prog = _pull_prog.setdefault(name, {})
        for line in p.stdout:
            # ollama pull prints "pulling manifest" / "downloading <sha> XX%" lines
            import re as _re
            m = _re.search(r"(\d+)%", line)
            if m:
                prog["pct"] = int(m.group(1))
            if "download" in line.lower() or "pulling" in line.lower():
                prog["phase"] = line.strip()[:80]
            prog["ts"] = time.time()
        rc = p.wait()
        _pull_done[name] = rc
    _threading.Thread(target=_run, daemon=True).start()
    return {"ok": True}


@app.get("/api/models/pull_status")
def pull_status(name: str = ""):
    name = name[:120]
    p = _pulls.get(name)
    if name in _pull_done:
        return {"state": "done" if _pull_done[name] == 0 else "failed",
                "code": _pull_done[name]}
    if p is not None and p.poll() is None:
        pr = _pull_prog.get(name, {})
        return {"state": "running", "pct": pr.get("pct"),
                "phase": pr.get("phase"), "last_ts": pr.get("ts")}
    if p is not None:
        return {"state": "done" if p.returncode == 0 else "failed",
                "code": p.returncode}
    return {"state": "idle"}


@app.post("/api/auto")
def auto_cleanup():
    """Safe RAM cleanup: abort streams, unload idle models, free internal caches.
    Never touches user apps, sessions, or model files."""
    import gc
    aborted = ollama.abort_active_streams()
    unloaded = ollama.unload_all_models()
    gc.collect()
    return {"ok": True, "streams_aborted": aborted,
            "models_unloaded": unloaded, "safe": True}


@app.post("/api/media/run")
def media_run(req: dict):
    """Invoke a media_studio tool directly (lazy, no model load)."""
    tool = str(req.get("tool", ""))[:80]
    args = req.get("args") or {}
    if not (tool.startswith("media_studio.") or tool.startswith("persona_live.")):
        return {"ok": False, "error": "media/persona tools only"}
    registry.scan_modules()
    try:
        out = registry.call_tool(tool, args, timeout=180.0)
        return {"ok": True, "output": out[:8000]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


_MEDIA_KEYS = ["gemini_api_key", "vercel_ai_gateway_key", "freepik_api_key"]


@app.get("/api/media/keys")
def media_keys():
    return {k: bool(db.vault_get(k)) for k in _MEDIA_KEYS}


@app.post("/api/media/keys")
def media_keys_set(req: dict):
    k = str(req.get("key", ""))
    v = str(req.get("value", ""))[:500]
    if k not in _MEDIA_KEYS:
        return {"ok": False, "error": "unknown key"}
    if v:
        db.vault_set(k, v)
    else:
        db.vault_delete(k)
    return {"ok": True, "configured": bool(v)}
