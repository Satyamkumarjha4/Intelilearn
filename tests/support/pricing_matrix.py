"""The plan's pricing matrix (§5.4) and the totals a learner is shown (§5.5, corrected by changelog P2) as data,
built from
the hints the services really send (`size_of` of the real services where there is one). Shared by the tests of the
rules,
of the quote endpoint and of the gate, so all three are held to the same table.

`MATRIX` rows are `(action, size, credits, price keys)`; `JOURNEYS` rows are `(action, size, due now, later, total)`.
"""

from lessons.followups import FollowupService
from lessons.metering import MeteredAction
from lessons.services import LessonService, MaterialService

CREATE, CONTINUE, FOLLOWUP = MeteredAction.LESSON_CREATE, MeteredAction.LESSON_CONTINUE, MeteredAction.LESSON_FOLLOWUP
RETAKE, QUIZ, QUIZ_RETAKE, SHEET = (
    MeteredAction.TEST_RETAKE,
    MeteredAction.QUIZ_CREATE,
    MeteredAction.QUIZ_RETAKE,
    MeteredAction.SHEET_GENERATE,
)


def create(entry, intent, origin, sheets=0):
    return LessonService.size_of(entry, intent, origin, sheets)


def quiz_size(count, source="topic", mode="self_rating"):
    return {"num_questions": count, "source_type": source, "sources": 1, "level_mode": mode, "has_subjective": False}


def continue_size(choice, **more):
    return {"choice": choice, "perfect": False, **more}


# (action, size, credits, the price keys it is made of)
MATRIX = [
    # lesson.create: Quick check
    (CREATE, create("diagnostic", "lesson", "direct"), 3, ["lesson.check"]),
    (CREATE, create("diagnostic", "lesson", "recommendation"), 2, ["lesson.check_recommended"]),
    (CREATE, create("diagnostic", "sheets", "direct", 1), 3, ["lesson.check"]),
    (CREATE, create("diagnostic", "sheets", "direct", 2), 3, ["lesson.check"]),
    (CREATE, create("diagnostic", "sheets", "recommendation", 1), 3, ["lesson.check"]),
    (CREATE, create("diagnostic", "sheets", "recommendation", 2), 3, ["lesson.check"]),
    # lesson.create: self-rating
    (CREATE, create("self_rating", "lesson", "direct"), 10, ["lesson.full"]),
    (CREATE, create("self_rating", "lesson", "recommendation"), 9, ["lesson.full_recommended"]),
    (CREATE, create("self_rating", "sheets", "direct", 1), 2, ["sheet.each"]),
    (CREATE, create("self_rating", "sheets", "direct", 2), 4, ["sheet.each"] * 2),
    (CREATE, create("self_rating", "sheets", "recommendation", 1), 2, ["sheet.each"]),
    (CREATE, create("self_rating", "sheets", "recommendation", 2), 4, ["sheet.each"] * 2),
    # lesson.create: a quick quiz result
    (CREATE, create("quiz_result", "lesson", "quiz_result"), 9, ["lesson.full_from_quiz"]),
    (CREATE, create("quiz_result", "sheets", "quiz_result", 1), 2, ["sheet.each"]),
    (CREATE, create("quiz_result", "sheets", "quiz_result", 2), 4, ["sheet.each"] * 2),
    # lesson.continue: the lesson, at any score
    (CONTINUE, continue_size("lesson"), 7, ["lesson.rest"]),
    (CONTINUE, {"choice": "lesson", "perfect": True}, 7, ["lesson.rest"]),
    # lesson.continue: sheets, by the number of sheets and not by the score
    (CONTINUE, MaterialService.size_of("sheets"), 2, ["sheets.after_check"]),
    (CONTINUE, continue_size("sheets_only", intent="sheets", sheets=2, grounding="quiz"), 2, ["sheets.after_check"]),
    (CONTINUE, {**continue_size("sheets_only", intent="sheets", sheets=2), "perfect": True}, 2, ["sheets.after_check"]),
    (
        CONTINUE,
        continue_size("sheets_only", intent="sheets", sheets=1, grounding="quiz"),
        0,
        ["sheets.after_check_single"],
    ),
    (
        CONTINUE,
        {**continue_size("sheets_only", intent="sheets", sheets=1), "perfect": True},
        0,
        ["sheets.after_check_single"],
    ),
    # the others
    (FOLLOWUP, FollowupService.size_of("foundation"), 5, ["followup.foundation"]),
    (FOLLOWUP, FollowupService.size_of("advanced"), 7, ["followup.advanced"]),
    (RETAKE, {"question_count": 10, "attempt_no": 2}, 2, ["test.retake"]),
    (RETAKE, {"question_count": 10, "attempt_no": 9}, 2, ["test.retake"]),
    (SHEET, {"sheets": 1, "grounding": "lesson"}, 3, ["sheet.each", "sheet.grounded_extra"]),
    (SHEET, {"sheets": 2, "grounding": "lesson"}, 5, ["sheet.each", "sheet.each", "sheet.grounded_extra"]),
    (SHEET, {"sheets": 1, "grounding": "quiz"}, 2, ["sheet.each"]),
    (SHEET, {"sheets": 2, "grounding": "quiz"}, 4, ["sheet.each"] * 2),
    (SHEET, {"sheets": 1, "grounding": "none"}, 2, ["sheet.each"]),
    (SHEET, {"sheets": 2, "grounding": "none"}, 4, ["sheet.each"] * 2),
]

