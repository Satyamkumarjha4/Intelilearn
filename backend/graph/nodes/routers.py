"""Routers: the conditional edges. Pure functions of the state, as classes so the builder can configure them."""

from abc import ABC, abstractmethod
from typing import Any


class Router(ABC):
    @abstractmethod
    def __call__(self, state: dict) -> Any:
        """The name of the next node (or a list of `Send`s)."""


class CheckRouter(Router):
    """After a `ValidateNode`: continue when valid, give up when the budget is spent, otherwise retry."""

    def __init__(self, feedback_key: str, *, ok: str, retry: str, fail: str = "mark_failed"):
        self.feedback_key, self.ok, self.retry, self.fail = feedback_key, ok, retry, fail

    def __call__(self, state: dict) -> str:
        if not (state.get("feedback") or {}).get(self.feedback_key):
            return self.ok
        return self.fail if state.get("error") else self.retry


class LevelRouter(Router):
    """After the diagnostic is graded: where each route goes."""

    def __init__(self, destinations: dict[str, str]):
        self.destinations = destinations

    def __call__(self, state: dict) -> str:
        return self.destinations[state["route"]]
