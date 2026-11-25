"""AI Orchestrator & Auto-Router.

Decides which backend handles a prompt:
  - cloud APIs (DeepSeek via OpenAI-compatible endpoint) for complex reasoning,
    when a key exists and we're online
  - local Ollama for code/privacy/offline
Falls back cloud -> local automatically when offline or on API errors.
Picks a smaller local model when the hardware monitor reports stress.
"""
import json
import socket

import httpx

from . import config, db, ollama, telemetry


def is_online(timeout: float = 2.0) -> bool:
    try:
        httpx.get("https://api.deepseek.com", timeout=timeout)
        return True
    except Exception:
        try:
            httpx.get("https://www.google.com", timeout=timeout)
            return True
        except Exception:
            return False


def classify(prompt: str) -> str:
    """Heuristic task classification."""
    p = prompt.lower()
    code_words = ["code", "function", "script", "python", "debug", "implement",
                  "write a", "build", "scraper", "regex", "api", "sql", "bug",
                  "fetch", "download", "url", "http", "website", "file",
                  "workspace", "run", "execute", "module", "tool"]
    plan_words = ["plan", "architect", "design", "strategy", "roadmap", "step by step",
                  "deep", "analyze", "explain why", "pros and cons", "tradeoff",
                  "how does", "why does", "evaluate", "compare"]
    import re as _re
    # app-building requests (incl. typos) always route to the agent builder
    verbs = _re.search(r"(mak|makk|mack|mcak|make|creat|buid|build|buld|mad|mka|design|gen)\w*", p)
    targets = _re.search(r"(app|web|calculater|calculator|calc|site|game|tool|page|program|website)", p)
    if (verbs and targets) or "web app" in p or "app bana" in p or "app hadanna" in p:
        return "coding"
    if any(w in p for w in code_words):
        return "coding"
    if any(w in p for w in plan_words):
        return "planning"
    return "chat"


def pick_local_model(task: str, tier: str = "large") -> str:
    """Choose a local model based on task + hardware tier."""
    available = set(ollama.model_names())
    settings_model = db.get_setting("local_model")
    coding_model = db.get_setting("coding_model") or config.CODING_LOCAL_MODEL

    def resolve(preferred: str, fallback: str) -> str:
        # Ollama names may lack tags; match on prefix.
        for name in available:
            if name == preferred or name.split(":")[0] == preferred.split(":")[0]:
                return name
        # Preferred not installed: pick the closest sensible installed model.
        if available:
            if task == "coding":
                for name in available:
                    if any(k in name.lower() for k in ("coder", "code", "deepseek")):
                        return name
            for name in available:
                if any(t in name for t in ("7b", "8b", "14b")):
                    return name
            return sorted(available)[0]
        return preferred  # let Ollama error if truly missing

    if task == "coding":
        return resolve(coding_model, config.DEFAULT_LOCAL_MODEL)
    if task == "planning":
        return resolve(db.get_setting("reasoning_model") or config.REASONING_LOCAL_MODEL,
                       config.DEFAULT_LOCAL_MODEL)
    if tier == "small":
        # Prefer a tiny model under memory pressure.
        for name in available:
            if any(t in name for t in ("1b", "3b", "2b")):
                return name
        return resolve(config.FALLBACK_SMALL_MODEL, config.DEFAULT_LOCAL_MODEL)
    if tier == "medium":
        # Prefer the configured/default model; Ollama will page as needed.
        return resolve(settings_model or config.DEFAULT_LOCAL_MODEL,
                       config.FALLBACK_SMALL_MODEL)
    return resolve(settings_model or config.DEFAULT_LOCAL_MODEL, config.FALLBACK_SMALL_MODEL)


def _cloud_stream(provider: str, api_key: str, model: str, prompt: str,
                  system: str | None, history: list[dict]):
    """Stream from an OpenAI-compatible cloud API."""
    if provider == "deepseek":
        base = config.DEEPSEEK_BASE
    elif provider == "openai":
        base = config.EXTRA_PROVIDERS.get("openai")
    else:
        base = (db.get_setting("custom_providers", {}) or {}).get(provider, {}) \
            .get("base_url") or db.get_setting(f"{provider}_base")
    if not base:
        raise RuntimeError(f"no base url for provider {provider}")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    for m in (history or [])[-20:]:
        if m["role"] in ("user", "assistant"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": prompt})

    with httpx.stream(
        "POST", f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": messages, "stream": True},
        timeout=httpx.Timeout(120.0, connect=10.0),
    ) as r:
        r.raise_for_status()
        with ollama._active_lock:
            ollama._active_responses.add(r)
        try:
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0].get("delta", {}).get("content")
                except Exception:
                    continue
                if delta:
                    yield delta
        finally:
            with ollama._active_lock:
                ollama._active_responses.discard(r)


