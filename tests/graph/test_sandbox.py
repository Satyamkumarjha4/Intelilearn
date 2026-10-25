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
