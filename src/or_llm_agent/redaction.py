from __future__ import annotations

import os
import re


SECRET_ENV_VARS = (
    "OPENAI_API_KEY",
    "CLAUDE_API_KEY",
    "ANTHROPIC_API_KEY",
)


def redact_text(text: object) -> str:
    """Remove provider credentials from text before it reaches logs or artifacts."""
    redacted = "" if text is None else str(text)

    for env_name in SECRET_ENV_VARS:
        secret = os.getenv(env_name)
        if secret and len(secret) >= 8:
            redacted = redacted.replace(secret, "<redacted>")

    replacements = (
        (r"(invalid key:\s*)[^'\"\s,)]+", r"\1<redacted>"),
        (r"(api[_-]?key\s*[=:]\s*)[^'\"\s,)]+", r"\1<redacted>"),
        (r"(authorization:\s*bearer\s+)[^'\"\s,)]+", r"\1<redacted>"),
        (r"sk-[A-Za-z0-9][A-Za-z0-9_\-]{8,}", "<redacted>"),
        (r"://([^/:@\s]+):([^/@\s]+)@", r"://<redacted>:<redacted>@"),
    )
    for pattern, replacement in replacements:
        redacted = re.sub(pattern, replacement, redacted, flags=re.IGNORECASE)

    return redacted


def env_status(*names: str) -> str:
    return "set" if any(os.getenv(name) for name in names) else "missing"

