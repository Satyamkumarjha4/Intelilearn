# ruff: noqa: E501  (the widget templates are code samples; long lines read better there)
"""Canned Stage B and C output for the fake LLM: a plan, pages, a test, an interactive plan, widget code and an
alignment report that pass the real validators and the real sandbox check, and compiled pages in the standard layout.
Content is built from what the prompt contains (the topic, the page plan, the lesson plan), so the lesson the
walk-through shows is about what the learner asked for."""

import json
import re

from graph.codegen import DocumentAssembler

TOPICS_WITH_PICTURES = re.compile(r"reproduction|cell|amoeba|biology|photosynthesis|organism|anatomy|ecosystem", re.I)

SIMULATION_TSX = """function {name}() {{
  const items = [2, 5, 8, 12, 16, 23, 38, 56, 72, 91];
  const target = 23;
  const [lo, setLo] = useState(0);
  const [hi, setHi] = useState(items.length - 1);
  const mid = Math.floor((lo + hi) / 2);
  const done = lo > hi || items[mid] === target;
  const step = () => {{
    if (done) return;
    if (items[mid] < target) setLo(mid + 1);
    else setHi(mid - 1);
  }};
  const reset = () => {{ setLo(0); setHi(items.length - 1); }};
  return (
    <div className="flex flex-col gap-3 rounded-lg border p-4">
      <p className="text-sm">Looking for {{target}} in a sorted list. low = {{lo}}, high = {{hi}}, mid = {{mid}}.</p>
      <div className="flex flex-wrap gap-1">
        {{items.map((x, i) => (
          <span key={{i}} className={{"rounded border px-2 py-1 text-sm " + (i === mid && !(lo > hi) ? "bg-primary text-primary-foreground" : i < lo || i > hi ? "opacity-30" : "")}}>{{x}}</span>
        ))}}
      </div>
      <div className="flex gap-2">
        <Button onClick={{step}}>Step</Button>
        <Button variant="outline" onClick={{reset}}>Reset</Button>
      </div>
      <p className="text-sm text-muted-foreground">{{done ? (items[mid] === target ? "Found it at index " + mid : "Not in the list") : "Press Step"}}</p>
    </div>
  );
}}
"""

GRAPH_TSX = """function {name}() {{
  const point = useMovablePoint([1, 1]);
  return (
    <Mafs height={{300}}>
      <Coordinates.Cartesian />
      <Plot.OfX y={{(x) => point.y * Math.sin(x)}} />
      {{point.element}}
    </Mafs>
  );
}}
"""

SVG_TSX = """function {name}() {{
  const [part, setPart] = useState("cell");
  const labels = {{ cell: "The whole cell", nucleus: "The nucleus holds the genes", membrane: "The membrane controls what passes" }};
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-4">
      <svg viewBox="0 0 200 120" className="h-40 w-full" role="img" aria-label="Labelled diagram">
        <ellipse cx="100" cy="60" rx="80" ry="45" fill="none" stroke="currentColor" strokeWidth="3" onClick={{() => setPart("membrane")}} />
        <circle cx="100" cy="60" r="18" fill="currentColor" opacity="0.4" onClick={{() => setPart("nucleus")}} />
      </svg>
      <p className="text-sm">{{labels[part]}}</p>
      <Button variant="outline" onClick={{() => setPart("cell")}}>Reset</Button>
    </div>
  );
}}
"""


