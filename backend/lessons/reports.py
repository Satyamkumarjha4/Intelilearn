"""A plain-text report of a lesson for the `flow show` command: everything an operator needs to judge what the flow
produced, section by section. Each section is a small class, so a stage adds its own without touching the others."""

from abc import ABC, abstractmethod

from .models import Lesson, QuizAttempt


class ReportSection(ABC):
    @abstractmethod
    def lines(self, lesson: Lesson) -> list[str]: ...


class HeaderSection(ReportSection):
    def lines(self, lesson: Lesson) -> list[str]:
        lines = [
            f"{lesson.topic}  [{lesson.id}]",
            f"  owner: {lesson.owner.email}   stage: {lesson.stage}   route: {lesson.route or '-'}   "
            f"level: {lesson.level or '-'}",
        ]
        if lesson.user_context:
            lines.append(f"  context: {lesson.user_context}")
        if lesson.error:
            lines.append(f"  ERROR: {lesson.error}")
        return lines


class QuizSection(ReportSection):
    def lines(self, lesson: Lesson) -> list[str]:
        lines = []
        for attempt in QuizAttempt.objects.filter(quiz__lesson=lesson).select_related("quiz").order_by("submitted_at"):
            result = attempt.result
            bands = "  ".join(f"{band} {right}/{total}" for band, (right, total) in result["by_band"].items())
            lines.append(
                f"  {attempt.quiz.kind} quiz: {result['correct']}/{result['total']} correct, "
                f"{result['dont_know']} don't know" + (f"   ({bands})" if bands else "")
            )
            if not result.get("consistent", True):
                lines.append("    (results look inconsistent: possible guessing)")
        return lines


class AssessmentSection(ReportSection):
    def lines(self, lesson: Lesson) -> list[str]:
        assessment = lesson.assessment
        if not assessment:
            return []
        lines = [f"  assessment: {assessment['level']} (confidence {assessment['confidence']})"]
        lines.append(f"    start at: {assessment['start_point']}")
        for label, key in (("knows", "known_concepts"), ("gaps", "gaps")):
            if assessment[key]:
                lines.append(f"    {label}: {', '.join(assessment[key])}")
        if lesson.prerequisites_to_cover:
            lines.append("    prerequisites to cover: " + ", ".join(p["name"] for p in lesson.prerequisites_to_cover))
        return lines


class PlanSection(ReportSection):
    def lines(self, lesson: Lesson) -> list[str]:
        plan = lesson.plan
        if not plan:
            return []
        spec = plan["final_test"]
        lines = [f"  plan: {plan['title']} ({plan['level']}); {plan['summary']}"]
        for page in plan["pages"]:
            concepts = ", ".join(item["concept"] for item in page["outline"])
            covers = (
                f" [prerequisites: {', '.join(page['covers_prerequisites'])}]" if page["covers_prerequisites"] else ""
            )
            lines.append(f"    {page['key']}: {concepts}{covers}")
        mix = ", ".join(f"{n} {kind}" for kind, n in spec["type_mix"].items() if n)
        lines.append(f"    test: {spec['question_count']} questions ({mix})")
        return lines


class PagesSection(ReportSection):
    def lines(self, lesson: Lesson) -> list[str]:
        lines = []
        for key, page in (lesson.pages or {}).items():
            words = sum(len(s["body"].split()) for s in page["sections"])
            headings = "; ".join(s["heading"] for s in page["sections"])
            lines.append(f"  page {key}: {page['title']}: {len(page['sections'])} sections, {words} words ({headings})")
        test = lesson.final_test
        if test:
            kinds: dict[str, int] = {}
            for question in test["questions"]:
                kinds[question["type"]] = kinds.get(question["type"], 0) + 1
            mix = ", ".join(f"{n} {kind}" for kind, n in kinds.items())
            lines.append(f"  test: {len(test['questions'])} questions ({mix})")
        return lines


class InteractivesSection(ReportSection):
    def lines(self, lesson: Lesson) -> list[str]:
        specs = (lesson.interactive_plan or {}).get("specs", [])
        if not specs:
            return []
        assets = {a.spec_id: a for a in lesson.media.all()}
        lines = ["  interactives:"]
        for spec in specs:
            state = "dropped" if spec.get("dropped") else ("media" if spec["id"] in assets else "built")
            lines.append(f"    {spec['id']} ({spec['page']}, {spec['kind']}, {state}): {spec['purpose']}")
        for asset in assets.values():
            lines.append(
                f"    media {asset.spec_id}: {asset.kind} {asset.width}x{asset.height} from {asset.source}, "
                f"{asset.license}, by {asset.attribution}" + (", verified" if asset.verified else "")
            )
        return lines


class CodeSection(ReportSection):
    def lines(self, lesson: Lesson) -> list[str]:
        if not lesson.code:
            return []
        parts = lesson.code_parts or {}
        lines = [
            f"  code: version {lesson.code_version}, {len(lesson.code):,} characters, "
            f"{len(parts.get('pages', {}))} pages, {len(parts.get('interactives', {}))} interactives"
        ]
        if lesson.runtime_repairs:
            lines.append(f"    runtime repairs requested: {lesson.runtime_repairs}")
        lines += [f"    kept v{v.code_version}: {v.reason or 'no reason'}" for v in lesson.versions.all()]
        return lines


class MaterialsSection(ReportSection):
    @staticmethod
    def size(kind: str, content: dict) -> str:
        if kind == "cheat_sheet":
            items = sum(len(section["items"]) for section in content["sections"])
            return f"{items} items in {len(content['sections'])} sections"
        if kind == "revision_sheet":
            return f"{len(content['subtopics'])} subtopics"
        return f"{len(content['questions'])} questions"

    def lines(self, lesson: Lesson) -> list[str]:
        lines = []
        for material in lesson.materials.all():
            content = material.content
            size = {
                "cheat_sheet": lambda c: (
                    f"{sum(len(s['items']) for s in c['sections'])} items in {len(c['sections'])} sections"
                ),
                "revision_sheet": lambda c: f"{len(c['subtopics'])} subtopics",
                "practice_sheet": lambda c: f"{len(c['questions'])} questions",
            }[material.kind](content)
            lines.append(f"  {material.kind}: {content['title']} ({size})")
        return lines


class RunsSection(ReportSection):
    def lines(self, lesson: Lesson) -> list[str]:
        runs = list(lesson.runs.order_by("created_at"))
        lines = [f"  runs: {len(runs)}"] if runs else []
        lines += [f"    {run.created_at:%H:%M:%S} {run.graph}/{run.trigger}: {run.status}" for run in runs[-5:]]
        return lines


class WarningsSection(ReportSection):
    def lines(self, lesson: Lesson) -> list[str]:
        return ["  warnings:", *[f"    - {w}" for w in lesson.warnings]] if lesson.warnings else []


class LessonReport:
    def __init__(self, sections: list[ReportSection] | None = None):
        self.sections = sections or [
            HeaderSection(),
            QuizSection(),
            AssessmentSection(),
            PlanSection(),
            PagesSection(),
            InteractivesSection(),
            CodeSection(),
            MaterialsSection(),
            WarningsSection(),
            RunsSection(),
        ]

    def lines(self, lesson: Lesson) -> list[str]:
        return [line for section in self.sections for line in section.lines(lesson)]
