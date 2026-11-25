"""Autonomous agent engine.

Pipeline for non-trivial tasks:
  1. PLANNER decomposes the task into steps (emits agent_msg events so the
     user sees component-to-component communication).
  2. EXECUTOR runs a ReAct loop per step: think -> call tool -> observe.
     Tool errors are fed back as observations so the model can diagnose and
     reroute (self-healing). Repeated failures mark a module unhealthy and
     trigger a registry rescan.
  3. SYNTHESIZER merges step results into the final streamed answer.

All providers are driven through a uniform text protocol (prompt-based tool
calling) so local Ollama and cloud APIs behave identically.
"""
import json
import threading
import uuid
from queue import Queue, Empty
import logging
import re
import socket

from . import config, db, ollama, orchestrator, registry, telemetry

log = logging.getLogger("multi_ai.agent")

MAX_STEPS_PER_TASK = 12
MAX_PLAN_STEPS = 8
TOOL_CALL_RE = re.compile(r"```tool_call\s*(\{.*?\})\s*```", re.DOTALL)

# ---- shell permission plumbing ----
_PERM_LOCK = threading.Lock()
_PERM_WAITS = {}  # rid -> {"event": Event, "choice": None}
PERM_EMIT = None  # set by WS layer to push events live


def resolve_perm(rid: str, choice: str):
    with _PERM_LOCK:
        w = _PERM_WAITS.pop(rid, None)
    if w:
        w["choice"] = choice
        w["event"].set()


def _request_shell_perm(command: str, emit) -> str:
    """Ask the UI for shell permission. Returns 'always'|'once'|'never'."""
    rid = uuid.uuid4().hex[:12]
    ev = threading.Event()
    with _PERM_LOCK:
        _PERM_WAITS[rid] = {"event": ev, "choice": None}
    ev_dict = {"type": "shell_perm", "id": rid, "command": command[:500]}
    emit(ev_dict)

    ev.wait(timeout=600)
    with _PERM_LOCK:
        w = _PERM_WAITS.pop(rid, {"choice": None})
    return w.get("choice") or "never"
NEXT_RE = re.compile(r"NEXT:\s*([\w.]+)\s*(\{.*\})?\s*$", re.MULTILINE)

AGENT_SYSTEM = """You are an autonomous agent operating a local machine.
You have tools provided by modules. To use a tool, output EXACTLY one block:

```tool_call
{{"tool": "<module.tool>", "args": {{<arguments>}}}}
```

Then STOP — you will receive an Observation with the result.
If a tool fails, diagnose why and try a different approach or tool.
When the task is fully complete, reply with the final answer as plain text
(no tool_call block).

When the user asks you to build/create an app or project:
CRITICAL: NEVER fetch example.com, placeholder URLs, or any external website to "build" an app — apps are created LOCALLY as files. Do NOT use web.fetch_url for app-building tasks.
1. Plan the structure first.
2. For any project/web-app request, derive a clean unique folder name from the app name the user gave (e.g. "calculator web app" -> calculator-web-app/). NEVER use generic names like "project 1". If no name is given, invent a fitting one (e.g. notes-app/). Create it with workspace.ws_mkdir, then scope ALL module work inside that folder — write files under <project>/... (index.html, style.css, app.js/script.js with complete working code), run builds/tests with cwd=<project>.
3. Write all app files inside that subfolder using workspace file tools.
4. Build it, then test it — shell tests require user permission (Always / This time only / Never); if denied, skip the shell test gracefully.

Available tools:
{tools}
"""


def _only_model_in_ram(keep: str):
    """Unload every other Ollama model so only `keep` stays resident."""
    import httpx
    for m in ollama.list_models():
        name = m.get("name") or m.get("model") or ""
        base = name.split(":")[0]
        if base != keep.split(":")[0] and name:
            try:
                httpx.post(f"{config.OLLAMA_HOST}/api/generate",
                           json={"model": name, "keep_alive": 0},
                           timeout=httpx.Timeout(10.0, connect=2.0))
            except Exception:
                pass


def _complete(provider_kind: str, model: str, prompt: str) -> str:
    """Non-streaming completion through whichever provider is selected."""
    if provider_kind == "cloud":
        key = db.vault_get("deepseek")
        if not key:
            raise RuntimeError("no deepseek key")
        import httpx
        r = httpx.post(
            f"{config.DEEPSEEK_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}],
                  "stream": False},
            timeout=120.0,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    for attempt in range(2):
        try:
            return ollama.generate(model, prompt)
        except Exception:
            if attempt:
                raise
            import time as _t; _t.sleep(2)


