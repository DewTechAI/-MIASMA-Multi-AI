"""Web module: fetch URLs over HTTP(S). Read-only, size-capped."""
import httpx



def fetch_url(url: str, max_chars: int = 20000) -> str:
    """GET a URL, return status + truncated text body."""
    if not url.startswith(("http://", "https://")):
        return "error: url must start with http:// or https://"
    try:
        with httpx.stream("GET", url, timeout=20.0,
                          headers={"User-Agent": "multi-ai/0.2"},
                          follow_redirects=True) as r:
            chunks, total = [], 0
            for chunk in r.iter_bytes():
                chunks.append(chunk)
                total += len(chunk)
                if total > 512_000:
                    break
            body = b"".join(chunks).decode(r.encoding or "utf-8", errors="replace")
        return f"HTTP {r.status_code} {r.url}\n\n{body[:max_chars]}"
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"


MANIFEST = {
    "name": "web",
    "description": "Fetch web pages and APIs",
    "tools": {
        "fetch_url": {
            "description": "Download a URL and return its text content",
            "parameters": {"url": "string (required)", "max_chars": "int optional"},
            "func": fetch_url,
        },
    },
}
