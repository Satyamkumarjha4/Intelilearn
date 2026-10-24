"""Runs the Node scripts of the `sandbox/` package in a subprocess.

- check.mjs:        esbuild syntax check, Babel AST security scan, scope contract (and a KaTeX mode for LaTeX)
- render-check.mjs: headless Chromium render of the assembled lesson with every network request blocked

The browser runs the same runtime, so what passes here renders for the learner.
"""

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)


class SandboxError(RuntimeError):
    """The sandbox script itself failed (not the code it checked)."""


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RenderReport:
    ok: bool
    pages: dict[str, list[str]] = field(default_factory=dict)  # page key → errors
    components: dict[str, list[str]] = field(default_factory=dict)  # component name → errors
    security: list[str] = field(default_factory=list)  # blocked network requests etc.

    def as_dict(self) -> dict:
        return {"ok": self.ok, "pages": self.pages, "components": self.components, "security": self.security}


def _format(error: dict) -> str:
    where = f"line {error['line']}:{error.get('column', 0)} " if error.get("line") else ""
    rule = f"[{error['rule']}] " if error.get("rule") else ""
    return f"{where}{rule}{error['message']}".strip()


class SandboxRunner:
    def __init__(self, sandbox_dir: Path | None = None, node: str | None = None):
        self.dir = Path(sandbox_dir or settings.SANDBOX_DIR)
        self.node = node or settings.NODE_BINARY

    def available(self) -> bool:
        return (
            (self.dir / "scripts" / "check.mjs").exists()
            and (self.dir / "node_modules").exists()
            and shutil.which(self.node) is not None
        )

    def render_available(self) -> bool:
        """The render check needs the built runtime (sandbox/dist) and Chromium on top of the check script."""
        return (
            self.available()
            and (self.dir / "dist" / "runtime.js").exists()
            and (self.dir / "scripts" / "render-check.mjs").exists()
        )

    def _run(self, script: str, payload: dict, timeout_s: int) -> dict:
        if not self.available():
            raise SandboxError(
                f"The sandbox is not installed at {self.dir} (run `bun install` there) or node is missing"
            )
        try:
            completed = subprocess.run(  # noqa: S603 (fixed script path, JSON on stdin)
                [self.node, str(self.dir / "scripts" / script)],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=self.dir,
            )
        except subprocess.TimeoutExpired as exc:
            raise SandboxError(f"{script} timed out after {timeout_s}s") from exc
        if completed.returncode not in (0, 1) or not completed.stdout.strip():
            raise SandboxError(f"{script} failed: {completed.stderr.strip()[-1500:]}")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise SandboxError(f"{script} returned invalid JSON: {completed.stdout[:300]}") from exc

    def check_code(
        self, code: str, *, required: list[str] = (), components: list[str] = (), asset_ids: list[str] = ()
    ) -> CheckResult:
        """Static + security + scope check of TSX. `components` are extra names defined elsewhere in the document."""
        result = self._run(
            "check.mjs",
            {
                "mode": "code",
                "code": code,
                "required": list(required),
                "components": list(components),
                "assetIds": list(asset_ids),
            },  # fmt: skip
            timeout_s=settings.SANDBOX_CHECK_TIMEOUT_S,
        )
        return CheckResult(ok=result["ok"], errors=[_format(e) for e in result.get("errors", [])])

    def latex(self, expressions: list[str]) -> list[str]:
        """Messages for the LaTeX expressions KaTeX can't parse. Skipped (with a log line) if no sandbox."""
        if not expressions:
            return []
        if not self.available():
            logger.info("sandbox not installed: skipping the LaTeX check")
            return []
        result = self._run("check.mjs", {"mode": "latex", "items": expressions}, settings.SANDBOX_CHECK_TIMEOUT_S)
        return [f"LaTeX does not parse: {e['item']!r}: {e['message']}" for e in result.get("errors", [])]

    def render_check(self, code: str, data: dict, *, pages: list[str], media_files: dict[str, str]) -> RenderReport:
        """Render every page headlessly. media_files: asset id → local file path (served; all else is blocked)."""
        if not self.render_available():
            raise SandboxError(f"The lesson runtime is not built at {self.dir / 'dist'} (run `bun run build` there)")
        result = self._run(
            "render-check.mjs",
            {
                "code": code,
                "data": data,
                "pages": pages,
                "mediaFiles": media_files,
                "pageTimeoutMs": settings.SANDBOX_PAGE_TIMEOUT_MS,
            },  # fmt: skip
            timeout_s=settings.SANDBOX_RENDER_TIMEOUT_S,
        )
        return RenderReport(
            ok=result["ok"],
            pages=result.get("pages", {}),
            components=result.get("components", {}),
            security=result.get("security", []),
        )