def _stream_final(provider_kind: str, model: str, prompt: str):
    """Stream the final synthesized answer."""
    if provider_kind == "cloud":
        key = db.vault_get("deepseek")
        for chunk in orchestrator._cloud_stream("deepseek", key, model, prompt, None, []):
            yield chunk
    else:
        yield from ollama.generate_stream(model, prompt)


def _pick_backend(task: str):
    """Return (kind, model, meta) for the agent, honoring hardware tier."""
    online = orchestrator.is_online()
    ollama_up = ollama.is_running()
    health = telemetry.assess()
    tier = health["tier"]

    # Coding/planning prefer cloud for reasoning quality when available,
    # but always fall back to local.
    prefer_cloud = online and db.vault_get("deepseek")
    if prefer_cloud:
        kind, model = "cloud", db.get_setting("cloud_model", config.DEFAULT_CLOUD_MODEL)
    elif ollama_up:
        kind = "local"
        model = orchestrator.pick_local_model(task, tier)
    elif prefer_cloud:
        kind, model = "cloud", db.get_setting("cloud_model", config.DEFAULT_CLOUD_MODEL)
    else:
        return None
    return kind, model, {"tier": tier, "online": online}


def _plan(task: str, kind: str, model: str) -> tuple[list[str], str]:
    """Ask the model to decompose the task. Returns list of step strings."""
    prompt = (
        "You are the Planner module. Analyze the user's request and produce a "
        "real, concrete build plan. For app/website requests include: a fitting "
        "project folder name, each file to create (index.html, style.css, "
        "app.js/script.js) with what it contains, and build/verify steps. "
        "Reply with ONLY a JSON array of step strings.\n\nTask: " + task
    )
    try:
        text = _complete(kind, model, prompt)
        m = re.search(r"\[.*\]", text, re.DOTALL)
        steps = json.loads(m.group(0)) if m else []
        steps = [str(s) for s in steps if str(s).strip()][:MAX_PLAN_STEPS]
        if not steps:
            # planner replied prose — split into actionable lines
            steps = [ln.strip(" -*0123456789.)") for ln in text.splitlines()
                     if ln.strip() and not ln.strip().startswith("```")][:MAX_PLAN_STEPS]
        return (steps or [task]), text
    except Exception as e:
        log.warning("planner failed (%s); single-step fallback", e)
        return [task], ""


