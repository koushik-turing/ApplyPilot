"""Thin wrapper around the Anthropic (Claude) API for AI resume tailoring.

The API key is read by the SDK from the ANTHROPIC_API_KEY environment variable
(or a .env file) — it is never stored in code and never sent to the browser.
"""
from __future__ import annotations
import os


def claude_available() -> bool:
    """True if an API key is configured and the SDK is importable."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def get_client():
    import anthropic
    # Pass the key explicitly and disable auth_token so the SDK never sends both
    # an x-api-key AND a bearer token (which the API rejects with a 401).
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), auth_token=None)