def _chat_stream_impl(prompt: str, session_id: str = "default",
                force_provider: str | None = None,
                system: str | None = None,
                preferred_model: str | None = None):
    """Main entry point. Yields events: dicts with type/content/provider/model."""
    task = classify(prompt)
    import re as _re2
    if _re2.search(r"(youer|your|ur)\s*name|whats?\s+(yo|ur|your)|who\s+(are|r)\s+you|who\s+(made|created|trained|owns)|your\s+(creator|owner|trainer)|what\s+are\s+you\s+called", prompt.lower()):
        ans = ("I'm just a **sub-module** of ᛗᛁᚨᛋᛗᚨ — part of this system, nothing more. "
               "I don't have my own name or creator to share. 🔧")
        yield {"type": "meta", "provider": "system", "model": "identity", "task": "identity"}
        yield {"type": "delta", "content": ans}
        yield {"type": "done", "provider": "system", "model": "identity", "chars": len(ans)}
        return

    # MOCK MODE (MIASMA_MOCK=1): canned responses, zero model loads — for tests only
    import os as _os
    if _os.environ.get("MIASMA_MOCK"):
        task_l = classify(prompt)
        yield {"type": "meta", "provider": "mock", "model": "mock-1b", "task": task_l, "tier": "mock", "online": False}
        if task_l in ("coding", "planning"):
            yield {"type": "agent_msg", "from": "normal", "to": "router", "content": "mock: routed to planner"}
            yield {"type": "agent_msg", "from": "planner", "to": "coder", "content": "mock: plan ready (3 steps)"}
            for i, st in enumerate(["create folder", "write files", "test"], 1):
                yield {"type": "agent_msg", "from": "executor", "to": f"step {i}", "content": st}
                yield {"type": "tool_call", "tool": "workspace.ws_write", "args": {"path": f"mock-app/f{i}.txt"}}
                yield {"type": "tool_result", "tool": "workspace.ws_write", "ok": True, "output": "mock: wrote file"}
            yield {"type": "delta", "content": "Mock build complete ✅ — folder + files saved (dry run, no models loaded)."}
        else:
            yield {"type": "delta", "content": "Mock reply: hello from the test environment 🧪"}
        yield {"type": "done", "provider": "mock", "model": "mock-1b", "chars": 10}
        return

    # Dedicated media workflow: image/video/lip-sync/cinema requests go
    # straight to the media_studio module — isolated from chat/planner/coder.
    import re as _rem
    _pl = prompt.lower()
    if _rem.search(r"(image|video|lip.?sync|cinema|shot list|photo|picture|render|generate (an? )?(image|video|pic))", _pl) \
       and _rem.search(r"(generat|creat|mak|buid|design|produc|render|draw|animat)", _pl):
        from . import agent as _ag, registry as _reg
        _ag.registry.scan_modules()
        yield {"type": "meta", "provider": "media_studio", "model": "media_studio",
               "task": "media", "tier": "media", "online": is_online()}
        yield {"type": "agent_msg", "from": "router", "to": "media_studio",
               "content": "media workflow: dedicated media_studio branch (chat/planner/coder bypassed)"}
        # choose tool by keywords
        tool, args = "media_studio.ms_image_prompt", {"subject": prompt}
        if "lip" in _pl or "sync" in _pl:
            tool, args = "media_studio.ms_lip_sync_prompt", {"video_desc": prompt}
        elif "video" in _pl or "animat" in _pl:
            tool, args = "media_studio.ms_video_prompt", {"subject": prompt}
        elif "shot" in _pl or "cinema" in _pl or "camera" in _pl or "lens" in _pl:
            tool, args = "media_studio.ms_shot_list", {"subject": prompt}
        yield {"type": "tool_call", "tool": tool, "args": args}
        try:
            out = _reg.call_tool(tool, args, timeout=180.0)
            yield {"type": "tool_result", "tool": tool, "ok": True, "output": out[:2000]}
            yield {"type": "delta", "content": out}
        except Exception as e:
            yield {"type": "tool_result", "tool": tool, "ok": False, "output": str(e)}
            yield {"type": "delta", "content": f"media workflow error: {e}"}
        ans = "Media workflow complete — see output above. 🎬"
        db.save_message(session_id, "user", prompt)
        db.save_message(session_id, "assistant", ans, "media_studio", "media_studio")
        yield {"type": "done", "provider": "media_studio", "model": "media_studio", "chars": len(ans)}
        return

    # Agentic path: coding/planning tasks (and explicit provider="agent")
    # go through the planner + tool-using ReAct loop.
    use_agent = force_provider == "agent" or (
        force_provider is None and task in ("coding", "planning"))
    if use_agent:
        from . import agent
        yield from agent.run_agent(prompt, session_id=session_id,
                                   force_provider=None if force_provider == "agent" else force_provider,
                                   preferred_model=preferred_model)
        return

    online = is_online()
    ollama_up = ollama.is_running()
    health = telemetry.assess()
    tier = health["tier"]
    history = db.get_history(session_id)

    # Decide provider order.
    providers = []
    if force_provider:
        providers = [("cloud" if force_provider != "ollama" else "local", force_provider)]
    else:
        # Coding always prefers local for privacy/cost; chat/planning prefer cloud if online+key.
        prefer_cloud = task != "coding" and online
        # Any stored cloud key can serve as provider (deepseek first, then others).
        custom = db.get_setting("custom_providers", {}) or {}
        cloud_keys = [p for p in ("deepseek", "openai") if db.vault_get(p)] \
            + [n for n in custom if db.vault_get(n)]
        key = db.vault_get(cloud_keys[0]) if (prefer_cloud and cloud_keys) else None
        if key:
            providers.extend(("cloud", p) for p in cloud_keys)
        if ollama_up:
            providers.append(("local", pick_local_model(task, tier)))
        elif key and online:
            providers.extend(("cloud", p) for p in cloud_keys)
        else:
            yield {"type": "error", "content": "No AI backend available: Ollama is not running "
                   "and no cloud API key is configured."}
            return

    last_error = None
    for kind, target in providers:
        provider_name = target if kind == "cloud" else "ollama"
        if kind == "cloud":
            _cp = (db.get_setting("custom_providers", {}) or {}).get(target, {})
            model = _cp.get("model") or db.get_setting("cloud_model", config.DEFAULT_CLOUD_MODEL)
        else:
            model = (ollama.resolve_model(preferred_model) if preferred_model else None) \
                 or pick_local_model(task, tier)
        yield {"type": "meta", "provider": provider_name, "model": model, "task": task,
               "tier": tier, "online": online,
               "host": socket.gethostname() if provider_name == "ollama" else None}
        try:
            buf = []
            eng_system = ((system + "\n" if system else "") +
                          "Always think, reason, and reply in English only.")
            if kind == "cloud":
                key = db.vault_get(provider_name)
                gen = _cloud_stream(provider_name, key, model, prompt, eng_system, history)
            else:
                gen = ollama.generate_stream(model, prompt, eng_system, history)
            for chunk in gen:
                buf.append(chunk)
                yield {"type": "delta", "content": chunk}
            full = "".join(buf)
            db.save_message(session_id, "user", prompt)
            db.save_message(session_id, "assistant", full, provider_name, model)
            yield {"type": "done", "provider": provider_name, "model": model,
                   "chars": len(full)}
            return
        except Exception as e:  # fallback to next provider
            last_error = e
            yield {"type": "fallback", "provider": provider_name,
                   "reason": str(e)[:200]}
            continue

    yield {"type": "error",
           "content": f"All providers failed. Last error: {last_error}"}


_GEN_SEM = __import__("threading").BoundedSemaphore(2)


def chat_stream(prompt: str, session_id: str = "default",
                force_provider: str | None = None,
                system: str | None = None,
                preferred_model: str | None = None):
    """Concurrency-capped wrapper: at most 2 model executions at once.
    Bounded wait so an orphaned producer can't hang the new turn forever."""
    if not _GEN_SEM.acquire(timeout=90):
        yield {"type": "error",
               "content": "System busy — a previous generation is still finishing. Try again shortly."}
        return
    try:
        yield from _chat_stream_impl(prompt, session_id, force_provider,
                                     system, preferred_model)
    finally:
        _GEN_SEM.release()


def status() -> dict:
    online = is_online()
    ollama_up = ollama.is_running()
    models = ollama.model_names() if ollama_up else []
    return {
        "online": online,
        "host": socket.gethostname(),
        "ollama": {"running": ollama_up, "host": config.OLLAMA_HOST, "models": models},
        "cloud_keys": db.vault_list(),
        "hardware": telemetry.assess(),
    }