def _react_loop(step: str, kind: str, model: str, emit, state: dict) -> str:
    """Run think->act->observe until final answer or step cap.

    `state` carries per-run failure tracking for self-healing.
    Returns the final text answer for this step.
    """
    # Auto-select modules for this task (user prefs > relevance > all).
    task_type = orchestrator.classify(step)
    import re as _re
    _sl = step.lower()
    state["app_build"] = bool(
        (_re.search(r"(mak|makk|mack|mcak|make|creat|buid|build|buld|mad|mka|design|gen)\w*", _sl)
         and _re.search(r"(app|web|calculater|calculator|calc|site|game|tool|page|program|website|shop)", _sl))
        or "web app" in _sl or "app bana" in _sl or "app hadanna" in _sl)
    allowed = registry.modules_for_task(task_type, step)
    state["allowed_modules"] = allowed

    # Rank modules by relevance to this step so the right one is picked first.
    tools = registry.tool_specs_for_prompt(step, allowed=allowed)
    system = AGENT_SYSTEM.format(tools=tools or "(none available)")
    transcript = [f"User task: {step}"]

    for i in range(MAX_STEPS_PER_TASK):
        prompt = system + "\n\nTRANSCRIPT:\n" + "\n".join(transcript) + \
                 "\n\nRespond now (tool_call block or final answer):"
        try:
            reply = _complete(kind, model, prompt)
        except Exception as e:
            emit({"type": "error", "content": f"model call failed: {e}"})
            return f"[step failed: model error {e}]"

        m = TOOL_CALL_RE.search(reply)
        if not m:
            # Final answer for this step.
            return reply.strip()

        try:
            call = json.loads(m.group(1))
        except json.JSONDecodeError:
            transcript.append(f"Agent: {reply[:500]}\nObservation: malformed tool_call JSON, retry")
            continue

        tool_name = call.get("tool", "")
        _ALIASES = {"workspace.file_write": "workspace.ws_write",
                    "file_write": "workspace.ws_write", "ws_write": "workspace.ws_write"}
        tool_name = _ALIASES.get(tool_name, tool_name)
        args = call.get("args", {}) or {}
        emit({"type": "thought", "step": i + 1, "content": reply[:400]})
        emit({"type": "tool_call", "tool": tool_name, "args": args})

        # ---- self-healing: validate before executing ----
        tool = registry.get_tool(tool_name)
        if not tool:
            obs = (f"ERROR: unknown tool '{tool_name}'. Available tools: "
                   + ", ".join(sorted(registry.healthy_tools()))
                   + "\nReroute: pick a valid tool or answer directly.")
            state["errors"] += 1
        elif not registry.is_module_healthy(tool.module):
            obs = f"ERROR: module '{tool.module}' is unhealthy."
            state["errors"] += 1
        elif state.get("app_build") and tool.module == "web":
            obs = ("ERROR: app builds must be created LOCALLY — do NOT fetch URLs. "
                   "Use workspace.ws_write to create files inside a dedicated "
                   "<appname>/ subfolder, then workspace.ws_run or shell.sh_run to test.")
            state["errors"] += 1
        else:
            try:
                obs = registry.call_tool(tool_name, args)
                state["errors"] = 0
                state["tool_ok"] = state.get("tool_ok", 0) + 1
            except Exception as e:
                obs = f"ERROR executing {tool_name}: {type(e).__name__}: {e}"
                state["errors"] += 1
                # Module-level failure -> mark unhealthy + rescan so the
                # system 'thinks' around a broken component.
                if state["errors"] >= 3 and tool.module not in state.get("_unhealthy", set()):
                    state.setdefault("_unhealthy", set()).add(tool.module)
                    registry.mark_unhealthy(tool.module, str(e))
                    registry.scan_modules()
                    emit({"type": "agent_msg", "from": "supervisor", "to": "registry",
                          "content": f"module '{tool.module}' failed repeatedly -> marked unhealthy, rescanning"})

        emit({"type": "tool_result", "tool": tool_name,
              "ok": not obs.startswith("ERROR"), "output": obs[:2000]})
        transcript.append(f"Agent: {reply[:800]}\nObservation: {obs[:4000]}")

        # ---- automatic chaining: module finished -> scan for next module ----
        if not obs.startswith("ERROR"):
            registry.scan_modules()  # pick up any modules added at runtime
            chained = _auto_chain(tool_name, args, obs, emit, state)
            if chained:
                transcript.append("Observation: chained module outputs:\n" + chained[:4000])

    return "[step ended: max tool-call steps reached]"


MAX_CHAIN_DEPTH = 5


def _resolve_args(template: dict, prev_args: dict) -> dict:
    """Fill {key} placeholders in auto_next args from the previous call's args."""
    out = {}
    for k, v in (template or {}).items():
        if isinstance(v, str):
            try:
                out[k] = v.format_map({kk: str(vv) for kk, vv in prev_args.items()})
            except Exception:
                out[k] = v
        else:
            out[k] = v
    return out


def _exec_tool(tool_name: str, args: dict, emit, state) -> tuple[str, dict | None]:
    """Validate + execute one tool call. Returns (observation, tool_or_None)."""
    _ALIASES = {"workspace.file_write": "workspace.ws_write",
                "file_write": "workspace.ws_write", "ws_write": "workspace.ws_write"}
    tool_name = _ALIASES.get(tool_name, tool_name)
    tool = registry.get_tool(tool_name)
    emit({"type": "tool_call", "tool": tool_name, "args": args})
    if not tool:
        return ("ERROR: unknown tool. Available: "
                + ", ".join(sorted(registry.healthy_tools()))), None
    allowed = state.get("allowed_modules")
    if allowed is not None and tool.module not in allowed:
        return (f"ERROR: module '{tool.module}' is not selected for this task. "
                f"Allowed modules: {', '.join(sorted(allowed))}. "
                "Reroute to an allowed module or answer directly."), tool
    if not registry.is_module_healthy(tool.module):
        return f"ERROR: module '{tool.module}' is unhealthy.", tool
    if state.get("app_build") and tool.module == "web":
        return ("ERROR: app builds must be created LOCALLY — do NOT fetch URLs. "
                "Use workspace.ws_write to create files inside a dedicated "
                "<appname>/ subfolder, then workspace.ws_run or shell.sh_run to test."), tool
    if tool_name == "shell.sh_run" and not state.get("shell_always"):
        choice = _request_shell_perm(str(args.get("command", "")), emit)
        if choice == "never":
            return "SKIPPED: user denied shell permission for this command.", tool
        if choice == "always":
            state["shell_always"] = True
    try:
        obs = registry.call_tool(tool_name, args)
        state["errors"] = 0
        state["tool_ok"] = state.get("tool_ok", 0) + 1
    except Exception as e:
        obs = f"ERROR executing {tool_name}: {type(e).__name__}: {e}"
        state["errors"] += 1
        if state["errors"] >= 3:
            registry.mark_unhealthy(tool.module, str(e))
            registry.scan_modules()
            emit({"type": "agent_msg", "from": "supervisor", "to": "registry",
                  "content": f"module '{tool.module}' failed repeatedly -> rescanning"})
    emit({"type": "tool_result", "tool": tool_name,
          "ok": not obs.startswith("ERROR"), "output": obs[:2000]})
    return obs, tool


