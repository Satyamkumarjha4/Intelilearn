"""When two addresses are the same inbox (phase 11, D7): the canonical email.

It decides "have we seen this person" and nothing else: the unique column, the throttle keys, the lookups. The address
as typed is what mail is sent to and shown as.
"""


class MalformedEmail(ValueError):
    """An address that has no local part, no domain or no `@`."""


class EmailCanonicalizer:
    #: Gmail ignores the dots of a local part, and `googlemail.com` is the same mailbox as `gmail.com`.
    GMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})
    GMAIL = "gmail.com"

    @classmethod
    def of(cls, typed: str) -> str:
        """Lowercased; the `+tag` dropped for every domain; for Gmail also the dots. Raises `MalformedEmail`."""
        address = (typed or "").strip().lower()
        local, at, domain = address.rpartition("@")
        if not at or not local or not domain:
            raise MalformedEmail(f"not an email address: {typed!r}")
        local = local.split("+", 1)[0]
        if domain in cls.GMAIL_DOMAINS:
            local, domain = local.replace(".", ""), cls.GMAIL
        if not local:
            raise MalformedEmail(f"nothing before the + in {typed!r}")
        return f"{local}@{domain}"
