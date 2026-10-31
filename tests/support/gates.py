"""Action gates for tests (see lessons/metering.py): one that counts, one that refuses.

- `CountingGate`: allows everything and records each `authorize` (the whole `ActionContext`) and each `settle`.
- `RefusingGate`: records the ask, then refuses it with `ActionRefused`, so a test can see that nothing was created.
- `SharedCountingGate`: a counting gate whose records live on the class, for tests that reach the gate through the
  `ACTION_GATE` setting (the views), where the test cannot hand over an instance.
"""

from lessons.metering import ActionContext, ActionRefused, Authorization, RunOutcome


class CountingGate:
    def __init__(self):
        self.authorized: list[ActionContext] = []
        self.settled: list[tuple[str, RunOutcome]] = []

    def authorize(self, context: ActionContext) -> Authorization:
        self.authorized.append(context)
        return Authorization.of(context)

    def settle(self, authorization: Authorization, outcome: RunOutcome) -> None:
        self.settled.append((authorization.action, outcome))

    @property
    def actions(self) -> list[str]:
        return [str(context.action) for context in self.authorized]

    def asked(self, action) -> list[ActionContext]:
        return [context for context in self.authorized if context.action == action]


class RefusingGate(CountingGate):
    def authorize(self, context: ActionContext) -> Authorization:
        self.authorized.append(context)
        raise ActionRefused("Not available.", code="test_refused")


class SharedCountingGate:
    authorized: list[ActionContext] = []
    settled: list[tuple[str, RunOutcome]] = []

    @classmethod
    def reset(cls) -> None:
        cls.authorized, cls.settled = [], []

    def authorize(self, context: ActionContext) -> Authorization:
        type(self).authorized.append(context)
        return Authorization.of(context)

    def settle(self, authorization: Authorization, outcome: RunOutcome) -> None:
        type(self).settled.append((authorization.action, outcome))


class RefusingSharedGate:
    """A gate that refuses everything, for tests that reach it through the `ACTION_GATE` setting (the views)."""

    def authorize(self, context: ActionContext) -> Authorization:
        raise ActionRefused("Not available.", code="test_refused")

    def settle(self, authorization: Authorization, outcome: RunOutcome) -> None:
        pass
