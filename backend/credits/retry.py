"""What pressing Retry on a failed lesson will cost (credits plan §9.2).

A Retry asks for the action of the stopped run again, with the same hints (the failure gave the credits back). The
screen cannot know what the run was asked with, so the server reads it from the run and prices it with the rule
the gate uses. A Retry whose work was kept, or whose run held nothing, costs nothing and says so rather than showing a
price that will not be charged.
"""

from lessons.metering import AuthorizationLedger, RunOutcome
from lessons.models import GraphRun, Lesson

from .pricing.journey import JourneyQuote
from .quotes import QuoteAnswer


class RetryQuote:
    ACTION = "lesson.retry"

    def __init__(self, authorizations: AuthorizationLedger | None = None, journeys: JourneyQuote | None = None):
        self.authorizations = authorizations or AuthorizationLedger()
        self.journeys = journeys or JourneyQuote()

    def of(self, lesson: Lesson) -> dict:
        last = GraphRun.objects.for_subject(lesson).filter(graph=GraphRun.Graph.FLOW).order_by("-created_at").first()
        stored = self.authorizations.read(last) if last else None
        if stored is None or stored.settled is RunOutcome.SUCCEEDED:
            return QuoteAnswer.free(self.ACTION, lesson.owner)
        asked = stored.authorization
        return QuoteAnswer.of(str(asked.action), self.journeys.of(asked.action, asked.size), lesson.owner)
