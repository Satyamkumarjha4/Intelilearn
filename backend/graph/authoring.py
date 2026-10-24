"""Writing the lesson's content: one object that asks a model for a page, the test or a widget and checks the result.

The same writer serves the first attempt (the write_* nodes) and a fix after the alignment judge (fix_item), so a
fixed item is held to exactly the rules of a fresh one.
"""

from .context import FlowContext
from .prompts import GenerateInteractivePrompt, WritePagePrompt, WriteTestPrompt
from .sanitizer import CodeSanitizer
from .schemas import FinalTest, InteractiveComponent, PageContent, component_name
from .validators import FinalTestValidator, PageValidator


class ContentWriter:
    def __init__(self, ctx: FlowContext, sanitizer: CodeSanitizer | None = None):
        self.ctx = ctx
        self.sanitizer = sanitizer or CodeSanitizer()

    def page(self, data: dict, key: str, feedback: list[str] | None) -> tuple[dict, list[str]]:
        """→ (the page, the validator's problems with it). The page is returned even when it has problems."""
        plan_page = next(p for p in data["plan"]["pages"] if p["key"] == key)
        messages = WritePagePrompt().messages(data | {"page_plan": plan_page}, feedback)
        output = self.ctx.invoke(data, "page.generate", messages, schema=PageContent).output
        page = output.model_dump(mode="json") | {"key": key}
        return page, PageValidator(self.ctx.sandbox).validate(page, plan_page=plan_page)

    def final_test(self, data: dict, feedback: list[str] | None) -> tuple[dict, list[str]]:
        messages = WriteTestPrompt().messages(data, feedback)
        output = self.ctx.invoke(data, "test.generate", messages, schema=FinalTest).output
        test = output.model_dump(mode="json")
        return test, FinalTestValidator(self.ctx.sandbox).validate(test, spec=data["plan"]["final_test"])

    def component(self, data: dict, spec: dict, feedback: list[str] | None) -> tuple[dict, list[str]]:
        """interactive.generate, then the sandbox's static and security check → (component, problems)."""
        name = component_name(spec["id"])
        section = self.section(data, spec)
        subject = data | {"spec": spec, "component_name": name, "section": section}
        messages = GenerateInteractivePrompt().messages(subject, feedback)
        output: InteractiveComponent = self.ctx.invoke(
            data, "interactive.generate", messages, schema=InteractiveComponent
        ).output
        tsx = self.sanitizer.sanitize(output.tsx)
        check = self.ctx.sandbox.check_code(tsx, required=[name])
        component = {
            "spec_id": spec["id"], "component_name": name, "tsx": tsx, "page": spec["page"],
            "anchor": spec["anchor_section"], "kind": spec["kind"], "purpose": spec["purpose"],
        }  # fmt: skip
        return component, list(check.errors)

    @staticmethod
    def section(data: dict, spec: dict) -> dict | None:
        page = (data.get("pages") or {}).get(spec["page"]) or {}
        return next((s for s in page.get("sections", []) if s["id"] == spec["anchor_section"]), None)
