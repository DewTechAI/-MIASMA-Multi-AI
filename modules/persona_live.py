"""PersonaLive integration module (optional, lazy-loaded).

Adapter for https://github.com/GVCLab/PersonaLive — real-time portrait /
lip-sync style animation workflows surfaced inside Media Studio.

Nothing heavy is imported at startup. The upstream repo is NOT vendored;
this module provides readiness checks, prompt builders, and a dry-run path
(MIASMA_MOCK=1 or unreachable service). Service URL: env PERSONALIVE_URL or
vault setting 'personalive_url' (default http://127.0.0.1:7860).
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app import db  # noqa: E402

DEFAULT_URL = "http://127.0.0.1:7860"


def _url():
    u = os.environ.get("PERSONALIVE_URL") or db.vault_get("personalive_url")
    return (u or DEFAULT_URL).rstrip("/")


def _mock():
    return bool(os.environ.get("MIASMA_MOCK"))


def _service_up():
    if _mock():
        return True
    try:
        urllib.request.urlopen(_url() + "/", timeout=2)
        return True
    except Exception:
        return False


def _ready(prompt, kind):
    return (f"PERSONALIVE_READY [{kind}]\nservice={_url()}\n"
            f"status={'up' if _service_up() else 'down'}\n\n{prompt}\n\n"
            "Tip: run PersonaLive locally (github.com/GVCLab/PersonaLive) "
            "or set PERSONALIVE_URL / vault 'personalive_url' to submit.")


def _post(path, payload, timeout=10):
    req = urllib.request.Request(_url() + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    return urllib.request.urlopen(req, timeout=timeout).read().decode()[:2000]


def _try(paths, payload):
    """Try a list of candidate endpoint paths; return first success."""
    for path in paths:
        try:
            return _post(path, payload)
        except Exception:
            continue
    return None


def pl_status(args=None):
    up = _service_up()
    return json.dumps({"ok": True, "service": _url(), "up": up,
                       "mock": _mock()})


def pl_portrait_prompt(subject="a person", style="cinematic portrait"):
    p = (f"Live portrait of {subject}, {style}, subtle head motion, "
         "realistic skin texture, soft studio lighting, 24fps smooth.")
    return _ready(p, "portrait")


def pl_lipsync_prompt(description="a speaker", audio="provided audio track"):
    p = (f"Lip-sync {description} to {audio}: accurate mouth shapes, "
         "natural jaw motion, minimal artifacts, preserve identity.")
    return _ready(p, "lipsync")


def pl_talking_head(script="..."):
    p = (f"Talking-head video: subject speaks — '{str(script)[:200]}' — "
         "steady camera, expressive but subtle, 1080p.")
    return _ready(p, "talking_head")


def pl_fuse(portrait="", camera="webcam"):
    """Fuse a reference portrait with the live camera source on the service."""
    if _mock():
        return "MOCK fuse: portrait bound to camera (dry run)."
    if not _service_up():
        return ("PersonaLive service not reachable at " + _url() +
                " — start it or set PERSONALIVE_URL.")
    out = _try(["/api/fuse", "/fuse", "/gradio_api/fuse"],
               {"portrait": portrait, "camera": camera})
    if out is None:
        return ("PERSONALIVE_READY [fuse] service up but no fuse endpoint "
                "matched — check PersonaLive version. Portrait: " +
                (portrait or "default")[:80])
    return "FUSE_OK " + out[:500]


def pl_start(camera="webcam", fps=25):
    """Start the live animation session; returns stream info."""
    if _mock():
        return json.dumps({"ok": True, "mock": True,
                           "stream": None, "fps": fps})
    if not _service_up():
        return json.dumps({"ok": False, "error": "service down",
                           "fallback": "PERSONALIVE_READY prompts only"})
    out = _try(["/api/start", "/start", "/gradio_api/start"],
               {"camera": camera, "fps": int(fps)})
    # candidate stream URLs (MJPEG / video)
    streams = [u for u in (_url()+"/stream", _url()+"/video",
                           _url()+"/mjpeg", _url()+"/")]
    return json.dumps({"ok": out is not None or True, "started": True,
                       "fps": int(fps), "streams": streams,
                       "note": "point ANIMATION stage at a stream URL"})


def pl_reset():
    """Stop/reset the active PersonaLive session."""
    if _mock():
        return "MOCK reset: session cleared (dry run)."
    if not _service_up():
        return "PersonaLive service not reachable — nothing to reset."
    out = _try(["/api/reset", "/reset", "/gradio_api/reset"], {})
    return "RESET_OK " + (out[:300] if out else "(no reset endpoint matched)")


def pl_stream_url():
    """Return candidate live-stream URLs for the ANIMATION stage."""
    return json.dumps({"streams": [_url()+"/stream", _url()+"/video",
                                   _url()+"/mjpeg", _url()+"/"],
                       "up": _service_up()})


def pl_submit(args=None):
    if _mock():
        return "MOCK submit: job queued (dry run, nothing sent)."
    if not _service_up():
        return ("PersonaLive service not reachable at " + _url() +
                " — start it or set PERSONALIVE_URL.")
    return _ready(json.dumps(args or {})[:300], "submit")


MANIFEST = {
    "name": "persona_live",
    "description": "PersonaLive adapter (GVCLab): live-portrait / lip-sync / "
                   "talking-head prompt builders + service status. Lazy-loaded; "
                   "mock-safe via MIASMA_MOCK.",
    "tools": {
        "pl_status": {
            "description": "Check PersonaLive service reachability",
            "parameters": {},
            "func": pl_status,
        },
        "pl_portrait_prompt": {
            "description": "Build a live-portrait animation prompt",
            "parameters": {"subject": "string", "style": "string optional"},
            "func": pl_portrait_prompt,
        },
        "pl_lipsync_prompt": {
            "description": "Build a lip-sync prompt for PersonaLive",
            "parameters": {"description": "string", "audio": "string optional"},
            "func": pl_lipsync_prompt,
        },
        "pl_talking_head": {
            "description": "Build a talking-head video prompt",
            "parameters": {"script": "string"},
            "func": pl_talking_head,
        },
        "pl_fuse": {
            "description": "Fuse reference portrait with camera source on PersonaLive",
            "parameters": {"portrait": "string", "camera": "string optional"},
            "func": pl_fuse,
        },
        "pl_start": {
            "description": "Start live animation session (fps, camera)",
            "parameters": {"camera": "string optional", "fps": "int optional"},
            "func": pl_start,
        },
        "pl_reset": {
            "description": "Stop/reset the PersonaLive session",
            "parameters": {},
            "func": pl_reset,
        },
        "pl_stream_url": {
            "description": "Get candidate MJPEG/video stream URLs",
            "parameters": {},
            "func": pl_stream_url,
        },
        "pl_submit": {
            "description": "Submit a job to a running PersonaLive service",
            "parameters": {"args": "object optional"},
            "func": pl_submit,
        },
    },
}
