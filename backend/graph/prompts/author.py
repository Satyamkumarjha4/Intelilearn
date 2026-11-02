"""Stage B prompts: the plan, pages, test, interactives and the alignment judge."""

import json

from ..questions import QuestionConcepts, QuestionTypes
from ..shapes import LessonShapes
from .base import Prompt
from .scope import SCOPE_REFERENCE


class PlanLessonPrompt(Prompt):
    def system(self, subject: dict) -> str:
        shape = LessonShapes.of(subject["assessment"])
        return f"""You are an expert teacher planning a three-page interactive lesson for one learner.

{shape.describe()}
Start the "core" page at the assessment's start_point and emphasise the learner's gaps. If there are PREREQUISITES \
TO COVER, the "introduction" page teaches every one (list each in covers_prerequisites and teach it in the outline).
The test is a separate screen after the lesson, not a page, and it is not planned here: it is the same for every \
lesson and is written later from the concepts you outline.

Rules:
- level: "{shape.level.value}".{self.title_rule(subject)}
- Every outline "concept" appears on exactly ONE page; pages don't overlap or repeat each other.
- 3-6 outline parts per page, in teaching order.
- quantitative: true only when the topic is mainly about calculating numbers (maths, physics, chemistry, statistics, \
finance); false for any other topic, programming and history included. It decides whether the test has numerical \
questions.
{self.language_rule(subject.get("profile"))}"""

    TITLES = {
        "foundation": "This lesson is a follow-up for a learner whose test showed they need the basics. Give it a "
        'title in the same style as its topic, such as "Foundations of …" or "Introduction to …".',
        "advanced": "This lesson is a follow-up for a learner who did very well on a test. Give it a title in the same "
        'style as its topic, such as "Advanced …" or "Mastering …".',
    }

    def title_rule(self, subject: dict) -> str:
        """A follow-up's topic was set from a template; the title the learner sees is written in the same style."""
        rule = self.TITLES.get(subject.get("followup_level") or "")
        return f"\n- {rule}" if rule else ""

    def user(self, subject: dict) -> str:
        to_cover = subject.get("prerequisites_to_cover") or []
        return f"""{self.topic_text(subject)}

The learner:
{self.learner_text(subject.get("profile"))}

Assessment: {self.to_json(subject["assessment"])}

Prerequisites to cover on the introduction page: {self.to_json(to_cover)}"""


class WritePagePrompt(Prompt):
    """Subject also carries `page_plan` (the plan entry for the page being written)."""

    def system(self, subject: dict) -> str:
        key = subject["page_plan"]["key"]
        shape = LessonShapes.of(subject["assessment"])
        role = shape.role(key)
        return f"""You write one page of an interactive lesson, following the lesson plan exactly.

- In this {shape.level.label} lesson the "{key}" page is "{role.title}": {role.brief}
- Write the "{key}" page. Follow its outline: one section per outline part, in order, with section \
ids "s1", "s2"…
- Each section: a clear, well-structured Markdown body (at least two paragraphs), key points, and worked examples, \
formulas (LaTeX without $ in "formula.latex"; inline maths in Markdown as $…$) or code snippets where they help.
- Each section's "concepts" lists the outline concepts of this page that it teaches, copied exactly from the outline \
(normally just the one the section is for). Use no other names.
- Pitch it at the learner's level and follow the author notes. Use concrete examples and analogies that fit \
their field and goal.
- Don't teach concepts that belong to other pages (see the full plan); you may refer to them briefly.
- Accurate. No filler.
{self.language_rule(subject.get("profile"))}"""

    def user(self, subject: dict) -> str:
        return f"""Topic: "{subject["topic"]}"

The learner:
{self.learner_text(subject.get("profile"))}

Assessment: {self.to_json(subject["assessment"])}

The whole lesson plan: {self.to_json(subject["plan"])}

Write this page: {self.to_json(subject["page_plan"])}"""


