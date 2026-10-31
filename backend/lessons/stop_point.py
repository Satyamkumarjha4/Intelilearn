"""Where a stopped flow run left the lesson, so Retry can carry on from there (`StopPoint`)."""

from .models import GraphRun
from .stages import Stage
from .subjects import RunSubject


class StopPoint:
    """Where a stopped flow run left the lesson, so Retry can carry on from there.

    Stop marks the lesson failed: once a quiz is answered there is nothing the learner can do from `awaiting_*`, so the
    stopped lesson shows the Retry card. The run remembers the answer it was about to hand the graph, and Retry hands
    it again. It also remembers the stage the lesson was in, but only for a run nobody had started: then the thread
    still waits at the question and the stage is still true. A run the worker had started is already moving (Stop is
    noticed after the step that is running), so the stage read at the click may be one the thread has left; nothing is
    remembered and the lesson stays failed until the first node that runs moves it to its own stage (`Node`).
    """

    KEY = "stopped_in"
    #: the resume trigger → the kind of pause its answer is for (an answer must never reach a different question)
    ANSWERS = {
        GraphRun.Trigger.RESUME_DIAGNOSTIC: "diagnostic",
        GraphRun.Trigger.RESUME_PREREQUISITE: "prerequisite",
        GraphRun.Trigger.RESUME_CHOICE: "mastery_choice",
    }

    def remember(self, run: GraphRun) -> None:
        """Call before the lesson is failed: the stage is read from the database, where the graph moves it."""
        if run.graph != GraphRun.Graph.FLOW:
            return
        stage = run.fresh_subject().stage
        if stage in (Stage.READY, Stage.FAILED):
            return
        started = GraphRun.objects.filter(pk=run.pk, started_at__isnull=False).exists()
        run.payload = {**run.payload, self.KEY: "" if started else stage}
        GraphRun.objects.filter(pk=run.pk).update(payload=run.payload)

    #: the kind of question a thread pauses at → the stage the lesson waits in
    PAUSES = {
        "diagnostic": Stage.AWAITING_DIAGNOSTIC,
        "prerequisite": Stage.AWAITING_PREREQUISITE,
        "mastery_choice": Stage.AWAITING_CHOICE,
    }

    def settle(self, run: GraphRun, paused_at: str | None) -> None:
        """The worker noticed the Stop, so the thread's position is known: waiting at a question (`paused_at` is its
        kind), then that question's stage is true and Retry restores it; otherwise it is moving, and none is."""
        if run.graph != GraphRun.Graph.FLOW:
            return
        stage = self.PAUSES.get(paused_at or "")
        fresh = GraphRun.objects.get(pk=run.pk)
        GraphRun.objects.filter(pk=run.pk).update(payload={**fresh.payload, self.KEY: str(stage) if stage else ""})

    def of(self, subject: RunSubject) -> tuple[Stage | None, dict]:
        """The stage to go back to and the payload for the retry run. Nothing, unless the last flow run was stopped."""
        last = GraphRun.objects.for_subject(subject).filter(graph=GraphRun.Graph.FLOW).order_by("-created_at").first()
        if last is None or last.status != GraphRun.Status.CANCELLED or self.KEY not in last.payload:
            return None, {}
        payload = {}
        if "resume" in last.payload and last.trigger in self.ANSWERS:
            payload = {"resume": last.payload["resume"], "resume_for": self.ANSWERS[last.trigger]}
        remembered = last.payload[self.KEY]
        return (Stage(remembered) if remembered else None), payload
