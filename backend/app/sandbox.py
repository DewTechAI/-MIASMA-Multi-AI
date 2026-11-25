"""Wrapper around the C++ sandbox_exec binary."""
import json
import subprocess

from . import config


def run(argv: list[str], mem_mb: int = 512, cpu_seconds: int = 30,
        wall_seconds: int = 60, cwd: str | None = None) -> dict:
    """Run a command in the C++ sandbox. Returns parsed JSON result."""
    if not config.SANDBOX_BIN.exists():
        return {"exit_code": -1, "stderr": "sandbox_exec not built",
                "stdout": "", "timed_out": False, "mem_killed": False,
                "peak_rss_mb": 0}
    cmd = [str(config.SANDBOX_BIN),
           "--mem-mb", str(mem_mb),
           "--cpu-seconds", str(cpu_seconds),
           "--wall-seconds", str(wall_seconds),
           "--"] + argv
    out = subprocess.run(cmd, capture_output=True, text=True,
                         timeout=wall_seconds + 15, cwd=cwd)
    try:
        return json.loads(out.stdout.strip())
    except json.JSONDecodeError:
        return {"exit_code": -1, "stderr": out.stderr or out.stdout,
                "stdout": "", "timed_out": False, "mem_killed": False,
                "peak_rss_mb": 0}


def run_python(script_path: str, mem_mb: int = 512, wall_seconds: int = 60,
               cwd: str | None = None) -> dict:
    """Run a workspace python file inside the sandbox."""
    return run(["python3", script_path], mem_mb=mem_mb,
               cpu_seconds=wall_seconds, wall_seconds=wall_seconds, cwd=cwd)
