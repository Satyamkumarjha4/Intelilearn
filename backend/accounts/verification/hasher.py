"""How a code is kept: a keyed hash, never the code (plan T2).

The key comes from `SECRET_KEY` and the hash is salted with the purpose, the canonical email and the row's id, so a hash
cannot be moved to another row or another person. **Honest limit:** a six-digit code has a million values, so anyone who
reads the table can find a code offline in a moment. The hash keeps codes out of logs, dumps and a staff member's
screen; what actually protects a code is that it lives ten minutes, works once and dies after five wrong tries.
"""

from django.utils.crypto import constant_time_compare, salted_hmac


class CodeHasher:
    SALT = "accounts.verification-code"

    def hash(self, code: str, purpose: str, email_canonical: str, row_id) -> str:
        return salted_hmac(self.SALT, f"{purpose}|{email_canonical}|{row_id}|{code}", algorithm="sha256").hexdigest()

    def matches(self, code: str, stored: str, purpose: str, email_canonical: str, row_id) -> bool:
        return constant_time_compare(self.hash(code, purpose, email_canonical, row_id), stored)
