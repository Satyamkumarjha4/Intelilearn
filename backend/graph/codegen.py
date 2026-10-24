"""Deterministic code steps: sanitising LLM output, template pages, and assembling the lesson document.

The assembled document is plain TSX evaluated by the sandbox runtime (sandbox/src/runtime.tsx) with the scope
from sandbox/src/scope. Content is data (`LESSON.pages.<key>`), so pages render it rather than retype it.
"""

import json
import re

PAGE_ORDER = ("introduction", "core", "advanced", "test")
HOOKS = ("useState", "useEffect", "useRef", "useMemo", "useCallback", "useReducer", "useLayoutEffect", "useId")

_FENCE = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.S)


def page_component(key: str) -> str:
    return f"Page_{key}"


def sanitize(code: str) -> str:
    """Strip what LLMs add around a component: code fences, imports/exports, React.-prefixed hooks, render()."""
    if match := _FENCE.search(code):
        code = match.group(1)
    lines = []
    for line in code.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped in ('"use client";', "'use client';", '"use client"'):
            continue
        if re.match(r"^\s*render\(.*\);?\s*$", line):
            continue
        if re.match(r"^\s*export\s+default\s+[A-Za-z_]\w*\s*;?\s*$", line):
            continue  # export default Foo;
        line = re.sub(r"^(\s*)export\s+(default\s+)?", r"\1", line)
        lines.append(line)
    code = "\n".join(lines)
    return re.sub(r"\bReact\.(" + "|".join(HOOKS) + r")\b", r"\1", code).strip() + "\n"


def _jsx_string(value: str) -> str:
    return json.dumps(value)


def template_page(key: str, placements: dict[str, list[str]]) -> str:
    """A page that is guaranteed to render: every section via <Section>, with interactives/figures at anchors.

    placements: section id → JSX snippets to place after that section's body.
    """
    cases = "\n".join(
        f"          {{section.id === {_jsx_string(section_id)} ? (<>{''.join(snippets)}</>) : null}}"
        for section_id, snippets in placements.items()
    )
    return f"""function {page_component(key)}() {{
  const page = LESSON.pages.{key};
  return (
    <PageFrame title={{page.title}}>
      {{page.sections.map((section) => (
        <Section key={{section.id}} section={{section}}>
{cases or "          {null}"}
        </Section>
      ))}}
      <KeyPoints title="Summary" points={{[page.summary]}} />
    </PageFrame>
  );
}}
"""


def test_page() -> str:
    """Page 4 is never left to the LLM: answer capture must be reliable."""
    return """function Page_test() {
  return (
    <PageFrame title={LESSON.final_test.title} subtitle="Answer every question, then submit to see your score.">
      <Assessment test={LESSON.final_test} />
    </PageFrame>
  );
}
"""


def placements_for(key: str, specs: list[dict], built: set[str], media: dict[str, dict]) -> dict[str, list[str]]:
    """Where each built interactive / stored figure goes on a page: {section_id: [jsx, …]}."""
    from .schemas.interactive import component_name

    placed: dict[str, list[str]] = {}
    for spec in specs:
        if spec["page"] != key:
            continue
        if spec["id"] in media:
            snippet = f"<Figure asset={_jsx_string(media[spec['id']]['asset_id'])} />"
        elif spec["id"] in built:
            snippet = f"<{component_name(spec['id'])} />"
        else:
            continue
        placed.setdefault(spec["anchor_section"], []).append(snippet)
    return placed


def assemble(components: dict[str, str], pages: dict[str, str]) -> str:
    """One TSX document: interactives (each behind an error boundary), the four pages, LessonDocument, render().

    Each component's code runs inside its own function scope, so its declaration can keep the plain name while
    the outer binding is the wrapped version the pages use.
    """
    parts = ["// Lesson document assembled by Lesson Crafter. Content comes from LESSON (injected data).\n"]
    for name, code in sorted(components.items()):
        body = "\n".join("  " + line if line else line for line in code.strip().splitlines())
        parts.append(f"const {name} = withBoundary({_jsx_string(name)}, (() => {{\n{body}\n  return {name};\n}})());\n")
    for key in PAGE_ORDER:
        parts.append(pages[key].strip() + "\n")
    titles = {key: "LESSON.final_test.title" if key == "test" else f"LESSON.pages.{key}.title" for key in PAGE_ORDER}
    entries = ",\n".join(
        f"  {{ key: {_jsx_string(key)}, title: {titles[key]}, render: {page_component(key)} }}" for key in PAGE_ORDER
    )
    parts.append(f"const PAGES = [\n{entries},\n];\n")
    parts.append("function LessonDocument() {\n  return <LessonShell pages={PAGES} />;\n}\n")
    parts.append("render(<LessonDocument />);\n")
    return "\n".join(parts)


def page_contract(key: str, components: list[str]) -> str:
    uses = f" It may use these already-defined components: {', '.join(components)}." if components else ""
    return (f"Declare exactly `function {page_component(key)}() {{ … }}` (no props) rendering LESSON.pages.{key} "
            f"with PageFrame and Section.{uses}")  # fmt: skip


def component_contract(name: str) -> str:
    return f"Declare exactly `function {name}() {{ … }}` (no props): one self-contained interactive component."
