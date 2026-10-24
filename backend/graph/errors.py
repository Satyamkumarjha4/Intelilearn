"""Failures a graph raises on purpose: the reason is already written for the learner."""


class RunFailed(Exception):
    """A run that cannot continue, with a readable reason (shown to the learner as is)."""