class WriteQuestionsPrompt(Prompt):
    """Subject carries `batch` (`{"id", "cells": [{index, type, difficulty, marks}]}`) and `exclusions` (the questions
    this lesson has already asked)."""

    MAX_EXCLUSIONS = 60
    STEM_CHARS = 160

    def system(self, subject: dict) -> str:
        cells = subject["batch"]["cells"]
        kinds = list(dict.fromkeys(cell["type"] for cell in cells))
        lines = "\n".join(
            f"{number}. {cell['type']}, {cell['difficulty']}, worth {cell['marks']} "
            f"{'mark' if cell['marks'] == 1 else 'marks'}"
            for number, cell in enumerate(cells, start=1)
        )
        return f"""You write questions for the test of a lesson: exactly {len(cells)} questions, ONE for each line \
below, in this order, each of the type and difficulty on its line. What a question is worth is set by the system, \
never by you, but short and long answers need criteria that add up to it.
{lines}

- How to write each type:
{QuestionTypes.guidance(kinds)}
- Test the concepts taught across the three pages (see the plan). Every question names its concept in "concept", \
copied exactly from this list, because the app uses it to point a learner to the page that teaches it:
{self.concepts_line(subject)}
- A question must stand on its own and have one clear right answer (or set of right answers).
- Never repeat a question that was already asked, or ask it again in other words.
- Ids "t1", "t2"… in order.
{self.language_rule(subject.get("profile"))}"""

    ALLOWED = 'Allowed concepts (copy one exactly into "concept")'

    @classmethod
    def concepts_line(cls, subject: dict) -> str:
        return f"{cls.ALLOWED}: {json.dumps(QuestionConcepts.outline(subject['plan']), ensure_ascii=False)}"

    def user(self, subject: dict) -> str:
        return f"""Topic: "{subject["topic"]}"

Assessment: {self.to_json(subject["assessment"])}

The lesson plan: {self.to_json(subject["plan"])}

Questions already asked (do not repeat them): {self.to_json(self.asked(subject.get("exclusions")))}"""

    def asked(self, exclusions) -> list[str]:
        """The newest stems, shortened, so a lesson retaken many times does not grow the prompt without bound."""
        return [stem[: self.STEM_CHARS] for stem in (exclusions or [])[-self.MAX_EXCLUSIONS :]]


class PlanInteractivesPrompt(Prompt):
    def system(self, subject: dict) -> str:
        max_per_page = subject["settings"].get("max_interactives_per_page", 3)
        return f"""You decide which interactive elements make a lesson teach better than text alone.

Kinds:
- interactive_graph: a Mafs coordinate graph the learner manipulates (drag points, sliders) — geometry, functions.
- simulation: a step-by-step or parameter-driven simulation (e.g. binary search stepping with low/mid/high).
- css_animation / svg_diagram: an animation or labelled diagram drawn in code (e.g. cell division stages).
- code_playground: an editable snippet with a Run button (JavaScript only).
- image / gif: a REAL photo, micrograph, diagram or animation found in an openly licensed library (Wikimedia \
Commons, Openverse). Give a short media_query (2-5 plain words, in English).

Rules:
- Every one of the three pages gets at least one, and at most {max_per_page}.
- Each anchors to one existing section id on its page ("anchor_section").
- "purpose" names the concept it teaches and why interaction or a picture helps.
- "description" says concretely what the learner sees and does; it must be buildable in one small React \
component (no network, no external data).
- Prefer real images/GIFs for things that exist in the physical world (organisms, anatomy, apparatus, places); \
prefer simulations and graphs for processes, algorithms and maths.
- Match the learner's learning preference (visual learners get more).
- Ids: short, letters/digits/underscores."""

    def user(self, subject: dict) -> str:
        return f"""Topic: "{subject["topic"]}"

The learner:
{self.learner_text(subject.get("profile"))}

The pages and their sections:
{self.page_outline(subject["pages"])}"""

    @staticmethod
    def page_outline(pages: dict) -> str:
        lines = []
        for key, page in pages.items():
            lines.append(f'Page "{key}": {page["title"]}')
            lines += [f'  - section "{s["id"]}": {s["heading"]}' for s in page["sections"]]
        return "\n".join(lines)


