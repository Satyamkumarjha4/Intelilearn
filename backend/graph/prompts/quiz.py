"""The prompt of a quick quiz's question writer: the same task as a lesson test's, without a lesson plan to lean on."""

from ..questions import QuestionTypes
from .author import WriteQuestionsPrompt


class WriteQuizQuestionsPrompt(WriteQuestionsPrompt):
    """Subject carries `batch` (`{"id", "cells": [{index, type, difficulty, marks, source}]}`), `exclusions`, and
    `quiz`:
    `{level, code_format, sources: {key: {title, level, summary}}}`. A topic quiz has no sources; a quiz from lessons is
    given the summary (made in code from the lesson's plan, never its text) of the lessons of this batch only."""

    def system(self, subject: dict) -> str:
        cells, quiz = subject["batch"]["cells"], subject["quiz"]
        kinds = list(dict.fromkeys(cell["type"] for cell in cells))
        lines = "\n".join(self._line(number, cell, quiz) for number, cell in enumerate(cells, start=1))
        scope = (
            "Ask only about the concepts of the lessons named on the lines, at the level given for each lesson; do "
            "not ask about anything its summary does not cover."
            if self._sources(subject)
            else f"Ask about the topic at the learner's level ({quiz['level']})."
        )
        return f"""You write the questions of a quick quiz: exactly {len(cells)} questions, ONE for each line below, in
        \
this order, each of the type and difficulty on its line. What a question is worth is set by the system, never by \
you, but short and long answers need criteria that add up to it.
{lines}

- How to write each type:
{QuestionTypes.guidance(kinds)}
- {scope}
- Every question names its concept in "concept": a short phrase for what it tests.
- A question must stand on its own and have one clear right answer (or set of right answers).
- Never repeat a question that was already asked, or ask it again in other words.
- Ids "t1", "t2"… in order (the system renames them).
{self._code_rule(quiz, kinds)}{self.language_rule(subject.get("profile"))}"""

    def user(self, subject: dict) -> str:
        sources = self._sources(subject)
        about = (
            "The lessons these questions are about:\n"
            + "\n\n".join(
                f"### {s['title']} (write its questions at {s['level']} level)\n{s['summary']}" for s in sources
            )
            if sources
            else f"The learner's level: {subject['quiz']['level']}"
        )
        return f"""{self.topic_text(subject)}

{about}

Questions already asked (do not repeat them): {self.to_json(self.asked(subject.get("exclusions")))}"""

    @staticmethod
    def _line(number: int, cell: dict, quiz: dict) -> str:
        marks = cell["marks"]
        line = f"{number}. {cell['type']}, {cell['difficulty']}, worth {marks} {'mark' if marks == 1 else 'marks'}"
        source = quiz.get("sources", {}).get(cell.get("source") or "")
        return line + (f' — about "{source["title"]}"' if source else "")

    @staticmethod
    def _sources(subject: dict) -> list[dict]:
        """The lessons this batch is about, once each, in the order of its cells."""
        known = subject["quiz"].get("sources") or {}
        keys = dict.fromkeys(cell.get("source") for cell in subject["batch"]["cells"] if cell.get("source"))
        return [known[key] for key in keys if key in known]

    @staticmethod
    def _code_rule(quiz: dict, kinds: list[str]) -> str:
        if not quiz.get("code_format") or not any(kind in QuestionTypes.SUBJECTIVE for kind in kinds):
            return ""
        return (
            "- This topic is programming: a short or long answer may ask the learner to write code. Then set "
            '"language" to the programming language (for example "python" or "javascript") and, if it helps, '
            '"starter_code"; the criteria judge the code. A question that does not need code leaves both out.\n'
        )
