"""The synthetic learners of the pre-launch audit, and what makes each one what it is.

A persona is data (who, how they sign in, which language) and an ordered list of steps (`PersonaStep`, Template
Method): each step knows whether it is already done for a user, so seeding twice changes nothing. A new kind of
persona is a new step or a new row in `AuditPersonas`, never a branch in the seeder.

Everything here is synthetic: the addresses are `audit-<slug>@example.test` (a domain that cannot receive mail; a
hyphen and not a `+tag`, because the app drops a `+tag` when it decides whether two addresses are one inbox, so tagged
personas would be one account) and the passwords never appear in the code or in any output.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Protocol


class PlanPurchaser(Protocol):
    def buy(self, user, plan_key: str, quantity: int = 1) -> None:
        """Buys the plan for the user through the app's own order and payment path."""


class HistoryBuilder(Protocol):
    def build(self, user) -> None:
        """Gives the user a lesson with test attempts and a retest, a study sheet and a quick quiz."""


@dataclass
class SeedWorld:
    """The collaborators a step may need, so a test can hand in fakes for the slow ones."""

    ledger: object  # credits.ledger.Ledger
    days: object  # credits.earning.days.StreakDays
    purchases: PlanPurchaser
    history: HistoryBuilder
    today: object  # callable user -> the learner's local date


class PersonaStep(ABC):
    """One thing a persona has. `apply` does it only when it is not already so."""

    @property
    @abstractmethod
    def label(self) -> str: ...

    @abstractmethod
    def done(self, user, world: SeedWorld) -> bool: ...

    @abstractmethod
    def run(self, user, world: SeedWorld) -> None: ...

    def apply(self, user, world: SeedWorld) -> bool:
        if self.done(user, world):
            return False
        self.run(user, world)
        return True


@dataclass(frozen=True)
class LeaveCredits(PersonaStep):
    """Exactly `keep` credits: takes the rest away, or gives what is missing."""

    keep: int

    @property
    def label(self) -> str:
        return f"balance is {self.keep}"

    def done(self, user, world):
        return world.ledger.balance(user) == self.keep

    def run(self, user, world):
        from uuid import uuid4

        world.ledger.adjust(
            user,
            self.keep - world.ledger.balance(user),
            f"audit-seed:{user.pk}:{uuid4().hex}",
            reason="audit seed: synthetic persona",
            actor="audit_seed",
        )


@dataclass(frozen=True)
class TopUpTo(PersonaStep):
    """At least `amount` credits, so a persona that builds history is never short."""

    amount: int

    @property
    def label(self) -> str:
        return f"at least {self.amount} credits"

    def done(self, user, world):
        return world.ledger.balance(user) >= self.amount

    def run(self, user, world):
        from uuid import uuid4

        world.ledger.adjust(
            user,
            self.amount - world.ledger.balance(user),
            f"audit-seed:{user.pk}:{uuid4().hex}",
            reason="audit seed: synthetic persona",
            actor="audit_seed",
        )


@dataclass(frozen=True)
class HoldPlan(PersonaStep):
    plan_key: str
    quantity: int = 1

    @property
    def label(self) -> str:
        return f"holds the {self.plan_key} plan"

    def done(self, user, world):
        from credits.models import PlanPurchase

        return PlanPurchase.objects.filter(user=user, plan__key=self.plan_key).exists()

    def run(self, user, world):
        world.purchases.buy(user, self.plan_key, self.quantity)


@dataclass(frozen=True)
class HaveStreak(PersonaStep):
    """`length` streak days ending the day before yesterday, so yesterday is missed and can be repaired."""

    length: int = 5

    @property
    def label(self) -> str:
        return f"a {self.length}-day streak with yesterday missed"

    def wanted(self, user, world) -> list:
        from datetime import timedelta

        today = world.today(user)
        return [today - timedelta(days=2 + n) for n in range(self.length)]

    def done(self, user, world):
        return set(self.wanted(user, world)) <= world.days.dates(user)

    def run(self, user, world):
        for day in self.wanted(user, world):
            world.days.add_active(user, day)
        world.days.refresh(user, world.days.snapshot(user, world.today(user)))


@dataclass(frozen=True)
class HaveHistory(PersonaStep):
    @property
    def label(self) -> str:
        return "lesson, test attempts, retest, study sheet and quick quiz"

    def done(self, user, world):
        from lessons.models import Lesson

        return Lesson.objects.filter(owner=user).exists()

    def run(self, user, world):
        world.history.build(user)


@dataclass(frozen=True)
class Persona:
    slug: str
    name: str
    purpose: str
    sign_in: str = "password"  # "password" or "google" (the stand-in provider, no password)
    language: str = "en"
    onboarded: bool = True  # False: a profile nobody has filled in, so onboarding can be walked
    staff: bool = False
    steps: tuple[PersonaStep, ...] = field(default=())

    @property
    def email(self) -> str:
        return f"audit-{self.slug}@example.test"


class AuditPersonas:
    """The catalogue, in the order the runbook lists them (Stage -1, audit prep)."""

    @staticmethod
    def all() -> list[Persona]:
        return [
            Persona("new-learner", "Nia New", "just signed up: the signup grant, no profile yet", onboarded=False),
            Persona("zero-credits", "Zed Zero", "has no credits", steps=(LeaveCredits(0),)),
            Persona("weekly", "Wren Weekly", "holds the Weekly plan", steps=(HoldPlan("weekly_pro"),)),
            Persona("monthly", "Mona Monthly", "holds the Monthly plan", steps=(HoldPlan("monthly_pro"),)),
            Persona("pro-plus", "Pia Plus", "holds the Pro Plus plan", steps=(HoldPlan("pro_plus"),)),
            Persona(
                "streak",
                "Sam Streak",
                "a streak, and yesterday's miss can be repaired",
                steps=(TopUpTo(50), HaveStreak(5)),
            ),
            Persona(
                "history",
                "Hana History",
                "a lesson, test attempts, a retest, a study sheet and a quick quiz",
                steps=(TopUpTo(300), HaveHistory()),
            ),
            Persona("hindi", "Hari Hindi", "learns in Hindi", language="hi"),
            Persona(
                "google", "Gia Google", "signs in with Google (the stand-in provider), no password", sign_in="google"
            ),
            Persona("staff", "Sol Staff", "a staff member: the console", staff=True),
        ]
