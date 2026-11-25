"""Workspace file management. All paths are confined to WORKSPACE_DIR."""
import re
from pathlib import Path

from . import config, db


def roots() -> list[dict]:
    out = [{"name": "main", "path": str(config.WORKSPACE_DIR.resolve()), "custom": False}]
    for name, path in (db.get_setting("workspace_roots", {}) or {}).items():
        out.append({"name": name, "path": path, "custom": True})
    return out


def _root_path(name: str) -> Path:
    for r in roots():
        if r["name"] == name:
            return Path(r["path"]).resolve()
    raise ValueError(f"unknown workspace '{name}'")


def add_root(path: str) -> dict:
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise ValueError("path is not an existing directory")
    cfg = db.get_setting("workspace_roots", {}) or {}
    name, i = p.name or "root", 2
    while name in cfg or name == "main":
        name = f"{p.name}{i}"; i += 1
    cfg[name] = str(p)
    db.set_setting("workspace_roots", cfg)
    return {"name": name, "path": str(p)}


def remove_root(name: str):
    cfg = db.get_setting("workspace_roots", {}) or {}
    if name not in cfg:
        raise ValueError("not a custom workspace")
    del cfg[name]
    db.set_setting("workspace_roots", cfg)


def _resolve(rel: str) -> Path:
    """Resolve a workspace-relative path, refusing escapes.
    Custom roots are addressed as '+name/relpath'."""
    if rel.startswith("+"):
        name, _, rest = rel[1:].partition("/")
        root = _root_path(name)
        rel = rest
    else:
        root = config.WORKSPACE_DIR.resolve()
    p = (root / rel).resolve()
    if not str(p).startswith(str(root)):
        raise ValueError("path escapes workspace")
    return p


def tree(root: str | None = None) -> list[dict]:
    """Return workspace as a flat list of {path, type, size}."""
    if root:
        base = _root_path(root)
        prefix = f"+{root}/"
    else:
        base = config.WORKSPACE_DIR.resolve()
        prefix = ""
    base.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(base.rglob("*")):
        rel = prefix + str(p.relative_to(base))
        if p.is_dir():
            out.append({"path": rel + "/", "type": "dir", "size": 0})
        else:
            out.append({"path": rel, "type": "file", "size": p.stat().st_size})
    return out


def checkpoint_dir() -> Path:
    d = config.WORKSPACE_DIR / ".miasma" / "checkpoints"
    d.mkdir(parents=True, exist_ok=True)
    return d


def checkpoint_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:80] or "main"
    return checkpoint_dir() / f"{safe}.md"


def save_checkpoint(session_id: str, note: str) -> dict:
    p = checkpoint_path(session_id)
    p.write_text(note)
    return {"path": str(p.relative_to(config.WORKSPACE_DIR)), "size": len(note)}


def load_checkpoint(session_id: str) -> str | None:
    p = checkpoint_path(session_id)
    return p.read_text(errors="replace") if p.is_file() else None


def delete_checkpoint(session_id: str) -> bool:
    p = checkpoint_path(session_id)
    if p.is_file():
        p.unlink()
        return True
    return False


def expand_mentions(text: str, cap: int = 20000) -> str:
    """Expand @path / @+root/path mentions into attached file contents."""
    import re
    parts, used = [], 0
    for m in re.finditer(r"@([+\w][\w./-]*)", text):
        ref = m.group(1)
        try:
            content = read_file(ref)
        except Exception:
            continue
        if used + len(content) > cap:
            break
        used += len(content)
        parts.append(f"--- {ref} ---\n{content}")
    if not parts:
        return text
    return text + "\n\n[attached workspace files]\n" + "\n\n".join(parts)


def read_file(rel: str) -> str:
    return _resolve(rel).read_text(errors="replace")


def write_file(rel: str, content: str) -> dict:
    p = _resolve(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    db.index_file(rel, content)
    return {"path": rel, "size": len(content)}


def delete_file(rel: str) -> bool:
    p = _resolve(rel)
    if p.is_file():
        p.unlink()
        return True
    return False


def extract_code_blocks(text: str) -> list[dict]:
    """Pull fenced code blocks out of assistant output."""
    return [
        {"language": m.group(1) or "", "code": m.group(2)}
        for m in re.finditer(r"```(\w*)\n(.*?)```", text, re.DOTALL)
    ]
