"""Strips what language models wrap around a component, so the sandbox sees only the component."""

import re


class CodeSanitizer:
    HOOKS = ("useState", "useEffect", "useRef", "useMemo", "useCallback", "useReducer", "useLayoutEffect", "useId")
    FENCE = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.S)
    DIRECTIVES = ('"use client";', "'use client';", '"use client"')

    def sanitize(self, code: str) -> str:
        """Code fences, imports, `export`, a trailing `render(...)` and `React.`-prefixed hooks removed."""
        if match := self.FENCE.search(code):
            code = match.group(1)
        lines = []
        for line in code.strip().splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped in self.DIRECTIVES:
                continue
            if re.match(r"^\s*render\(.*\);?\s*$", line):
                continue
            if re.match(r"^\s*export\s+default\s+[A-Za-z_]\w*\s*;?\s*$", line):
                continue  # export default Foo;
            lines.append(re.sub(r"^(\s*)export\s+(default\s+)?", r"\1", line))
        code = "\n".join(lines)
        return re.sub(r"\bReact\.(" + "|".join(self.HOOKS) + r")\b", r"\1", code).strip() + "\n"
