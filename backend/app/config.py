"""Central configuration. All values overridable via environment variables
or a .env file in the project root (KEY=VALUE per line)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.environ.get("MULTI_AI_DATA_DIR", ROOT / "data"))
WORKSPACE_DIR = Path(os.environ.get("MULTI_AI_WORKSPACE_DIR", ROOT / "workspace"))
FRONTEND_DIR = ROOT / "frontend"
BIN_DIR = ROOT / "cpp" / "build"
HWMON_BIN = BIN_DIR / "hwmon"
SANDBOX_BIN = BIN_DIR / "sandbox_exec"
DB_PATH = DATA_DIR / "multi_ai.db"
VAULT_KEY_PATH = DATA_DIR / ".vault_key"

# ---- server ----
HOST = os.environ.get("MULTI_AI_HOST", "127.0.0.1")
PORT = int(os.environ.get("MULTI_AI_PORT", "8000"))
# Bearer token required on /api/* and /ws/* when set. Empty = open (localhost only).
AUTH_TOKEN = os.environ.get("MULTI_AI_AUTH_TOKEN", "")
CORS_ORIGINS = [o.strip() for o in os.environ.get(
    "MULTI_AI_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()]

# ---- backends ----
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE", "https://api.deepseek.com")
# Optional OpenAI-compatible providers: name -> base url env override
EXTRA_PROVIDERS = {
    "openai": os.environ.get("OPENAI_BASE", "https://api.openai.com/v1"),
}

# ---- hardware stress thresholds ----
GPU_VRAM_WARN_PERCENT = float(os.environ.get("GPU_VRAM_WARN_PERCENT", "80"))
GPU_VRAM_CRITICAL_PERCENT = float(os.environ.get("GPU_VRAM_CRITICAL_PERCENT", "90"))
RAM_WARN_PERCENT = float(os.environ.get("RAM_WARN_PERCENT", "85"))
CPU_WARN_PERCENT = float(os.environ.get("CPU_WARN_PERCENT", "90"))

# ---- model defaults ----
# Renamed local models on this machine:
#   void-weaver   = qwen2.5-coder (coding)
#   obsidian-mind = deepseek-r1   (reasoning/planning)
#   whisper-dark  = llama3        (general chat)
DEFAULT_CLOUD_MODEL = os.environ.get("CLOUD_MODEL", "deepseek-chat")
DEFAULT_LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "whisper-dark")
CODING_LOCAL_MODEL = os.environ.get("CODING_MODEL", "void-weaver")
REASONING_LOCAL_MODEL = os.environ.get("REASONING_MODEL", "obsidian-mind")
FALLBACK_SMALL_MODEL = os.environ.get("FALLBACK_MODEL", "whisper-dark")

# ---- sandbox limits ----
SANDBOX_MEM_MB = int(os.environ.get("SANDBOX_MEM_MB", "512"))
SANDBOX_CPU_SECONDS = int(os.environ.get("SANDBOX_CPU_SECONDS", "30"))
SANDBOX_WALL_SECONDS = int(os.environ.get("SANDBOX_WALL_SECONDS", "60"))
MAX_OUTPUT_CHARS = int(os.environ.get("MAX_OUTPUT_CHARS", "200_000"))

# ---- request limits ----
MAX_PROMPT_CHARS = int(os.environ.get("MAX_PROMPT_CHARS", "32_000"))
MAX_FILE_BYTES = int(os.environ.get("MAX_FILE_BYTES", "1_000_000"))
