"""The one error a seeding step raises: it says which step failed and what to do, and never holds a secret."""


class SeedFailed(Exception):
    """A step did not work; the message says which call and what came back, or what to do about it."""
