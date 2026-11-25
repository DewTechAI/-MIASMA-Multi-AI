"""Shell module: run shell commands in the workspace (permission-gated)."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app import config  # noqa: E402


def sh_run(command: str, timeout: int = 120) -> str:
    """Run a shell command inside the workspace directory."""
    try:
        r = subprocess.run(command, shell=True, cwd=str(config.WORKSPACE_DIR),
                           capture_output=True, text=True, timeout=min(timeout, 300))
        out = f"exit={r.returncode}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"
        return out[: config.MAX_OUTPUT_CHARS]
    except subprocess.TimeoutExpired:
        return "error: command timed out"
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"


MANIFEST = {
    "name": "shell",
    "description": "Run shell commands inside the workspace (requires user permission)",
    "tools": {
        "sh_run": {
            "description": "Run a shell command (e.g. tests, builds) in the workspace folder",
            "parameters": {"command": "string (required)", "timeout": "int optional (default 120)"},
            "func": sh_run,
        },
    },
}
