"""A learner's history in a learner's words (credits plan §8.1, §9).

The ledger is written for people who audit it; a learner reads "Used 3 credits for “Binary search”". This turns a row
into
that sentence, with the lesson or quiz it was about when it still exists. It never says hold, ledger, bucket,
transaction
or any other term of the machinery, and it sends nothing of the ledger's insides (the action, the reserve, the key).
"""

from dataclasses import dataclass

from lessons.models import Lesson
from quizzes.models import QuickQuiz, QuickQuizAttempt

from .models import CreditBucket, CreditTransaction
from .refusals import credits_word

Type = CreditTransaction.Type
Source = CreditBucket.Source


@dataclass(frozen=True)
class Subject:
    kind: str  # lesson or quiz
    id: str
    title: str

    def as_json(self) -> dict:
        return {"kind": self.kind, "id": self.id, "title": self.title}


class SubjectTitles:
    """What the rows of a page were about, found in one query a kind. A subject that no longer exists is missing."""

    @classmethod
    def for_rows(cls, rows, user) -> dict[tuple[str, str], Subject]:
        wanted: dict[str, set] = {}
        for row in rows:
            if row.subject_id and row.subject_kind:
                wanted.setdefault(row.subject_kind, set()).add(row.subject_id)
        found: dict[tuple[str, str], Subject] = {}
        for lesson in Lesson.objects.filter(owner=user, pk__in=wanted.get("lesson", ())).values("pk", "topic"):
            found["lesson", str(lesson["pk"])] = Subject("lesson", str(lesson["pk"]), lesson["topic"])
        for quiz in QuickQuiz.objects.filter(owner=user, pk__in=wanted.get("quiz", ())).values("pk", "topic"):
            found["quiz", str(quiz["pk"])] = Subject("quiz", str(quiz["pk"]), quiz["topic"])
        from lessons.models import TestSubmission

        attempts = TestSubmission.objects.filter(lesson__owner=user, pk__in=wanted.get("test_attempt", ()))
        for attempt in attempts.values("pk", "lesson_id", "lesson__topic"):
            found["test_attempt", str(attempt["pk"])] = Subject(
                "lesson", str(attempt["lesson_id"]), attempt["lesson__topic"]
            )
        attempts = QuickQuizAttempt.objects.filter(quiz__owner=user, pk__in=wanted.get("quiz_attempt", ()))
        for attempt in attempts.values("pk", "quiz_id", "quiz__topic"):
            found["quiz_attempt", str(attempt["pk"])] = Subject("quiz", str(attempt["quiz_id"]), attempt["quiz__topic"])
        return found


class TransactionWords:
    """One row, as a sentence and a kind the screen can colour."""

    EARNED = {
        Source.SIGNUP: "Welcome gift: {n}",
        Source.DAILY: "Earned {n} for studying today",
        Source.WEEKLY_STREAK: "Earned {n} for a 7-day streak",
        Source.MONTHLY_STREAK: "Earned {n} for a 28-day streak",
    }
    BOUGHT = {Source.PURCHASE: "Bought {n}", Source.SUBSCRIPTION: "{n} from your plan"}

    def __init__(self, subjects: dict[tuple[str, str], Subject]):
        self.subjects = subjects

    def describe(self, row: CreditTransaction) -> dict:
        subject = self.subjects.get((row.subject_kind, str(row.subject_id))) if row.subject_id else None
        kind, text = self._say(row, subject.title if subject else "")
        return {
            "id": row.pk,
            "kind": kind,
            "text": text,
            "amount": row.amount,
            "balance_after": row.balance_after,
            "created_at": row.created_at,
            "subject": subject.as_json() if subject else None,
        }

    def _say(self, row: CreditTransaction, title: str) -> tuple[str, str]:
        about = f" for “{title}”" if title else ""
        n = credits_word(abs(row.amount))
        match row.type:
            case Type.GRANT:
                return self._grant(row.meta.get("source", ""), n)
            case Type.HOLD:
                return "reserved", (
                    f"Reserved {n}{about}" if row.amount else f"No credits needed{about or ' for this'}"
                )
            case Type.COMMIT:
                spent = row.hold.amount if row.hold else 0
                return "used", (f"Used {credits_word(spent)}{about}" if spent else f"No credits used{about}")
            case Type.RELEASE:
                return "returned", (f"Returned {n}{about}" if row.amount else f"Nothing to return{about}")
            case Type.DEBIT:
                return "used", f"Used {n}"
            case Type.REPAIR:
                return "used", f"Used {n} to repair your streak"
            case Type.ADMIN_ADJUST:
                return "adjusted", (f"{n} added by Socra" if row.amount > 0 else f"{n} taken off by Socra")
            case Type.EXPIRE:
                return "expired", f"{n} expired"
            case Type.FORFEIT:
                return "taken_back", f"{n} removed with the account"
            case Type.REFUND:
                return "taken_back", f"{n} taken back after a refund"
        return "used", f"{n}"  # a kind this version does not know: still readable

    def _grant(self, source: str, n: str) -> tuple[str, str]:
        if source in self.EARNED:
            return "earned", self.EARNED[source].format(n=n)
        if source in self.BOUGHT:
            return "bought", self.BOUGHT[source].format(n=n)
        if source == Source.ADMIN_GRANT:
            return "adjusted", f"{n} added by Socra"
        return "returned", f"{n} given back"