# quiz.create and quiz.retake: the six counts, each in the two columns of the twelve prices
TIERS = {5: ("quiz.tier_5", 1), 10: ("quiz.tier_10", 2), 15: ("quiz.tier_10", 2),
         20: ("quiz.tier_20", 3), 25: ("quiz.tier_20", 3), 30: ("quiz.tier_20", 3)}  # fmt: skip
for count, (tier, credits) in TIERS.items():
    MATRIX += [
        (QUIZ, quiz_size(count), credits, [tier]),
        (QUIZ, quiz_size(count, "lessons", "existing_score"), credits + 1, [tier, "quiz.extra"]),
        (QUIZ, quiz_size(count, "lessons", "self_rating"), credits + 1, [tier, "quiz.extra"]),
        (QUIZ, quiz_size(count, "topic", "calibration"), credits + 1, [tier, "quiz.extra"]),
        (QUIZ, quiz_size(count, "lessons", "calibration"), credits + 1, [tier, "quiz.extra"]),  # never both
        (QUIZ_RETAKE, {"num_questions": count, "source_type": "topic"}, credits, [tier]),
        (QUIZ_RETAKE, {"num_questions": count, "source_type": "lessons"}, credits + 1, [tier, "quiz.extra"]),
    ]


# (action, size, due now, later, total)
JOURNEYS = [
    (CREATE, create("diagnostic", "lesson", "direct"), 3, 7, 10),
    (CREATE, create("diagnostic", "lesson", "recommendation"), 2, 7, 9),
    (CREATE, create("self_rating", "lesson", "direct"), 10, 0, 10),
    (CREATE, create("self_rating", "lesson", "recommendation"), 9, 0, 9),
    (CREATE, create("quiz_result", "lesson", "quiz_result"), 9, 0, 9),
    (CREATE, create("diagnostic", "sheets", "direct", 1), 3, 0, 3),
    (CREATE, create("diagnostic", "sheets", "direct", 2), 3, 2, 5),
    (CREATE, create("diagnostic", "sheets", "recommendation", 2), 3, 2, 5),
    (CREATE, create("self_rating", "sheets", "direct", 1), 2, 0, 2),
    (CREATE, create("self_rating", "sheets", "direct", 2), 4, 0, 4),
    (CREATE, create("quiz_result", "sheets", "quiz_result", 1), 2, 0, 2),
    (CREATE, create("quiz_result", "sheets", "quiz_result", 2), 4, 0, 4),
    (CONTINUE, continue_size("lesson"), 7, 0, 7),  # the mastery choice, Expert lesson
    (CONTINUE, MaterialService.size_of("sheets"), 2, 0, 2),  # the mastery choice, sheets
    (FOLLOWUP, FollowupService.size_of("foundation"), 5, 0, 5),
    (RETAKE, {"question_count": 10, "attempt_no": 2}, 2, 0, 2),
    (QUIZ, quiz_size(10, "lessons", "existing_score"), 3, 0, 3),
    (SHEET, {"sheets": 2, "grounding": "lesson"}, 5, 0, 5),
]
