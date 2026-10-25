"""Stage B prompts: the plan, pages, test, interactives and the alignment judge."""

from .base import Prompt
from .scope import SCOPE_REFERENCE


class PlanLessonPrompt(Prompt):
    def system(self, subject: dict) -> str:
        settings = subject["settings"]
        return f"""You are an expert teacher planning a four-page interactive lesson for one learner.

Pages:
1. "introduction": a hook, why the topic matters, then the PREREQUISITES TO COVER (every one, listed in \
covers_prerequisites and taught in the outline), then an overview of the topic.
2. "core": the core concepts. Start at the assessment's start_point and emphasise the learner's gaps.
3. "advanced": depth, edge cases, complexity and real-world use, scaled to the learner's level.
4. The test (planned below as final_test).

Rules:
- Every outline "concept" appears on exactly ONE page; pages don't overlap or repeat each other.
- 3-6 outline parts per page, in teaching order.
- final_test: {settings.get("final_test_min", 10)}-{settings.get("final_test_max", 15)} questions. type_mix and \
difficulty_mix must each add up to question_count. Use at least 3 question types, choosing ones that suit the \
topic (code only for programming topics; numerical for quantitative topics). A novice gets mostly easy \
questions; an advanced learner mostly medium and hard.
{self.language_rule(subject.get("profile"))}"""

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
        return f"""You write one page of an interactive lesson, following the lesson plan exactly.

- Write the "{key}" page. Follow its outline: one section per outline part, in order, with section \
ids "s1", "s2"…
- Each section: a clear, well-structured Markdown body (at least two paragraphs), key points, and worked examples, \
formulas (LaTeX without $ in "formula.latex"; inline maths in Markdown as $…$) or code snippets where they help.
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


class WriteTestPrompt(Prompt):
    def system(self, subject: dict) -> str:
        spec = subject["plan"]["final_test"]
        return f"""You write the final test of a lesson: exactly {spec["question_count"]} questions.

- Exactly this many of each type: {self.to_json(spec["type_mix"])}
- Exactly this many of each difficulty: {self.to_json(spec["difficulty_mix"])}
- Types: mcq (exactly 4 different options + correct_index), numerical (answer + tolerance + unit), short_answer \
(model_answer + key_points), long_answer (model_answer + rubric), code (language, starter_code, \
reference_solution, 1-5 test_cases).
- Test the concepts taught across the three pages; every question names its concept. No repeated questions.
- Ids "t1", "t2"… Marks: easy 1-2, medium 2-4, hard 4-8.
{self.language_rule(subject.get("profile"))}"""

    def user(self, subject: dict) -> str:
        return f"""Topic: "{subject["topic"]}"

Assessment: {self.to_json(subject["assessment"])}

The lesson plan: {self.to_json(subject["plan"])}"""


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
