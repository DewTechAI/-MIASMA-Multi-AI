"""Module registry: auto-discovers and loads plugin modules.

A module is a Python file in MODULES_DIR containing a MANIFEST dict:

    MANIFEST = {
        "name": "web",
        "description": "Fetch web pages",
        "tools": {
            "fetch_url": {
                "description": "GET a URL and return its text",
                "parameters": {"url": "string", "...": "..."},   # loose schema
                "func": fetch_url,                              # callable(**args) -> str
            },
        },
    }

Tools are exposed to the agent as `module.tool`. Failed modules are marked
unhealthy and their tools excluded, but a rescan can recover them.
"""
import importlib.util
import json
import logging
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import config, db

log = logging.getLogger("multi_ai.modules")

MODULES_DIR = config.ROOT / "modules"


@dataclass
class Tool:
    name: str            # "module.tool"
    module: str
    description: str
    parameters: dict
    func: Callable
    auto_next: list = field(default_factory=list)  # [{"tool":..., "args":{...}}]


@dataclass
class ModuleInfo:
    name: str
    description: str
    path: str
    tools: list[str] = field(default_factory=list)
    healthy: bool = True
    error: str = ""
    loaded_at: float = 0.0


_registry: dict[str, ModuleInfo] = {}
_tools: dict[str, Tool] = {}
_lock = threading.Lock()


