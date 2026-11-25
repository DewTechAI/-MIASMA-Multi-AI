"""Media & Cinema Studio module (optional, lazy-loaded).

Higgsfield-style workflows: image prompts, video prompts, lip-sync prompts,
and cinema shot lists (camera angle / lens / product-animation style).

Nothing heavy is loaded unless a tool is actually invoked. External
generation is only attempted when an API key is configured via the
GEMINI_API_KEY / VERCEL_AI_GATEWAY_KEY / FREEPIK_API_KEY / MEDIA_API_KEY (env or vault).
Without a key, tools return ready-to-use structured prompts.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app import db  # noqa: E402

CAMERA_ANGLES = ["eye-level", "low-angle hero", "high-angle top-down",
                 "dutch tilt", "over-the-shoulder", "macro close-up",
                 "wide establishing", "tracking side-shot", "crane reveal"]
LENSES = ["35mm cinematic", "50mm portrait", "85mm product macro",
          "24mm wide", "anamorphic 2.39:1", "tilt-shift miniature"]
LIGHTING = ["soft studio softbox", "golden hour rim light", "neon noir",
            "high-key clean", "low-key dramatic", "volumetric haze"]


# Provider keys (open-higgsfield style): env vars or vault settings.
# Supported: GEMINI_API_KEY, VERCEL_AI_GATEWAY_KEY, FREEPIK_API_KEY, MEDIA_API_KEY.
def _env(*names):
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    for n in names:
        v = db.vault_get(n.lower())
        if v:
            return v
    return ""


def _provider():
    """Pick first configured provider: vercel gateway > gemini > freepik > generic."""
    if _env("VERCEL_AI_GATEWAY_KEY", "vercel_ai_gateway_key"):
        return "vercel"
    if _env("GEMINI_API_KEY", "gemini_api_key"):
        return "gemini"
    if _env("FREEPIK_API_KEY", "freepik_api_key"):
        return "freepik"
    if _env("MEDIA_API_KEY", "media_api"):
        return "generic"
    return None


def _maybe_submit(prompt: str, kind: str) -> str:
    prov = _provider()
    if not prov:
        return ("NO_API_KEY — structured prompt ready. Set one of "
                "GEMINI_API_KEY / VERCEL_AI_GATEWAY_KEY / FREEPIK_API_KEY "
                "(env or vault) to auto-submit.\n" + prompt)
    try:
        import httpx
        if prov == "gemini":
            key = _env("GEMINI_API_KEY", "gemini_api_key")
            model = "gemini-2.0-flash-preview-image-generation" if kind == "image" else "veo-3.1-fast-generate-preview"
            r = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
                json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=180.0)
            r.raise_for_status()
            return "GEMINI SUBMITTED: " + r.text[:2000]
        if prov == "vercel":
            key = _env("VERCEL_AI_GATEWAY_KEY", "vercel_ai_gateway_key")
            r = httpx.post("https://ai-gateway.vercel.sh/v1/images/generations",
                           headers={"Authorization": f"Bearer {key}"},
                           json={"prompt": prompt, "model": "openai/gpt-image-1"},
                           timeout=180.0)
            r.raise_for_status()
            return "VERCEL GATEWAY SUBMITTED: " + r.text[:2000]
        if prov == "freepik":
            key = _env("FREEPIK_API_KEY", "freepik_api_key")
            r = httpx.post("https://api.freepik.com/v1/ai/image",
                           headers={"x-freepik-api-key": key},
                           json={"prompt": prompt}, timeout=180.0)
            r.raise_for_status()
            return "FREEPIK SUBMITTED: " + r.text[:2000]
        key = _env("MEDIA_API_KEY", "media_api")
        url = os.environ.get("MEDIA_API_URL", "https://api.example.com/v1/generate")
        r = httpx.post(url, headers={"Authorization": f"Bearer {key}"},
                       json={"prompt": prompt, "kind": kind}, timeout=120.0)
        r.raise_for_status()
        return "SUBMITTED: " + r.text[:2000]
    except Exception as e:
        return f"submit failed ({e}); prompt was:\n{prompt}"


def ms_shot_list(subject: str, style: str = "product ad", count: int = 4) -> str:
    """Build a cinema shot list: camera angle, lens, lighting per shot."""
    shots = []
    for i in range(min(count, 8)):
        shots.append({
            "shot": i + 1,
            "camera": CAMERA_ANGLES[i % len(CAMERA_ANGLES)],
            "lens": LENSES[i % len(LENSES)],
            "lighting": LIGHTING[i % len(LIGHTING)],
            "motion": ["slow push-in", "orbit", "static locked", "crane up"][i % 4],
            "subject": subject,
            "style": style,
        })
    return "CINEMA SHOT LIST:\n" + json.dumps(shots, indent=2)


def ms_image_prompt(subject: str, style: str = "cinematic product photo",
                    lighting: str = "soft studio softbox") -> str:
    p = (f"{style} of {subject}, {lighting}, ultra-detailed, 8k, "
         f"sharp focus, professional composition")
    return _maybe_submit(p, "image")


def ms_video_prompt(subject: str, camera: str = "slow push-in",
                    seconds: int = 5) -> str:
    p = (f"{seconds}s video: {subject}, {camera} camera move, cinematic "
         f"lighting, smooth motion, 24fps")
    return _maybe_submit(p, "video")


def ms_lip_sync_prompt(video_desc: str, audio_desc: str = "clear voiceover") -> str:
    p = (f"lip-sync {video_desc} to {audio_desc}, natural mouth motion, "
         f"stable face, no artifacts")
    return _maybe_submit(p, "lip_sync")


MANIFEST = {
    "name": "media_studio",
    "description": "Optional media/cinema studio: image, video, lip-sync "
                   "prompts and shot lists (Higgsfield-style). Lazy-loaded; "
                   "no heavy pipelines unless invoked.",
    "tools": {
        "ms_shot_list": {
            "description": "Generate a cinema shot list (camera/lens/lighting/motion)",
            "parameters": {"subject": "string", "style": "string optional",
                           "count": "int optional (max 8)"},
            "func": ms_shot_list,
        },
        "ms_image_prompt": {
            "description": "Build (and optionally submit) an image-gen prompt",
            "parameters": {"subject": "string", "style": "string optional",
                           "lighting": "string optional"},
            "func": ms_image_prompt,
        },
        "ms_video_prompt": {
            "description": "Build (and optionally submit) a video-gen prompt",
            "parameters": {"subject": "string", "camera": "string optional",
                           "seconds": "int optional"},
            "func": ms_video_prompt,
        },
        "ms_lip_sync_prompt": {
            "description": "Build a lip-sync prompt for video+audio",
            "parameters": {"video_desc": "string", "audio_desc": "string optional"},
            "func": ms_lip_sync_prompt,
        },
    },
}
