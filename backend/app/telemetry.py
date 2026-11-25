"""Python wrapper around the C++ hwmon binary."""
import json
import subprocess

from . import config


def snapshot() -> dict:
    """One hardware telemetry snapshot."""
    if not config.HWMON_BIN.exists():
        return {"error": "hwmon binary not built", "gpus": []}
    out = subprocess.run(
        [str(config.HWMON_BIN), "--once"], capture_output=True, text=True, timeout=10
    )
    return json.loads(out.stdout.strip() or "{}")


def assess(snap: dict | None = None) -> dict:
    """Return stress assessment + recommended local model tier."""
    snap = snap or snapshot()
    cpu = snap.get("cpu_percent", 0)
    mem = snap.get("mem_percent", 0)
    gpu_mem_pct = 0.0
    gpu_util = 0.0
    for g in snap.get("gpus", []):
        total = g.get("mem_total_mb") or 0
        if total:
            gpu_mem_pct = max(gpu_mem_pct, 100.0 * g.get("mem_used_mb", 0) / total)
        gpu_util = max(gpu_util, g.get("util_percent", 0) or 0)

    # Decide which local model tier is safe to load.
    # small = 1-3B class, medium = 7-8B, large = 14B+
    if gpu_mem_pct >= config.GPU_VRAM_CRITICAL_PERCENT or mem >= config.RAM_WARN_PERCENT + 5:
        tier = "small"
    elif gpu_mem_pct >= config.GPU_VRAM_WARN_PERCENT or gpu_util >= 85 or cpu >= config.CPU_WARN_PERCENT:
        tier = "medium"
    else:
        tier = "large"

    return {
        "snapshot": snap,
        "tier": tier,
        "gpu_mem_percent": gpu_mem_pct,
        "gpu_util_percent": gpu_util,
        "warnings": [
            w for w, cond in [
                ("cpu_high", cpu >= config.CPU_WARN_PERCENT),
                ("ram_high", mem >= config.RAM_WARN_PERCENT),
                ("vram_high", gpu_mem_pct >= config.GPU_VRAM_WARN_PERCENT),
            ] if cond
        ],
    }