def _load_file(path: Path) -> tuple[str, dict]:
    # Ensure backend package is importable from plugin modules.
    backend_dir = str(config.ROOT / "backend")
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    spec = importlib.util.spec_from_file_location(f"mai_mod_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    manifest = getattr(mod, "MANIFEST", None)
    if not isinstance(manifest, dict) or "name" not in manifest or "tools" not in manifest:
        raise ValueError("missing MANIFEST with name/tools")
    return manifest["name"], manifest


def scan_modules() -> dict:
    """(Re)scan MODULES_DIR. Returns {name: ModuleInfo}."""
    global _registry, _tools
    MODULES_DIR.mkdir(parents=True, exist_ok=True)
    new_registry: dict[str, ModuleInfo] = {}
    new_tools: dict[str, Tool] = {}

    for path in sorted(MODULES_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            name, manifest = _load_file(path)
            info = ModuleInfo(
                name=name,
                description=manifest.get("description", ""),
                path=str(path),
                loaded_at=time.time(),
            )
            for tname, tdef in manifest["tools"].items():
                func = tdef.get("func")
                if not callable(func):
                    raise ValueError(f"tool '{tname}' has no callable func")
                full = f"{name}.{tname}"
                new_tools[full] = Tool(
                    name=full, module=name,
                    description=tdef.get("description", ""),
                    parameters=tdef.get("parameters", {}),
                    func=func,
                    auto_next=tdef.get("auto_next", []) or [],
                )
                info.tools.append(full)
            new_registry[name] = info
            log.info("module loaded: %s (%d tools) from %s", name, len(info.tools), path.name)
        except Exception as e:
            # A broken module must not take down the system.
            mname = path.stem
            new_registry[mname] = ModuleInfo(
                name=mname, description="(failed to load)", path=str(path),
                healthy=False, error=str(e)[:300],
            )
            log.error("module failed: %s -> %s", path.name, e)

    with _lock:
        _registry, _tools = new_registry, new_tools
    return {k: v.__dict__ | {"tools": list(v.tools)} for k, v in _registry.items()}


def list_modules() -> list[dict]:
    with _lock:
        return [
            {"name": m.name, "description": m.description, "path": m.path,
             "tools": list(m.tools), "healthy": m.healthy, "error": m.error,
             "loaded_at": m.loaded_at}
            for m in _registry.values()
        ]


def get_tool(name: str) -> Tool | None:
    with _lock:
        return _tools.get(name)


def healthy_tools() -> dict[str, Tool]:
    with _lock:
        return {n: t for n, t in _tools.items()
                if _registry.get(t.module) and _registry[t.module].healthy}


def call_tool(name: str, args: dict, timeout: float = 60.0) -> str:
    """Execute a tool. Returns string output or raises."""
    tool = get_tool(name)
    if not tool:
        raise KeyError(f"unknown tool '{name}'")
    mod = _registry.get(tool.module)
    if not mod or not mod.healthy:
        raise RuntimeError(f"module '{tool.module}' is unhealthy: {mod.error if mod else '?'}")
    result = tool.func(**(args or {}))
    if not isinstance(result, str):
        result = json.dumps(result, default=str)
    return result[: config.MAX_OUTPUT_CHARS]


def is_module_healthy(module: str) -> bool:
    with _lock:
        m = _registry.get(module)
        return bool(m and m.healthy)


def mark_unhealthy(module: str, error: str) -> None:
    with _lock:
        if module in _registry:
            _registry[module].healthy = False
            _registry[module].error = error[:300]
            log.warning("module %s marked unhealthy: %s", module, error)


# Task -> module relevance aliases used for auto-selection.
_TASK_ALIASES = {
    "chat": set(),
    "coding": {"file", "files", "workspace", "script", "code", "python",
               "run", "write", "read", "save", "edit", "debug", "implement"},
    "planning": {"plan", "design", "architect", "strategy", "research",
                 "analyze", "compare"},
}
_MODULE_ALIASES = {
    "web": {"fetch", "download", "http", "https", "url", "site", "page",
            "scrape", "browse", "website", "api", "research", "search"},
    "workspace": {"file", "files", "workspace", "script", "code", "python",
                  "run", "write", "read", "save", "edit", "debug"},
}


def _module_score(module: str, description: str, prompt: str) -> int:
    words = set(re.findall(r"[a-z]{3,}", prompt.lower()))
    text = (module + " " + description).lower()
    s = sum(2 for w in words if w in text)
    kws = _MODULE_ALIASES.get(module, set())
    if words & kws:
        s += 6
    # task-type affinity
    for task, kws2 in _TASK_ALIASES.items():
        if words & kws2 and module in ("workspace" if task == "coding" else "web"):
            s += 3
    return s


def modules_for_task(task: str, prompt: str = "") -> set[str]:
    """Which modules should handle this task.

    Priority: explicit user prefs (settings `module_prefs`) > auto-selection
    by prompt relevance > all healthy modules.
    """
    prefs = db.get_setting("module_prefs", {}) or {}
    chosen = prefs.get(task) or prefs.get("default")
    healthy_names = {m.name for m in _registry.values() if m.healthy}
    if chosen:
        sel = {m for m in chosen if m in healthy_names}
        if sel:
            return sel
    # auto-select: modules with relevance score > 0
    scores = {}
    for name, m in _registry.items():
        if not m.healthy:
            continue
        scores[name] = _module_score(name, m.description, prompt or task)
    sel = {n for n, s in scores.items() if s > 0}
    return sel or healthy_names


def tool_specs_for_prompt(user_prompt: str = "", allowed: set[str] | None = None) -> str:
    """Human-readable tool listing for the system prompt.

    `allowed` restricts to tools of selected modules; remaining tools are
    ranked by keyword relevance so the model sees the best first.
    """
    tools = sorted(healthy_tools().items())
    if allowed is not None:
        tools = [(n, t) for n, t in tools if t.module in allowed]
    if user_prompt:
        words = set(re.findall(r"[a-z]{3,}", user_prompt.lower()))
        # module-name aliases that map common task words to modules
        aliases = {"web": {"fetch", "download", "http", "https", "url", "site",
                           "page", "scrape", "browse", "website", "api"},
                   "workspace": {"file", "files", "workspace", "script", "code",
                                 "python", "run", "write", "read", "save", "edit"}}
        def score(item):
            name, t = item
            s = 0
            text = (name + " " + t.description + " " + " ".join(t.parameters)).lower()
            for w in words:
                if w in text:
                    s += 2
            for mod, kws in aliases.items():
                if mod in name and words & kws:
                    s += 5
            return -s
        tools = sorted(tools, key=score)
    lines = []
    for name, t in tools:
        params = ", ".join(f"{k}: {v}" for k, v in t.parameters.items()) or "none"
        lines.append(f"- {name}({params}) — {t.description}")
    return "\n".join(lines)