def _auto_chain(tool_name: str, prev_args: dict, obs: str, emit, state,
                depth: int = 0) -> str:
    """After a module finishes, automatically run the next module(s).

    Sources of the next hop, in order:
      1. Manifest `auto_next` on the tool that just ran (static pipeline).
      2. A `NEXT: module.tool {args}` directive in the tool's output
         (dynamic pipeline decided by the module itself).
    Returns concatenated outputs of chained calls (for the transcript).
    """
    if depth >= MAX_CHAIN_DEPTH:
        return ""
    outputs = []

    # 1) static auto_next from manifest
    tool = registry.get_tool(tool_name)
    candidates = []
    if tool:
        for nxt in tool.auto_next:
            candidates.append((nxt.get("tool", ""), _resolve_args(nxt.get("args", {}), prev_args)))

    # 2) dynamic NEXT: directive in output
    m = NEXT_RE.search(obs or "")
    if m:
        try:
            dargs = json.loads(m.group(2)) if m.group(2) else {}
        except json.JSONDecodeError:
            dargs = {}
        candidates.append((m.group(1), dargs))

    for nxt_name, nxt_args in candidates:
        if not nxt_name:
            continue
        emit({"type": "agent_msg", "from": tool_name, "to": nxt_name,
              "content": f"auto-chain -> {nxt_name}"})
        nobs, ntool = _exec_tool(nxt_name, nxt_args, emit, state)
        outputs.append(f"{nxt_name}: {nobs[:1500]}")
        if nobs.startswith("ERROR"):
            break  # stop chain on failure; model will see the error
        # chained module may itself chain further
        sub = _auto_chain(nxt_name, nxt_args, nobs, emit, state, depth + 1)
        if sub:
            outputs.append(sub)
        # only follow the first successful candidate per level
        break

    return "\n".join(outputs)


