"""The lesson document: template pages, the test page and the assembly of everything into one TSX document.

The assembled document is plain TSX evaluated by the sandbox runtime (sandbox/src/runtime.tsx) with the scope from
sandbox/src/scope. Content is data (`LESSON.pages.<key>`), so pages render it rather than retype it.
"""

import json

from .schemas.interactive import component_name


class DocumentAssembler:
    PAGE_ORDER = ("introduction", "core", "advanced", "test")

    @staticmethod
    def page_component(key: str) -> str:
        return f"Page_{key}"

    @staticmethod
    def jsx_string(value: str) -> str:
        return json.dumps(value)

    def template_page(self, key: str, placements: dict[str, list[str]]) -> str:
        """A page that is guaranteed to render: every section via <Section>, with interactives and figures at their
        anchors. `placements`: section id → JSX snippets to place after that section's body."""
        cases = "\n".join(
            f"          {{section.id === {self.jsx_string(section_id)} ? (<>{''.join(snippets)}</>) : null}}"
            for section_id, snippets in placements.items()
        )
        return f"""function {self.page_component(key)}() {{
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

    @staticmethod
    def test_page() -> str:
        """Page 4 is never left to the model: answer capture must be reliable."""
        return """function Page_test() {
  return (
    <PageFrame title={LESSON.final_test.title} subtitle="Answer every question, then submit to see your score.">
      <Assessment test={LESSON.final_test} />
    </PageFrame>
  );
}
"""

    def placements_for(
        self, key: str, specs: list[dict], built: set[str], media: dict[str, dict]
    ) -> dict[str, list[str]]:
        """Where each built interactive and stored figure goes on a page: {section_id: [jsx, …]}."""
        placed: dict[str, list[str]] = {}
        for spec in specs:
            if spec["page"] != key:
                continue
            if spec["id"] in media:
                snippet = f"<Figure asset={self.jsx_string(media[spec['id']]['asset_id'])} />"
            elif spec["id"] in built:
                snippet = f"<{component_name(spec['id'])} />"
            else:
                continue
            placed.setdefault(spec["anchor_section"], []).append(snippet)
        return placed

    def assemble(self, components: dict[str, str], pages: dict[str, str]) -> str:
        """One TSX document: the interactives (each behind an error boundary), the four pages, `LessonDocument`, and
        `render()`. Each component's code runs inside its own function scope, so its declaration keeps the plain name
        while the outer binding is the wrapped version the pages use."""
        parts = ["// Lesson document assembled by Lesson Crafter. Content comes from LESSON (injected data).\n"]
        for name, code in sorted(components.items()):
            body = "\n".join("  " + line if line else line for line in code.strip().splitlines())
            wrapper = (
                f"const {name} = withBoundary({self.jsx_string(name)}, (() => {{\n{body}\n  return {name};\n}})());\n"
            )
            parts.append(wrapper)
        for key in self.PAGE_ORDER:
            parts.append(pages[key].strip() + "\n")
        titles = {k: "LESSON.final_test.title" if k == "test" else f"LESSON.pages.{k}.title" for k in self.PAGE_ORDER}
        entries = ",\n".join(
            f"  {{ key: {self.jsx_string(k)}, title: {titles[k]}, render: {self.page_component(k)} }}"
            for k in self.PAGE_ORDER
        )
        parts.append(f"const PAGES = [\n{entries},\n];\n")
        parts.append("function LessonDocument() {\n  return <LessonShell pages={PAGES} />;\n}\n")
        parts.append("render(<LessonDocument />);\n")
        return "\n".join(parts)

    def page_contract(self, key: str, components: list[str]) -> str:
        uses = f" It may use these already-defined components: {', '.join(components)}." if components else ""
        return (
            f"Declare exactly `function {self.page_component(key)}() {{ … }}` (no props) rendering "
            f"LESSON.pages.{key} with PageFrame and Section.{uses}"
        )

    @staticmethod
    def component_contract(name: str) -> str:
        return f"Declare exactly `function {name}() {{ … }}` (no props): one self-contained interactive component."
