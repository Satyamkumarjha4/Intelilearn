"""The deterministic parts of a runtime repair: which part of the lesson crashed, and whether a repair lost content."""

import re
from dataclasses import dataclass
from typing import Literal

from .schemas import PAGE_KEYS


@dataclass(frozen=True)
class RepairTarget:
    kind: Literal["component", "page"]
    key: str  # the component's name, or the page key

    def as_dict(self) -> dict:
        return {"kind": self.kind, "key": self.key}

    @classmethod
    def from_dict(cls, data: dict) -> "RepairTarget":
        return cls(**data)


class RepairTargetLocator:
    """Reads a browser error and says which interactive or page to repair.

    A component is named in the error when its boundary caught it (`Interactive_x`); a page is named by the viewer
    (`error.page`) or by its function in the stack (`Page_core`). The final test is not part of the document, so it
    is never a target.
    """

    COMPONENT = re.compile(r"\bInteractive_\w+")
    PAGE = re.compile(r"\bPage_(\w+)")

    def locate(self, error: dict, parts: dict) -> RepairTarget | None:
        components = parts.get("interactives") or {}
        pages = parts.get("pages") or {}
        text = [error.get("message") or "", error.get("stack") or ""]
        for chunk in text:
            for name in self.COMPONENT.findall(chunk):
                if name in components:
                    return RepairTarget("component", name)
        for key in [error.get("page"), *(m for chunk in text for m in self.PAGE.findall(chunk))]:
            if key in PAGE_KEYS and key in pages:
                return RepairTarget("page", key)
        return None


class CodeSignature:
    """What a page's code puts on the screen, as far as can be told without running it: the interactives and figures
    it places, whether it renders the page's sections from the data, and the section ids it names."""

    USED = re.compile(r"<(Interactive_\w+)")
    FIGURE = re.compile(r'<Figure\s+asset=\{?"([^"]+)"')

    @classmethod
    def of(cls, code: str, section_ids: list[str]) -> frozenset[str]:
        tokens = {f"interactive {name}" for name in cls.USED.findall(code)}
        tokens |= {f"figure {asset}" for asset in cls.FIGURE.findall(code)}
        tokens |= {f"section {sid}" for sid in section_ids if f'"{sid}"' in code or f"'{sid}'" in code}
        if re.search(r"\.sections\b", code):
            tokens.add("all sections")
        return frozenset(tokens)


class RegressionCheck:
    """A repair may change how something is drawn, never what the learner gets: the same pages and interactives, and
    everything each page placed before is still placed."""

    def problems(self, before: dict, after: dict, pages: dict) -> list[str]:
        found = []
        for group in ("pages", "interactives"):
            old, new = set(before.get(group) or {}), set(after.get(group) or {})
            if old != new:
                found.append(f"The repair changed the lesson's {group}: {', '.join(sorted(old ^ new))}")
        for key, code in (before.get("pages") or {}).items():
            if key not in (after.get("pages") or {}):
                continue
            sections = [s["id"] for s in (pages.get(key) or {}).get("sections", [])]
            lost = CodeSignature.of(code, sections) - CodeSignature.of(after["pages"][key], sections)
            if lost:
                found.append(f"The repair dropped content from the {key} page: {', '.join(sorted(lost))}")
        return found
