"""Unit under test: `graph.sanitizer.CodeSanitizer`, which strips what language models wrap around a component.

Why: models add code fences, imports, `export default`, a trailing `render(...)` and `React.useState` out of habit. The
sandbox runs the code with everything already in scope, so each of those is a hard error. Stripping them mechanically
spares a model call per component and keeps the repair loop for real problems.

Use cases:
- takes the code out of a fenced block and ignores the chatter around it
- drops import lines and "use client" directives
- drops a trailing render(...) call and `export default Name;`
- removes the export keyword from a declaration
- removes the React. prefix from hooks (and only from hooks)
- ends with exactly one newline and leaves ordinary code untouched
"""

import pytest

from graph.sanitizer import CodeSanitizer

sanitize = CodeSanitizer().sanitize


def test_takes_the_code_out_of_a_fenced_block_and_ignores_the_chatter():
    reply = "Here is the component:\n```tsx\nfunction A() {\n  return null;\n}\n```\nHope this helps!"

    assert sanitize(reply) == "function A() {\n  return null;\n}\n"


@pytest.mark.parametrize(
    "line",
    [
        'import React from "react";',
        "import { useState } from 'react'",
        '"use client";',
        "'use client';",
        '"use client"',
    ],
)
def test_drops_imports_and_use_client(line):
    assert sanitize(f"{line}\nfunction A() {{}}") == "function A() {}\n"


def test_drops_a_trailing_render_call_and_a_default_export_statement():
    code = "function A() {}\nexport default A;\nrender(<A />);\n"

    assert sanitize(code) == "function A() {}\n"


@pytest.mark.parametrize("declaration", ["export function A() {}", "export default function A() {}"])
def test_removes_the_export_keyword_from_a_declaration(declaration):
    assert sanitize(declaration) == "function A() {}\n"


def test_removes_the_react_prefix_from_hooks_only():
    code = "const [a, setA] = React.useState(0);\nReact.useEffect(() => {});\nconst el = React.createElement('div');"

    assert sanitize(code) == (
        "const [a, setA] = useState(0);\nuseEffect(() => {});\nconst el = React.createElement('div');\n"
    )


def test_ends_with_one_newline_and_leaves_ordinary_code_alone():
    code = "function A() {\n  const x = 1;\n  return <div>{x}</div>;\n}\n\n\n"

    assert sanitize(code) == "function A() {\n  const x = 1;\n  return <div>{x}</div>;\n}\n"
