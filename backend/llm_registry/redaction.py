"""Scrub credentials from text before it is stored (ModelCall.error) or shown (admin messages).

Provider SDK errors sometimes echo request details. Two layers:
  - the actual values of secret-looking environment variables (…_API_KEY, …_TOKEN, …_SECRET, …PASSWORD)
  - common key formats, in case a key arrived some other way
"""

import os
import re

MASK = "[redacted]"
_SECRET_ENV = re.compile(r"(_API_KEY|_TOKEN|_SECRET|_SECRET_KEY|PASSWORD)$")
_KEY_PATTERNS = re.compile(
    r"AIza[0-9A-Za-z_\-]{30,}"  # Google
    r"|gsk_[0-9A-Za-z]{20,}"  # Groq
    r"|sk-(?:ant-|proj-)?[0-9A-Za-z_\-]{20,}"  # OpenAI / Anthropic
    r"|(?i:bearer)\s+[0-9A-Za-z._\-]{20,}"
)


def _secret_values() -> list[str]:
    values = [v for k, v in os.environ.items() if _SECRET_ENV.search(k) and len(v) >= 8]
    return sorted(values, key=len, reverse=True)  # longest first, so overlapping values mask fully


def redact(text: str) -> str:
    if not text:
        return text
    for value in _secret_values():
        text = text.replace(value, MASK)
    return _KEY_PATTERNS.sub(MASK, text)
