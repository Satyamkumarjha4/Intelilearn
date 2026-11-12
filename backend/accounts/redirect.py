"""Where a sign-in may send a person afterwards (the server side of `frontend/lib/safe-redirect.ts`).

`next` comes from a link anyone can craft, so it is turned into a path on this site or dropped. Prefix checks are not
enough: browsers read `/\\evil.com` as `//evil.com`, and tabs and newlines inside a URL are ignored. So a value is
accepted only when it is a plain path (one leading slash, no backslash, no control character) and resolves, against a
placeholder host, to the same host.
"""

from urllib.parse import urljoin, urlsplit

PLACEHOLDER = "http://socra.invalid"


class RedirectPolicy:
    DEFAULT = "/lessons"

    @classmethod
    def safe_next(cls, value: object, fallback: str | None = None) -> str:
        """`value` as a same-site path (with its query), or the fallback when it could lead anywhere else."""
        fallback = cls.DEFAULT if fallback is None else fallback
        if not isinstance(value, str) or not value.startswith("/") or value.startswith("//"):
            return fallback
        if "\\" in value or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            return fallback
        try:
            joined = urlsplit(urljoin(PLACEHOLDER, value))
        except ValueError:
            return fallback
        if joined.scheme + "://" + joined.netloc != PLACEHOLDER:
            return fallback
        query = f"?{joined.query}" if joined.query else ""
        fragment = f"#{joined.fragment}" if joined.fragment else ""
        return f"{joined.path}{query}{fragment}"
