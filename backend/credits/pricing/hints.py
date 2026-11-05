"""Reading the size hints an action is asked with (`ActionContext.size`) strictly.

The gate and the quote endpoint both read them through here: a hint that is missing, unknown or the wrong kind of
value is
`UnknownHints`, naming the hint, and nothing is priced. So the quote endpoint cannot be used to probe, and a service
that
starts sending a hint the rules do not know fails loudly instead of being charged a wrong price.
"""

from collections.abc import Iterable


class UnknownHints(ValueError):
    """A hint the price rules cannot read. `field` names it (or `size` for the whole)."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}")
        self.field = field
        self.reason = message


REQUIRED = object()


class HintReader:
    def __init__(self, size, known: Iterable[str]):
        if not isinstance(size, dict):
            raise UnknownHints("size", "must be an object of hints.")
        self.size = size
        if unknown := sorted(set(size) - set(known)):
            raise UnknownHints(unknown[0], "is not a hint of this action.")

    def one_of(self, name: str, allowed: Iterable[str], default=REQUIRED):
        """A choice from a fixed list."""
        allowed = tuple(allowed)
        if name not in self.size and default is not REQUIRED:
            return default
        value = self._value(name, default)
        if not isinstance(value, str) or value not in allowed:
            raise UnknownHints(name, f"{value!r} is not one of {', '.join(allowed)}.")
        return value

    def whole(self, name: str, minimum: int = 0, maximum: int | None = None, allowed=None, default=REQUIRED):
        """A whole number (never a boolean, a string or a fraction), within limits or from a fixed set."""
        if name not in self.size and default is not REQUIRED:
            return default
        value = self._value(name, default)
        bad = isinstance(value, bool) or not isinstance(value, int) or value < minimum
        bad = bad or (maximum is not None and value > maximum) or (allowed is not None and value not in allowed)
        if bad:
            raise UnknownHints(name, f"{value!r} is not an allowed number.")
        return value

    def flag(self, name: str, default=REQUIRED):
        if name not in self.size and default is not REQUIRED:
            return default
        value = self._value(name, default)
        if not isinstance(value, bool):
            raise UnknownHints(name, f"{value!r} is not true or false.")
        return value

    def _value(self, name: str, default):
        if name in self.size:
            return self.size[name]
        if default is REQUIRED:
            raise UnknownHints(name, "is needed to price this.")
        return default
