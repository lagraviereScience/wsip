"""Small security primitives: opaque tokens, hashing and safe redirect targets."""

from __future__ import annotations

import hashlib
import re
import secrets

_SAFE_NEXT = re.compile(r"^/[A-Za-z0-9/_\-]*$")
DEFAULT_AFTER_LOGIN = "/onboarding"


def new_token(nbytes: int = 32) -> str:
    """URL-safe random token (256 bits by default)."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> bytes:
    """SHA-256 of a high-entropy token. Only hashes are stored server-side."""
    return hashlib.sha256(token.encode("utf-8")).digest()


def safe_next_path(candidate: str | None, default: str = DEFAULT_AFTER_LOGIN) -> str:
    """Accept only same-site absolute paths, never URLs (prevents open redirects).

    Rejects scheme-relative ("//evil.com"), backslash tricks, query strings and
    anything with characters outside a conservative path alphabet.
    """
    if not candidate or candidate.startswith("//") or not _SAFE_NEXT.fullmatch(candidate):
        return default
    return candidate
