"""Secret detection shared by LLM input, output, and citation boundaries."""

import re

from termnova.config import Settings

SECRET_PATTERNS = {
    "OPENROUTER_KEY": re.compile(r"\bsk-or-v1-[a-zA-Z0-9]{20,}\b|\bsk-or-[a-zA-Z0-9_-]{20,}\b"),
    "OPENAI_KEY": re.compile(r"\bsk-[a-zA-Z0-9_-]{20,}\b"),
    "GITHUB_TOKEN": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36,}\b"),
    "AWS_KEY": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "PRIVATE_KEY": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
        r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        re.DOTALL,
    ),
    "BEARER_TOKEN": re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{20,}"),
    "DB_CONNECTION": re.compile(r"\b(?:postgres|postgresql|rediss?):\/\/[^\s\"']+\b"),
    "JWT_TOKEN": re.compile(
        r"\beyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b"
    ),
    "GENERIC_SECRET": re.compile(
        r"(?i)(?:api[_-]?key|secret[_-]?key|access[_-]?token|password)"
        r"[\s:=]+['\"]?([a-zA-Z0-9_./+=-]{20,})['\"]?"
    ),
}


def _configured_secret_values(settings: Settings) -> list[str]:
    api_key = settings.API_KEY.get_secret_value() if settings.API_KEY else None
    candidates = [
        api_key,
        settings.OPENCODE_API_KEY,
        settings.OPENAI_API_KEY,
        settings.OPENROUTER_API_KEY,
        settings.AWS_ACCESS_KEY_ID,
        settings.AWS_SECRET_ACCESS_KEY,
    ]
    return [value for value in candidates if value and len(value) >= 8]


def redact_secrets(text: str, settings: Settings) -> tuple[str, bool]:
    """Redact known runtime credentials and credential-shaped values."""
    redacted = text
    found = False

    for value in _configured_secret_values(settings):
        if value in redacted:
            redacted = redacted.replace(value, "[REDACTED_SECRET]")
            found = True

    for secret_type, pattern in SECRET_PATTERNS.items():
        if pattern.search(redacted):
            redacted = pattern.sub(f"[REDACTED_{secret_type}]", redacted)
            found = True

    return redacted, found
