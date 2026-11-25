"""Workspace module: file ops + sandboxed code execution.

Exposes the ./workspace directory to the agent. All file paths are relative
to the workspace root and cannot escape it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import config, sandbox, workspace  # noqa: E402


def ws_list() -> str:
    """List files in the workspace."""
    return "\n".join(
        f"{f['path']}  ({f['type']}, {f['size']}B)" for f in workspace.tree()
    ) or "(empty workspace)"


def ws_read(path: str) -> str:
    """Read a workspace file."""
    return workspace.read_file(path)


def ws_write(path: str, content: str) -> str:
    """Write (create/overwrite) a workspace file."""
    info = workspace.write_file(path, content)
    return f"wrote {info['size']} bytes to {info['path']}"


def ws_run(path: str = "", command: str = "", mem_mb: int = 512,
           wall_seconds: int = 60, cwd: str = "") -> str:
    """Run a Python file or shell command inside the C++ sandbox.

    Provide either `path` (a workspace .py file) or `command` (argv string,
    split on whitespace — keep it simple, no shell metacharacters).
    """
    run_cwd = config.WORKSPACE_DIR
    if cwd:
        c = (config.WORKSPACE_DIR / cwd)
        c.resolve().relative_to(config.WORKSPACE_DIR.resolve())
        run_cwd = c if c.is_dir() else config.WORKSPACE_DIR
    if path:
        script = config.WORKSPACE_DIR / path
        try:
            script.resolve().relative_to(config.WORKSPACE_DIR.resolve())
        except Exception:
            return "error: path escapes workspace"
        result = sandbox.run(["python3", str(script)], mem_mb=mem_mb,
                             wall_seconds=wall_seconds, cwd=str(run_cwd))
    elif command:
        argv = command.split()
        result = sandbox.run(argv, mem_mb=mem_mb, wall_seconds=wall_seconds,
                             cwd=str(run_cwd))
    else:
        return "error: provide 'path' or 'command'"

    out = f"exit={result['exit_code']} peak_rss={result['peak_rss_mb']}MB"
    if result.get("timed_out"):
        out += " TIMED_OUT"
    if result.get("mem_killed"):
        out += " MEM_KILLED"
    out += f"\n--- stdout ---\n{result.get('stdout','')}\n--- stderr ---\n{result.get('stderr','')}"
    return out[: config.MAX_OUTPUT_CHARS]


def ws_mkdir(path: str = "", folder_name: str = "", name: str = "") -> str:
    """Create a directory (project folder) inside the workspace.
    Accepts path / folder_name / name / positional."""
    path = path or folder_name or name
    if not path:
        return "error: provide a folder name"
    d = config.WORKSPACE_DIR / path
    d.resolve().relative_to(config.WORKSPACE_DIR.resolve())
    d.mkdir(parents=True, exist_ok=True)
    return f"created folder {path}/"


def ws_scaffold(path: str, content: str) -> str:
    """Write a Python file; the manifest auto_next then runs it in the
    sandbox automatically — no second model round-trip needed."""
    return ws_write(path, content)


MANIFEST = {
    "name": "workspace",
    "description": "Read/write files and run code in the local workspace sandbox",
    "tools": {
        "ws_list": {
            "description": "List files in the workspace",
            "parameters": {},
            "func": ws_list,
        },
        "ws_read": {
            "description": "Read a file from the workspace",
            "parameters": {"path": "string (required)"},
            "func": ws_read,
        },
        "ws_write": {
            "description": "Write content to a file in the workspace",
            "parameters": {"path": "string (required)", "content": "string (required)"},
            "func": ws_write,
        },
        "ws_run": {
            "description": "Execute Python code or a command in the sandboxed workspace",
            "parameters": {
                "path": "string (workspace .py file, optional)",
                "command": "string (argv, optional)",
                "mem_mb": "int optional (default 512)",
                "wall_seconds": "int optional (default 60)",
                "cwd": "string optional (subfolder inside workspace)",
            },
            "func": ws_run,
        },
        "ws_mkdir": {
            "description": "Create a project folder inside the workspace",
            "parameters": {"path": "string (required, e.g. my-app)"},
            "func": ws_mkdir,
        },
        "ws_scaffold": {
            "description": "Write a Python file then AUTO-RUN it in the sandbox (chained)",
            "parameters": {
                "path": "string (required, e.g. script.py)",
                "content": "string (required, Python source)",
            },
            "func": ws_scaffold,
            "auto_next": [
                {"tool": "workspace.ws_run", "args": {"path": "{path}"}},
            ],
        },
    },
}