class LessonCanned:
    """Mixed into `Canned`: expects `self.topic`, `self.text` (all prompt text) and `self.messages`."""

    # --- helpers ---

    def _json_after(self, marker: str):
        """The JSON value that follows `marker` in the prompt (the prompts embed their inputs as indented JSON)."""
        start = self.text.index(marker) + len(marker)
        decoder = json.JSONDecoder()
        return decoder.raw_decode(self.text[start:].lstrip())[0]

    def _user(self) -> str:
        return self.messages[-1]["content"] if isinstance(self.messages[-1].get("content"), str) else self.text

    # --- Stage B ---

    def build_LessonPlan(self) -> dict:
        topic = self.topic
        required = self._json_after("Prerequisites to cover on the introduction page:")
        names = [p["name"] for p in required]
        parts = {
            "introduction": ["What " + topic + " is", "Why " + topic + " matters", "The vocabulary of " + topic],
            "core": ["The main idea of " + topic, "A worked example of " + topic, "The usual steps of " + topic],
            "advanced": ["Limits of " + topic, "Common mistakes in " + topic, "Where " + topic + " is used"],
        }
        pages = [
            {
                "key": key,
                "title": f"{topic}: {key}",
                "goals": ["Understand the idea", "Apply it once"],
                "outline": [{"concept": c, "heading": c, "notes": f"Explain {c}."} for c in concepts],
                "covers_gaps": [],
                "covers_prerequisites": names if key == "introduction" else [],
            }
            for key, concepts in parts.items()
        ]
        return {
            "title": topic, "level": "intermediate", "summary": f"A lesson on {topic} for this learner.", "pages": pages,
            "final_test": {
                "question_count": 10,
                "type_mix": {"mcq": 4, "numerical": 2, "short_answer": 2, "long_answer": 1, "code": 1},
                "difficulty_mix": {"easy": 4, "medium": 4, "hard": 2},
            },
        }  # fmt: skip

    def build_PageContent(self) -> dict:
        plan_page = self._json_after("Write this page:")
        sections = []
        for number, item in enumerate(plan_page["outline"], start=1):
            concept = item["concept"]
            body = (
                f"{concept} is the focus of this section. "
                + f"The key thing to understand about {concept.lower()} is how it fits the rest of {self.topic}. " * 3
                + "Try it on a small example of your own, then check your reasoning against the worked example below."
            )
            sections.append(
                {
                    "id": f"s{number}",
                    "heading": item["heading"],
                    "body": body,
                    "key_points": [f"{concept}: know what it is.", f"{concept}: know when to use it."],
                    "worked_examples": [
                        {"problem": f"Apply {concept} to a tiny case.", "solution": "Step 1, then step 2."}
                    ],
                    "formulas": [{"latex": "T(n) = O(\\log n)", "explanation": "Cost as the input grows."}]
                    if number == 1
                    else [],
                    "code_snippets": [],
                    "callouts": [{"kind": "tip", "text": f"Say {concept.lower()} out loud once."}],
                }  # fmt: skip
            )
        return {
            "key": plan_page["key"], "title": plan_page["title"], "sections": sections,
            "summary": f"A recap of the {plan_page['key']} page.",
        }  # fmt: skip

    def build_FinalTest(self) -> dict:
        spec = self._json_after("The lesson plan:")["final_test"]
        levels = [d for d, n in spec["difficulty_mix"].items() for _ in range(n)]
        questions, number = [], 0
        for kind, count in spec["type_mix"].items():
            for _ in range(count):
                number += 1
                base = {
                    "id": f"t{number}", "type": kind, "concept": f"{self.topic}: part {number}", "difficulty": levels[number - 1],
                    "marks": 2, "question": f"Test question {number} about {self.topic}?",
                }  # fmt: skip
                extra = {
                    "mcq": {"options": [f"Wrong {number}{c}" for c in "AB"] + [f"Right {number}", f"Wrong {number}C"],
                            "correct_index": 2},
                    "numerical": {"answer": float(number), "tolerance": 0.01, "unit": ""},
                    "short_answer": {"model_answer": f"A good answer to {number}.", "key_points": ["clear"]},
                    "long_answer": {"model_answer": f"A full answer to {number}.", "rubric": ["states the idea"]},
                    "code": {"language": "python", "starter_code": "def solve(xs, target):\n    pass\n",
                             "reference_solution": "def solve(xs, target):\n    return xs.index(target)\n",
                             "test_cases": [{"input": "[1, 2, 3], 2", "expected_output": "1"}]},
                }[kind]  # fmt: skip
                questions.append(base | extra)
        return {"title": f"Test your understanding of {self.topic}", "questions": questions}

    def build_InteractivePlan(self) -> dict:
        sections: dict[str, str] = {}
        page = None
        for line in self.text.splitlines():
            if match := re.match(r'Page "(\w+)":', line):
                page = match.group(1)
            elif page and (match := re.match(r'\s+- section "(\w+)":', line)):
                sections.setdefault(page, match.group(1))
        pictures = bool(TOPICS_WITH_PICTURES.search(self.topic))
        kinds = {
            "introduction": "image" if pictures else "svg_diagram",
            "core": "svg_diagram" if pictures else "simulation",
            "advanced": "svg_diagram" if pictures else "interactive_graph",
        }
        specs = [
            {
                "id": f"{key}_widget", "page": key, "anchor_section": sections.get(key, "s1"), "kind": kind,
                "purpose": f"Shows the main idea of the {key} page better than text does.",
                "description": "A small interactive the learner can try.",
                "media_query": "amoeba binary fission" if kind == "image" else "",
            }
            for key, kind in kinds.items()
        ]  # fmt: skip
        return {"specs": specs}

    def build_InteractiveComponent(self) -> dict:
        name = re.search(r"Component name: (\w+)", self.text).group(1)
        spec = self._json_after("Spec:")
        template = {"simulation": SIMULATION_TSX, "interactive_graph": GRAPH_TSX}.get(spec["kind"], SVG_TSX)
        return {"spec_id": spec["id"], "component_name": name, "tsx": template.format(name=name)}

    def build_AlignmentReport(self) -> dict:
        return {
            "topic_relevance": 5, "level_fit": 4, "prerequisite_coverage": 5, "factual_accuracy": 5,
            "interactive_relevance": 4, "issues": [], "passed": True,
        }  # fmt: skip

    # --- Stage C (text output: no schema, so chosen by the prompt) ---

    PLACEMENT = re.compile(r'^- (<(?:Interactive_\w+|Figure asset="[^"]+") />) after section "([^"]+)"', re.M)

    def for_text(self) -> str:
        """A page compiled the safe way: the standard layout with each interactive and figure after its anchor."""
        if not self.messages[0].get("content", "").startswith("You compile one page of a lesson"):
            raise KeyError("text")
        key = re.search(r"Page key: (\w+)", self._user()).group(1)
        placements: dict[str, list[str]] = {}
        for snippet, anchor in self.PLACEMENT.findall(self._user()):
            placements.setdefault(anchor, []).append(snippet)
        return DocumentAssembler().template_page(key, placements)
