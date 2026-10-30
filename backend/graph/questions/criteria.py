"""Fits the criteria of a short or long answer to the marks the table gives it."""

from fractions import Fraction


class CriteriaRebalancer:
    """A model cannot be trusted to add, and the marks are not its to choose, so criteria that do not add up to the
    question's marks are scaled in code rather than sent back. The total is exact (largest-remainder rounding, ties to
    the earlier criterion) and every criterion keeps at least one mark. Only a question with more criteria than marks
    cannot be fitted: that is a problem for the model to fix."""

    def rebalance(self, criteria, marks: int) -> tuple[list[dict] | None, str | None]:
        """→ (the criteria, a problem or None). Criteria that cannot be read are returned as they are, for the
        validator to name. The input is not changed."""
        if not self._readable(criteria) or type(marks) is not int or marks < 1:
            return criteria, None
        if len(criteria) > marks:
            return criteria, (
                f"there are {len(criteria)} criteria for {marks} marks: "
                f"use at most {marks} criteria, each worth at least one mark."
            )
        shares = self._shares([c["marks"] for c in criteria], marks)
        return [{**c, "marks": share} for c, share in zip(criteria, shares, strict=True)], None

    @staticmethod
    def _readable(criteria) -> bool:
        return (
            isinstance(criteria, list)
            and bool(criteria)
            and all(isinstance(c, dict) and type(c.get("marks")) is int and c["marks"] >= 1 for c in criteria)
        )

    @staticmethod
    def _shares(weights: list[int], marks: int) -> list[int]:
        """Proportional to the weights. A criterion whose share would be under one mark is fixed at one, and the rest
        share what is left, until none of them falls under one."""
        fixed: set[int] = set()
        while True:
            free = [i for i in range(len(weights)) if i not in fixed]
            total = sum(weights[i] for i in free)
            ideal = {i: Fraction((marks - len(fixed)) * weights[i], total) for i in free}
            small = {i for i in free if ideal[i] < 1}
            if not small:
                break
            fixed |= small
        shares = {i: 1 for i in fixed} | {i: int(ideal[i]) for i in free}
        leftover = marks - sum(shares.values())
        for i in sorted(free, key=lambda i: (-(ideal[i] - int(ideal[i])), i))[:leftover]:
            shares[i] += 1
        return [shares[i] for i in range(len(weights))]
