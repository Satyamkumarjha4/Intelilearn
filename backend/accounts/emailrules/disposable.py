"""Which email domains are disposable (plan D8): a vendored snapshot of a public blocklist, and an allow-list of ours.

The snapshot is `data/disposable_email_domains.txt`, refreshed by `manage.py refresh_disposable_domains` (its header
says which upstream commit and when). The allow-list, `data/school_allowlist.txt`, **always wins**: a school or college
that a strangers' list happens to include stays able to sign up. A name matches the domain itself and any subdomain
of it (`x.mailinator.com` is `mailinator.com`), and the allow-list matches the same way (any `*.ac.in`).
"""

from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


class DisposableDomains:
    BLOCKLIST = DATA / "disposable_email_domains.txt"
    ALLOWLIST = DATA / "school_allowlist.txt"
    _default: "DisposableDomains | None" = None

    def __init__(self, blocked: frozenset[str] | set[str], allowed: frozenset[str] | set[str] = frozenset()):
        self.blocked, self.allowed = frozenset(blocked), frozenset(allowed)

    @classmethod
    def default(cls) -> "DisposableDomains":
        """The shipped snapshot and allow-list, read once."""
        if cls._default is None:
            cls._default = cls(cls.read(cls.BLOCKLIST), cls.read(cls.ALLOWLIST))
        return cls._default

    @staticmethod
    def read(path: Path) -> set[str]:
        """The names in a list file: one per line, `#` starts a comment, blank lines are ignored."""
        names = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            name = line.split("#", 1)[0].strip().lower()
            if name:
                names.add(name)
        return names

    def blocks(self, domain: str) -> bool:
        """True when `domain` (or a parent of it) is disposable and no allow-list entry covers it."""
        names = self._suffixes(domain)
        if any(name in self.allowed for name in names):
            return False
        return any(name in self.blocked for name in names)

    @staticmethod
    def _suffixes(domain: str) -> list[str]:
        """`a.b.example.com` -> the name and each parent down to the last label (`b.example.com`, `example.com`, `com`),
        so an allow-list entry may be a whole suffix such as `ac.in` or `edu`."""
        labels = domain.strip().strip(".").lower().split(".")
        return [".".join(labels[i:]) for i in range(len(labels))]
