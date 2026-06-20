"""Thin client for a local Ollama server (optional AI features).

Uses only the standard library so the app has no hard dependency on AI — if
Ollama isn't running, callers fall back to deterministic rule-based logic.
"""
from __future__ import annotations
import json
import urllib.request
import urllib.error

from .config import settings


def ollama_running() -> bool:
    """True if a local Ollama server answers quickly."""
    try:
        with urllib.request.urlopen(settings.ollama_url + "/api/tags", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def generate(prompt: str, system: str = "", temperature: float = 0.3) -> str | None:
    """Run a single completion. Returns None on any failure."""
    payload = {
        "model": settings.llm_model,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": temperature},
    }
    req = urllib.request.Request(
        settings.ollama_url + "/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read()).get("response")
    except Exception:
        return None
