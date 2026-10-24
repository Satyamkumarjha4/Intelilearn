"""Scrub credentials from text before it is stored (ModelCall.error) or shown (admin messages, events, probes).

Provider SDK errors sometimes echo request details. Two layers:
  - the actual values of secret-looking environment variables (…_API_KEY, …_TOKEN, …_SECRET, …PASSWORD)
  - common key formats, in case a key arrived some other way
"""

import os
import re
from collections.abc import Mapping


class Redactor:
    MASK = "[redacted]"
    SECRET_ENV = re.compile(r"(_API_KEY|_TOKEN|_SECRET|_SECRET_KEY|PASSWORD)$")
    KEY_PATTERNS = re.compile(
        r"AIza[0-9A-Za-z_\-]{30,}"  # Google
        r"|gsk_[0-9A-Za-z]{20,}"  # Groq
        r"|sk-(?:ant-|proj-)?[0-9A-Za-z_\-]{20,}"  # OpenAI / Anthropic
        r"|(?i:bearer)\s+[0-9A-Za-z._\-]{20,}"
    )
    # Shorter values are too likely to be ordinary words to mask everywhere they appear.
    MIN_SECRET_LENGTH = 8

    def __init__(self, environ: Mapping[str, str] | None = None):
        self._environ = environ

    def redact(self, text: str) -> str:
        if not text:
            return text
        for value in self._secret_values():
            text = text.replace(value, self.MASK)
        return self.KEY_PATTERNS.sub(self.MASK, text)

    def _secret_values(self) -> list[str]:
        # Read the environment on every call, so keys set after start-up (or by a test) are covered.
        environ = self._environ if self._environ is not None else os.environ
        values = [v for k, v in environ.items() if self.SECRET_ENV.search(k) and len(v) >= self.MIN_SECRET_LENGTH]
        return sorted(values, key=len, reverse=True)  # longest first, so overlapping values mask fully


# Stateless default, reading os.environ at call time.
REDACTOR = Redactor()