class GenerateInteractivePrompt(Prompt):
    """Subject also carries `spec`, `component_name` and `section` (the anchor section, or None)."""

    KIND_HINTS = {
        "interactive_graph": "Use Mafs for the graph. Let the learner manipulate it (useMovablePoint or a Slider).",
        "simulation": "Keep the state in useState/useReducer. Give Step / Play / Reset controls; Play uses setTimeout "
        "or setInterval cleaned up in useEffect.",
        "css_animation": "Animate with motion (motion.div / motion.svg elements) and let the learner replay it.",
        "svg_diagram": "Draw an inline <svg> with labelled parts; highlight a part on hover or click.",
        "code_playground": "An editable <textarea> of JavaScript and a Run button. Run it only with a tiny "
        "interpreter you write for arithmetic/array expressions, or by showing precomputed outputs for preset "
        "inputs. (eval and Function are forbidden.)",
    }

    def system(self, subject: dict) -> str:
        name = subject["component_name"]
        kind_hint = self.KIND_HINTS.get(subject["spec"]["kind"], "")
        return f"""You write ONE self-contained React function component (TSX) for an interactive lesson.

Contract:
- Declare exactly: function {name}() {{ … }} — no props, no imports, no exports, no render() call.
- It must work on its own: all data inline or from LESSON. Max ~200 lines. Accessible labels on controls.
- Size: full width of its container, height ≤ 480px. Style with Tailwind classes; look good in light and dark mode.
- {kind_hint}

{SCOPE_REFERENCE}"""

    def user(self, subject: dict) -> str:
        spec, name, section = subject["spec"], subject["component_name"], subject.get("section")
        return f"""Topic: "{subject["topic"]}"
Component name: {name}
Spec: {self.to_json(spec)}
It sits in this section of the {spec["page"]} page: {self.to_json(section) if section else "(none)"}

Return spec_id "{spec["id"]}", component_name "{name}" and the tsx."""


class AlignmentPrompt(Prompt):
    def system(self, subject: dict) -> str:
        return f"""You are the final content reviewer of a personalised lesson. Judge it strictly against the \
topic and THIS learner. Score 1-5:
- topic_relevance, level_fit (right depth for this learner), prerequisite_coverage (the introduction teaches \
every required prerequisite), factual_accuracy, interactive_relevance.
List concrete issues. severity "major": factual errors, wrong level, a missing required prerequisite, a test \
question with a wrong answer. Otherwise "minor". target is "page" (target_id = page key), "final_test" \
(target_id = question id), "interactive" or "media" (target_id = spec id). fix_instruction tells the writer \
exactly what to change. Scores below {subject["settings"].get("alignment_min_score", 3)} fail the lesson."""

    def user(self, subject: dict) -> str:
        specs = (subject.get("interactive_plan") or {}).get("specs", [])
        built = set(subject.get("interactives") or {}) | set(subject.get("media") or {})
        media = {
            spec_id: {k: ref.get(k) for k in ("title", "caption", "alt_text", "source")}
            for spec_id, ref in (subject.get("media") or {}).items()
        }
        required = [p["name"] for p in subject.get("prerequisites_to_cover") or []]
        return f"""{self.topic_text(subject)}

The learner:
{self.learner_text(subject.get("profile"))}

Assessment: {self.to_json(subject["assessment"])}
Prerequisites that must be covered: {self.to_json(required)}

Plan: {self.to_json(subject["plan"])}

Pages: {self.to_json(subject["pages"])}

Final test: {self.to_json(subject.get("final_test"))}

Interactives (built: {sorted(built)}): {self.to_json(specs)}

Media: {self.to_json(media)}"""
