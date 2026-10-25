"""Stage C prompts: compiling a page to TSX and repairing code that fails a check."""

from .base import Prompt
from .scope import SCOPE_REFERENCE


class CompilePagePrompt(Prompt):
    """Subject also carries `key`, `components` ({name, anchor, purpose}) and `figures` ({asset, anchor, caption})."""

    def system(self, subject: dict) -> str:
        key = subject["key"]
        return f"""You compile one page of a lesson into a React function component (TSX).

Contract:
- Declare exactly: function Page_{key}() {{ … }} — no props, no imports, no exports, no render() call.
- The content is DATA: read it from LESSON.pages.{key} and render it; never retype, cut or change the text.
  Render EVERY section (the simplest correct way: page.sections.map(s => <Section key={{s.id}} section={{s}}>…
  </Section>)), wrapped in <PageFrame title={{page.title}}>, and end with the page summary.
- Place each interactive component and figure right after its anchor section (as children of that <Section>).
  Use each exactly once. They are already defined; just use them.
- You may add light structure (a short intro callout, a two-column layout on wide screens, a summary card) with
  Tailwind classes, but keep it simple and robust.
- Output ONLY the TSX code, no explanations, no code fences.

{SCOPE_REFERENCE}"""

    def user(self, subject: dict) -> str:
        key = subject["key"]
        placements = [
            f'- <{c["name"]} /> after section "{c["anchor"]}"  ({c["purpose"]})' for c in subject["components"]
        ]
        placements += [
            f'- <Figure asset="{f["asset"]}" /> after section "{f["anchor"]}"  ({f["caption"]})'
            for f in subject["figures"]
        ]
        sections = [{"id": s["id"], "heading": s["heading"]} for s in subject["pages"][key]["sections"]]
        return f"""Page key: {key}
Sections: {self.to_json(sections)}
Place these:
{chr(10).join(placements) or "- (nothing to place)"}"""


class RepairCodePrompt(Prompt):
    """Subject carries `code`, `errors` (list of strings) and `contract`."""

    def system(self, subject: dict) -> str:
        return f"""You fix TSX code for a sandboxed lesson so it passes the checks. Keep everything that works; \
change only what the errors require. Output ONLY the complete corrected code, no explanations, no code fences.

Contract: {subject["contract"]}

{SCOPE_REFERENCE}"""

    def user(self, subject: dict) -> str:
        return "Errors:\n" + "\n".join(f"- {e}" for e in subject["errors"]) + f"\n\nCode:\n{subject['code']}"


class RuntimeRepairPrompt(Prompt):
    """Subject carries `code`, `error` ({message, stack?}) and `contract`."""

    def system(self, subject: dict) -> str:
        return f"""A lesson page crashed in the learner's browser. Fix the TSX so it renders without errors. Keep \
all content and features; change only what is needed. Output ONLY the complete corrected code, no code fences.

Contract: {subject["contract"]}

{SCOPE_REFERENCE}"""

    def user(self, subject: dict) -> str:
        error = subject["error"]
        return f"Error: {error.get('message')}\nStack: {(error.get('stack') or '')[:2000]}\n\nCode:\n{subject['code']}"
