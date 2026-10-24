"""Small log-redaction helper for scheduler, DSH and GitHub adapter errors."""

from __future__ import annotations

import re

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)\b(DEEPSEEK_API_KEY|OPENAI_API_KEY|GITHUB_TOKEN|GH_TOKEN)\s*[=:]\s*\S+"),
        r"\1=<redacted>",
    ),
    (
        re.compile(r"(?i)(Authorization:\s*Bearer\s+)\S+"),
        r"\1<redacted>",
    ),
    (
        re.compile(r"(?i)(Authorization:\s*Basic\s+)\S+"),
        r"\1<redacted>",
    ),
    (
        re.compile(r"(?i)(X-Hub-Signature-256:\s*)\S+"),
        r"\1<redacted>",
    ),
)


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
