"""The calibration walk: five multiple-choice questions that find a level (plan §9.4, R16). Pure.

The questions are written once, a pool of two for each of the diagnostic's five bands, so there is no model call between
questions. The ladder starts at the middle band, goes one band up after a right answer and one down after a wrong one
(the ends hold), and after five questions reads the level off a table of where the learner ended up and how many they
got right. The walk itself is only the list of right and wrong answers so far, which is all this class is given.
"""

from typing import ClassVar

from .levels import BandDifficulty, Difficulty, Level
from .schemas.diagnostic import BANDS

B, F, P, E = Level.BEGINNER, Level.FOUNDATION, Level.PROFICIENT, Level.EXPERT


class AdaptiveLadder:
    QUESTIONS: ClassVar[int] = 5  # the spec's length, and the default of the `calibration_questions` setting
    START: ClassVar[int] = 2  # the middle band, "moderate": difficulty standard
    SHORTEST, LONGEST = 3, 7

    #: rows: the band the walk ended on (basic … hard); columns: the number right (0 … 5). The level never falls when
    #: the learner ends higher with the same number right, or gets more right on the same band.
    LEVELS: ClassVar[tuple[tuple[Level, ...], ...]] = (
        (B, B, B, F, F, F),
        (B, B, F, F, F, P),
        (B, F, F, F, P, P),
        (F, F, F, P, P, E),
        (F, F, P, P, E, E),
    )

    def __init__(self, questions: int = QUESTIONS):
        """`questions` is the length of the walk (3 to 7, the admin setting). The table above is written for five: a
        shorter or longer walk scales the number right onto it, so an all-right walk is always an Expert."""
        if type(questions) is not int or not self.SHORTEST <= questions <= self.LONGEST:
            raise ValueError(
                f"A calibration walk is {self.SHORTEST} to {self.LONGEST} questions long, got {questions!r}."
            )
        self.questions = questions

    def position(self, answers: list[bool]) -> int:
        """The band to ask next after these answers (right is True)."""
        if len(answers) > self.questions:
            raise ValueError(f"A calibration walk is {self.questions} questions long, got {len(answers)} answers.")
        band = self.START
        for right in answers:
            band = max(0, min(len(BANDS) - 1, band + (1 if right else -1)))
        return band

    def done(self, answers: list[bool]) -> bool:
        return len(answers) >= self.questions

    def level(self, answers: list[bool]) -> Level:
        if not self.done(answers):
            raise ValueError(f"The calibration level is known after all {self.questions} questions are answered.")
        return self.LEVELS[self.position(answers)][self.scaled(sum(answers))]

    def scaled(self, right: int) -> int:
        """The number right on the table's scale of five, rounded half up (exact for a walk of five)."""
        return (2 * right * self.QUESTIONS + self.questions) // (2 * self.questions)

    def pick(self, pool: list[dict], asked: list[str], answers: list[bool]) -> dict:
        """The next question: the first one of the band the walk is on that has not been asked. A band can be asked more
        than twice (an up-and-down walk asks the middle one three times) and the pool has two of each, so a used-up
        band falls back to the nearest band that has one left, the easier on a tie."""
        target = self.position(answers)
        unused = [q for q in pool if q["id"] not in asked]
        if not unused:
            raise ValueError("The pool has no question left to ask.")
        return min(unused, key=lambda q: (*self._closeness(q, target), pool.index(q)))

    @staticmethod
    def _closeness(question: dict, target: int) -> tuple[int, int]:
        """Nearest band first, and the easier one of two equally near."""
        band = BANDS.index(question["band"])
        return abs(band - target), band

    @staticmethod
    def difficulty_of(position: int) -> Difficulty:
        """The difficulty of the questions at a band (`BandDifficulty` is the bridge between the two vocabularies)."""
        return BandDifficulty.of(BANDS[position])