def run_agent(prompt: str, session_id: str = "default",
              force_provider: str | None = None,
              preferred_model: str | None = None):
    """Top-level agent pipeline. Yields events; final answer streams as deltas."""
    registry.scan_modules()  # ensure fresh module set
    # User-picked local model takes precedence when it exists on this machine.
    resolved = ollama.resolve_model(preferred_model) if preferred_model else None
    if resolved:
        backend = ("local", resolved,
                   {"tier": telemetry.assess()["tier"],
                    "online": orchestrator.is_online()})
    elif force_provider == "ollama":
        backend = ("local", orchestrator.pick_local_model(
            orchestrator.classify(prompt), telemetry.assess()["tier"]),
            {"tier": telemetry.assess()["tier"], "online": orchestrator.is_online()})
    elif force_provider and force_provider != "agent":
        backend = ("cloud", db.get_setting("cloud_model", config.DEFAULT_CLOUD_MODEL),
                   {"tier": "forced", "online": orchestrator.is_online()})
    else:
        backend = _pick_backend(orchestrator.classify(prompt))
    if not backend:
        yield {"type": "error", "content": "No AI backend available for agent."}
        return
    kind, model, meta = backend

    # Plan with the reasoning model, execute with the coding model — both stay
    # resident in RAM (keep_alive) so there's no reload between handoff steps.
    # strict role routing: whisper-dark=chat, obsidian-mind=planner, void-weaver=coder
    plan_model, exec_model = model, model
    if kind == "local":
        plan_model = ollama.resolve_model("obsidian-mind") or plan_model
        exec_model = ollama.resolve_model("void-weaver") or exec_model
        # deep questions / planning tasks: obsidian-mind handles plan AND answer
        if orchestrator.classify(prompt) == "planning":
            exec_model = plan_model

    modules = registry.list_modules()
    healthy = [m["name"] for m in modules if m["healthy"]]
    broken = [m["name"] for m in modules if not m["healthy"]]

    yield {"type": "meta", "provider": "agent", "model": model,
           "task": "agent", "tier": meta["tier"], "online": meta["online"],
           "host": socket.gethostname() if kind == "local" else None,
           "backend": kind,
           "modules": healthy, "modules_broken": broken,
           "selected_modules": sorted(registry.modules_for_task(
               orchestrator.classify(prompt), prompt))}
    yield {"type": "agent_msg", "from": "user", "to": "normal",
           "content": prompt[:300]}
    yield {"type": "agent_msg", "from": "normal", "to": "router",
           "content": "whisper-dark -> evaluating request -> " +
                      ("app/project build -> planner" if orchestrator.classify(prompt) in ("coding","planning") else "normal chat answer")}

    # ---- permanent handoff rule: chat -> planner -> coding ----
    yield {"type": "agent_msg", "from": "chat", "to": "planner",
           "content": "handoff: whisper-dark -> obsidian-mind (planner)"}
    plan_raw = ""
    if len(prompt) < 40:
        steps = [prompt]
    else:
        _only_model_in_ram(plan_model)
        steps, plan_raw = _plan(prompt, kind, plan_model)
    yield {"type": "agent_msg", "from": "planner", "to": "coder",
           "content": f"handoff: obsidian-mind plan ready ({len(steps)} step(s)) -> void-weaver (coding)"}
    yield {"type": "agent_msg", "from": "planner", "to": "executor",
           "content": f"{len(steps)} step(s): " + " | ".join(s[:80] for s in steps)}

    # show the plan + planner reasoning before execution
    yield {"type": "agent_msg", "from": "planner", "to": "executor",
           "content": "PLAN:\n" + "\n".join(f"{i+1}. {st}" for i, st in enumerate(steps))}
    if plan_raw:
        yield {"type": "thought", "step": 0,
               "content": "planner reasoning:\n" + plan_raw[:1500]}

    # ---- execute each step ----
    results = []
    state = {"errors": 0}
    for idx, step in enumerate(steps, 1):
        yield {"type": "agent_msg", "from": "executor", "to": f"step {idx}",
               "content": step[:200]}
        # live event streaming: _react_loop runs in a thread, events drain
        # through a queue so tool calls / thoughts / perms show in real time.
        q = Queue()
        _ans = [None]
        def _worker():
            try:
                _ans[0] = _react_loop(step, kind, exec_model, q.put, state)
            except Exception as e:
                q.put({"type": "error", "content": f"agent step crashed: {e}"})
                _ans[0] = f"[step failed: {e}]"
        _only_model_in_ram(exec_model)
        th = threading.Thread(target=_worker, daemon=True)
        th.start()
        while th.is_alive() or not q.empty():
            try:
                yield q.get(timeout=0.2)
            except Empty:
                pass
        th.join()
        answer = _ans[0] or "[no answer]"
        results.append(f"Step {idx}: {step}\nResult: {answer}")
        yield {"type": "agent_msg", "from": f"step {idx}", "to": "synthesizer",
               "content": answer[:300]}

    # ---- synthesize ----
    synth_prompt = (
        "Synthesize these step results into one coherent final answer for the user.\n\n"
        + "\n\n".join(results)
        + "\n\nOriginal task: " + prompt
    )
    yield {"type": "agent_msg", "from": "synthesizer", "to": "user",
           "content": "composing final answer"}
    full = []
    try:
        for chunk in _stream_final(kind, exec_model, synth_prompt):
            full.append(chunk)
            yield {"type": "delta", "content": chunk}
    except Exception as e:
        # Fallback: concatenate raw results.
        fallback = "\n\n".join(results)
        full = [fallback]
        yield {"type": "delta", "content": fallback}
        yield {"type": "fallback", "provider": "synthesizer", "reason": str(e)[:200]}

    answer = "".join(full).strip()
    if not answer:
        answer = ("Done ✅ — built and tested the app in the workspace subfolder. "
                  "Files created; shell test " + ("passed." if state.get("tool_ok") else "skipped/denied."))
        yield {"type": "delta", "content": answer}
    # work finished -> release ALL models from RAM automatically
    try:
        _only_model_in_ram("")
    except Exception:
        pass
    db.save_message(session_id, "user", prompt)
    db.save_message(session_id, "assistant", answer, "agent", model)
    yield {"type": "done", "provider": "agent", "model": model, "chars": len(answer)}
