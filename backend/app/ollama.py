"""Ollama local model client."""
import httpx

from . import config


def is_running(timeout: float = 1.5) -> bool:
    try:
        r = httpx.get(f"{config.OLLAMA_HOST}/api/version", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def list_models() -> list[dict]:
    if not is_running():
        return []
    try:
        r = httpx.get(f"{config.OLLAMA_HOST}/api/tags", timeout=5)
        return r.json().get("models", [])
    except Exception:
        return []


def model_names() -> list[str]:
    return [m.get("name", "") for m in list_models() if m.get("name")]


def model_details() -> list[dict]:
    """Installed models with human-readable details."""
    out = []
    for m in list_models():
        d = m.get("details") or {}
        out.append({
            "name": m.get("name", ""),
            "size_gb": round((m.get("size") or 0) / 1e9, 1),
            "quantization": d.get("quantization_level", ""),
            "parameter_size": d.get("parameter_size", ""),
            "family": d.get("family", ""),
            "modified_at": m.get("modified_at", ""),
        })
    return out


def resolve_model(name: str) -> str | None:
    """Match a user-supplied model name against installed models.

    Accepts exact name or prefix (e.g. 'qwen' matches 'qwen2.5-coder:7b').
    Returns the canonical installed name, or None if no match.
    """
    names = model_names()
    if name in names:
        return name
    base = name.split(":")[0]
    short = base.split("/")[-1]  # 'qwen2.5-coder-abliterate' from 'huihui_ai/qwen2.5...'
    for n in names:
        nbase = n.split(":")[0]
        nshort = nbase.split("/")[-1]
        if nbase == base or nshort == short or n.startswith(name) \
                or nshort.startswith(short) or short in nshort:
            return n
    return None


# Registry of in-flight streaming responses so a 'stop' request can abort
# the underlying HTTP read immediately (cancel flags alone can't interrupt
# a blocked socket read).
import threading as _threading
_active_responses: set = set()
_active_lock = _threading.Lock()


def unload_all_models() -> int:
    """Ask Ollama to unload every loaded model (keep_alive: 0)."""
    n = 0
    for m in list_models():
        name = m.get("name") or m.get("model")
        if not name:
            continue
        try:
            httpx.post(f"{config.OLLAMA_HOST}/api/generate",
                       json={"model": name, "keep_alive": 0},
                       timeout=httpx.Timeout(15.0, connect=3.0))
            n += 1
        except Exception:
            pass
    return n


def abort_active_streams() -> int:
    """Close all in-flight Ollama streams. Returns count aborted."""
    with _active_lock:
        rs = list(_active_responses)
    n = 0
    for r in rs:
        try:
            r.close()
            n += 1
        except Exception:
            pass
    return n


def generate_stream(model: str, prompt: str, system: str | None = None,
                    history: list[dict] | None = None, options: dict | None = None):
    """Yield text chunks from Ollama's /api/chat streaming endpoint."""
    import json

    messages = []
    eng = ("Always think, reason, and reply strictly in English only. Never use Chinese, Japanese, or any other language for thinking or output. "
           "Every assistant reply message must include at least one relevant emoji that matches the topic, tone, or meaning of that message. Keep it natural and sparse — one well-chosen emoji, never spammed word-by-word.")
    system = ((system + "\n" + eng) if system else eng)
    messages.append({"role": "system", "content": system})
    for m in (history or [])[-20:]:
        if m["role"] in ("user", "assistant"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": prompt})

    import os
    opts = {"num_ctx": 8192}
    opts.update(options or {})
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "keep_alive": "10m",  # unload from RAM ~10min after last use (lazy + low-RAM)
        "options": opts,
    }
    with httpx.stream("POST", f"{config.OLLAMA_HOST}/api/chat",
                      json=payload, timeout=httpx.Timeout(300.0, connect=5.0)) as r:
        r.raise_for_status()
        with _active_lock:
            _active_responses.add(r)
        try:
            for line in r.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                msg = chunk.get("message", {})
                think = msg.get("thinking") or ""
                if think:
                    yield f"<think>{think}</think>"
                text = msg.get("content", "")
                if text:
                    yield text
                if chunk.get("done"):
                    break
        finally:
            with _active_lock:
                _active_responses.discard(r)


def generate(model: str, prompt: str, system: str | None = None,
             history: list[dict] | None = None, options: dict | None = None) -> str:
    return "".join(generate_stream(model, prompt, system, history, options))


def show_model(model: str) -> dict | None:
    """Return model details (size, family) if present."""
    for m in list_models():
        if m.get("name") == model or m.get("model") == model:
            return m
    return None
