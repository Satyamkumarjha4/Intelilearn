"""Turns the questions a model wrote into the questions that are stored.

Three things are decided by code and never taken from the model: the marks (`MarksPolicy`), the right answer of a
numerical question (computed from its `answer_expr`) and how the marks of a short or long answer are shared between its
criteria (`CriteriaRebalancer`). A question the code cannot fit (an expression that cannot be computed, more criteria
than marks) comes back as a problem for the generator to fix.
"""

from ..levels import Difficulty
from .criteria import CriteriaRebalancer
from .expressions import ExpressionError, ExpressionEvaluator
from .marks import MarksPolicy


class QuestionFinisher:
    def __init__(self, evaluator: ExpressionEvaluator | None = None, rebalancer: CriteriaRebalancer | None = None):
        self.evaluator = evaluator or ExpressionEvaluator()
        self.rebalancer = rebalancer or CriteriaRebalancer()

    def finish(self, questions: list[dict]) -> tuple[list[dict], list[str]]:
        """Copies of the questions with marks (and `answer`), and the problems found. The input is not changed."""
        finished, problems = [], []
        for question in questions:
            done, found = self._finish_one(question)
            finished.append(done)
            problems += found
        return finished, problems

    def _fit_criteria(self, done: dict) -> tuple[dict, list[str]]:
        criteria, problem = self.rebalancer.rebalance(done.get("criteria"), done["marks"])
        done = {**done, "criteria": criteria} if criteria is not None else done
        return done, [f"Question {done['id']}: {problem}"] if problem else []

    def _finish_one(self, question: dict) -> tuple[dict, list[str]]:
        difficulty = Difficulty.parse(question["difficulty"])
        done = {**question, "difficulty": difficulty.value, "marks": MarksPolicy.marks(question["type"], difficulty)}
        if question["type"] in ("short_answer", "long_answer"):
            return self._fit_criteria(done)
        if question["type"] != "numerical":
            return done, []
        expression = question.get("answer_expr")
        if not isinstance(expression, str) or not expression.strip():
            return done, [f"Question {question['id']}: write the answer as answer_expr."]
        try:
            value = self.evaluator.evaluate(expression)
        except ExpressionError as exc:
            return done, [f"Question {question['id']}: the answer_expr {expression!r} cannot be computed: {exc}"]
        done["answer"] = round(value, question.get("decimal_precision") or 0)
        return done, []
