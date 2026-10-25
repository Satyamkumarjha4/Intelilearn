"""The `runtime_repair` graph: a lesson that crashed in the learner's browser is repaired in place.

load_repair → repair_runtime (runtime.repair → code-fix loop) → assemble_repaired → regression_check → verify_repair
→ save_repair. Any step that cannot go on raises `RepairFailed`: the run ends with its reason, the lesson stays ready
with the code it had, and the learner can ask again. Cheap checks run before the browser one.
"""

from django.db import transaction

from lessons.document import LessonData, LessonSource
from lessons.models import Lesson, LessonVersion, Stage

from ..codegen import DocumentAssembler
from ..context import FlowContext
from ..errors import RepairFailed
from ..prompts import RuntimeRepairPrompt
from ..rendering import PageParts
from ..repair import CodeSignature, RegressionCheck, RepairTarget, RepairTargetLocator
from ..sanitizer import CodeSanitizer
from ..schemas import PAGE_KEYS
from .base import Node
from .build import CodeFixer, RenderCheckNode

assembler = DocumentAssembler()


class LoadRepairNode(Node):
    name = "load_repair"

    def __init__(self, locator: RepairTargetLocator | None = None):
        self.locator = locator or RepairTargetLocator()

    def run(self, state: dict, ctx: FlowContext) -> dict:
        lesson = self.lesson(state)
        if lesson.stage != Stage.READY or not lesson.code_parts:
            raise RepairFailed("The lesson is not in a state that can be repaired.")
        if lesson.code_version != state["expected_code_version"]:
            raise RepairFailed("The lesson changed since the error was reported. Reload it and try again.")
        target = self.locator.locate(state["repair_error"], lesson.code_parts)
        if target is None:
            raise RepairFailed("The error could not be traced to one part of the lesson, so nothing was changed.")
        source = LessonSource.of(lesson)
        return {
            "topic": lesson.topic,
            "plan": source["plan"],
            "pages": source["pages"],
            "final_test": source["final_test"],
            "media": source["media"],
            "snapshot": lesson.config_snapshot,
            "settings": lesson.settings_snapshot,
            "code_parts": lesson.code_parts,
            "repair_target": target.as_dict(),
        }


class RepairRuntimeNode(Node):
    """Asks `runtime.repair` for the broken page or interactive and holds it to the same checks as a first draft."""

    name = "repair_runtime"

    def __init__(self, fixer: CodeFixer | None = None):
        self._fixer = fixer

    @property
    def fixer(self) -> CodeFixer:
        self._fixer = self._fixer or CodeFixer()
        return self._fixer

    def run(self, state: dict, ctx: FlowContext) -> dict:
        target = RepairTarget.from_dict(state["repair_target"])
        parts = state["code_parts"]
        group = "interactives" if target.kind == "component" else "pages"
        old = parts[group][target.key]
        known = sorted(parts["interactives"])
        if target.kind == "component":
            contract, required, components = assembler.component_contract(target.key), [target.key], []
        else:
            used = sorted(set(CodeSignature.USED.findall(old)))
            contract = assembler.page_contract(target.key, used)
            required, components = [assembler.page_component(target.key)], known
        messages = RuntimeRepairPrompt().messages({"code": old, "error": state["repair_error"], "contract": contract})
        draft = ctx.invoke(state, "runtime.repair", messages).output
        code, errors = self.fixer.fix(
            ctx, state, draft, contract=contract, required=required, components=components,
            asset_ids=PageParts.asset_ids(state),
        )  # fmt: skip
        if errors:
            raise RepairFailed(f"The repaired code still fails the checks ({errors[0]}), so nothing was changed.")
        if code == CodeSanitizer().sanitize(old):
            raise RepairFailed("The model returned the same code, so nothing was changed.")
        repaired = {**parts, group: {**parts[group], target.key: code}}
        return {"repaired_parts": repaired}


class AssembleRepairedNode(Node):
    name = "assemble_repaired"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        parts = state["repaired_parts"]
        document = assembler.assemble(parts["interactives"], parts["pages"] | {"test": assembler.test_page()})
        check = ctx.sandbox.check_code(document, required=["LessonDocument"], asset_ids=PageParts.asset_ids(state))
        if check.errors:
            raise RepairFailed(f"The repaired lesson does not pass the code checks ({check.errors[0]}).")
        return {"document_code": document}


class RegressionCheckNode(Node):
    name = "regression_check"

    def __init__(self, check: RegressionCheck | None = None):
        self.check = check or RegressionCheck()

    def run(self, state: dict, ctx: FlowContext) -> dict:
        problems = self.check.problems(state["code_parts"], state["repaired_parts"], state["pages"])
        if problems:
            raise RepairFailed(f"{problems[0]}, so nothing was changed.")
        return {}


class VerifyRepairNode(Node):
    """The repaired document must render in the headless browser with no error on any page or interactive."""

    name = "verify_repair"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        data = LessonData.build(state, media_url=lambda asset_id: f"https://media.invalid/{asset_id}")
        report = ctx.sandbox.render_check(
            state["document_code"], data, pages=[*PAGE_KEYS, "test"], media_files=RenderCheckNode.media_files(state)
        )
        if not report.ok:
            raise RepairFailed(
                f"The repaired lesson still fails in the browser check ({'; '.join(report.problems()[:3])})."
            )
        return {"render_report": report.as_dict()}


class SaveRepairNode(Node):
    """Snapshot the old code as a `LessonVersion`, then store the new one under the next `code_version`."""

    name = "save_repair"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        with transaction.atomic():
            lesson = Lesson.objects.select_for_update().get(pk=state["lesson_id"])
            if lesson.code_version != state["expected_code_version"]:
                raise RepairFailed("The lesson changed while it was being repaired, so nothing was saved.")
            LessonVersion.objects.create(
                lesson=lesson,
                code_version=lesson.code_version,
                code=lesson.code,
                code_parts=lesson.code_parts,
                reason=f"Runtime repair: {state['repair_error'].get('message', '')}"[:300],
            )
            lesson.code = state["document_code"]
            lesson.code_parts = state["repaired_parts"]
            lesson.code_version += 1
            lesson.save(update_fields=["code", "code_parts", "code_version", "updated_at"])
        return {}
