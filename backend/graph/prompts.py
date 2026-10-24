"""Prompt builders, one per LLM node. Each returns LangChain messages; the gateway adds the schema.

Keep the rules here in sync with graph/validators.py: the validator's messages are sent back as feedback,
so the prompt should already state every rule the validator enforces.
"""

import json

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from .schemas.diagnostic import BANDS

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French", "de": "German"}

BAND_MEANINGS = {
    "basic": "vocabulary and the core idea; anyone who has met the topic can answer",
    "easy_moderate": "direct application of the core idea",
    "moderate": "standard problems and typical usage",
    "moderate_hard": "edge cases, trade-offs, analysis",
    "hard": "expert level: only answerable with real mastery, NOT by general knowledge, elimination or wording cues",
}

# What generated TSX may use. Mirrors sandbox/src/scope (and the allow-list in sandbox/scripts/check.mjs).
SCOPE_REFERENCE = """\
Everything below is already in scope. There are NO imports: never write import/export/require.
- React hooks: useState, useEffect, useRef, useMemo, useCallback, useReducer (React is in scope for JSX).
- LESSON: the lesson data. LESSON.pages.<introduction|core|advanced> = {title, summary, sections: [{id, heading,
  body (Markdown), key_points, worked_examples: [{problem, solution}], formulas: [{latex, explanation}],
  code_snippets: [{language, code, explanation}], callouts: [{kind, text}]}]}. LESSON.media[assetId] =
  {url, alt, caption, attribution}. Read content from LESSON; never retype it.
- Layout: <PageFrame title subtitle?>…</PageFrame>; <Section section={sectionObject}>{children shown after the
  body}</Section> renders a whole section (heading, Markdown body, formulas, examples, code, callouts, key points);
  <Markdown>{markdownString}</Markdown>; <Callout kind="note|tip|warning|example">…</Callout>;
  <KeyPoints title? points={string[]} />; <WorkedExample example={{problem, solution}} />;
  <FormulaCard formula={{latex, explanation}} />; <CodeBlock code="…" language="python" />.
- Maths: <InlineMath>{"a^2+b^2"}</InlineMath>, <BlockMath>{"\\\\int_0^1 x\\\\,dx"}</BlockMath> (KaTeX).
- Media: <Figure asset="ASSET_ID" /> is the ONLY way to show an image or GIF.
- Controls: <Button onClick variant="default|outline">…</Button>, <Slider label min max step value onChange={(n)=>…} />.
- Graphs (mafs): Mafs, Coordinates (Coordinates.Cartesian), Plot (Plot.OfX, Plot.OfY, Plot.Parametric), Point,
  Line (Line.Segment, Line.ThroughPoints, Line.PointSlope), Vector, Circle, Ellipse, Polygon, Polyline, Text,
  Theme, Transform, useMovablePoint, vec. Example: <Mafs height={300}><Coordinates.Cartesian />
  <Plot.OfX y={(x) => Math.sin(x)} /></Mafs>.
- Animation (motion): motion.div, motion.circle, motion.rect, motion.path…, AnimatePresence.
- Standard JS: Math, Number, String, Array, Object, JSON, Date, Map, Set, parseInt, parseFloat, isNaN,
  setTimeout/clearTimeout, requestAnimationFrame/cancelAnimationFrame, performance.now, console.
- Styling: Tailwind CSS classes work (light and dark mode: use dark: variants or neutral colours).
FORBIDDEN (the code is rejected): fetch, XMLHttpRequest, WebSocket, EventSource, eval, Function, import(),
window, document, globalThis, localStorage, sessionStorage, indexedDB, cookies, postMessage, navigator,
dangerouslySetInnerHTML, raw <img>/<iframe>/<script>/<link>/<object>/<embed>, any http:// or https:// string,
.constructor / __proto__ / prototype access, setInterval without clearInterval in the useEffect cleanup."""


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1)


def language_rule(profile: dict) -> str:
    code = (profile or {}).get("preferred_language") or "en"
    name = LANGUAGE_NAMES.get(code, code)
    return f"Write all learner-facing text in {name}."


def learner_text(profile: dict) -> str:
    fields = [
        ("Education level", "education_level"),
        ("Grade / year", "grade_or_year"),
        ("Field of study", "field_of_study"),
        ("Learning preference", "learning_preference"),
        ("Goal", "goal"),
        ("Notes from the learner", "notes"),
    ]
    lines = [f"- {label}: {profile[key]}" for label, key in fields if (profile or {}).get(key)]
    return "\n".join(lines) or "- (no profile details)"


def _feedback(feedback: list[str] | None) -> str:
    if not feedback:
        return ""
    items = "\n".join(f"- {item}" for item in feedback)
    return f"\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED. Fix every one of these problems:\n{items}"


def _topic(state) -> str:
    context = state.get("user_context")
    return f'Topic: "{state["topic"]}"' + (f"\nWhat the learner says about it: {context}" if context else "")


# --- Stage A -------------------------------------------------------------------------------------------------


def diagnostic(state, feedback=None) -> list[BaseMessage]:
    settings = state["settings"]
    per_band = settings.get("diagnostic_questions_per_band", 2)
    prereqs = settings.get("prerequisite_question_count", 5)
    bands = "\n".join(f'- "{band}": {BAND_MEANINGS[band]}' for band in BANDS)
    system = f"""You are an expert assessment designer. You write a short diagnostic quiz that reveals what a \
learner already knows about a topic, plus a prerequisite quiz.

DIAGNOSTIC QUIZ: exactly {per_band * len(BANDS)} multiple-choice questions, exactly {per_band} per band, \
easiest band first:
{bands}

Rules:
- Every question probes a DIFFERENT concept of the topic (set "concept"; no two alike). Together they sample the \
whole topic.
- Questions are independent: none depends on, or reveals, the answer of another.
- Exactly 4 options, exactly one correct. Options are plausible, similar in length and style, and all different. \
Never use "all of the above", "none of the above" or "both A and B".
- The correct option's position varies across questions.
- "hard" questions must not be answerable by elimination, general knowledge, or cues in the wording.
- Every question has a 1-3 sentence explanation of the correct answer.
- The learner will also see an "I don't know" option; don't add it yourself.
- Use Markdown for code (`inline`) and LaTeX between $…$ for maths.

PREREQUISITE QUIZ: the {prereqs} most important concepts a learner must know BEFORE this topic (not parts of \
the topic itself), each with "why_needed", and exactly one "basic" question per prerequisite whose \
"prerequisite" field equals that prerequisite's name exactly. Ids: diagnostic "q1".., prerequisite "p1"..

{language_rule(state.get("profile"))}"""
    human = f"""{_topic(state)}

The learner:
{learner_text(state.get("profile"))}

Write the diagnostic bundle.{_feedback(feedback)}"""
    return [SystemMessage(system), HumanMessage(human)]


def diagnostic_review(state, bundle: dict) -> list[BaseMessage]:
    quiz = [{k: q[k] for k in ("id", "band", "concept", "question", "options", "correct_index")}
            for q in bundle["diagnostic"]]  # fmt: skip
    system = """You review diagnostic quizzes. Report only real problems:
- a question that depends on or reveals another question's answer;
- a question whose band is wrong (for example a "hard" question answerable from the wording or by elimination,
  or a "basic" question that needs expert knowledge);
- a wrong or ambiguous correct answer.
Return an empty issues list when the quiz is fine."""
    return [SystemMessage(system), HumanMessage(f"{_topic(state)}\n\nQuiz:\n{_json(quiz)}")]


def _results_text(questions: list[dict], result: dict, answers_key="per_question") -> str:
    rows = []
    for q in questions:
        label = q.get("band") or "prerequisite"
        concept = q.get("concept") or q.get("prerequisite")
        rows.append(f"- [{label}] {concept}: {'correct' if result[answers_key][q['id']] else 'wrong / did not know'}")
    return "\n".join(rows)


def assess_learner(state, diagnostic_questions, prerequisite_questions) -> list[BaseMessage]:
    result = state["diagnostic_result"]
    prereq_result = state.get("prerequisite_result")
    to_cover = [p["name"] for p in state.get("prerequisites_to_cover") or []]
    system = """You assess a learner from their quiz results and profile, for the writers of their lesson.
- level: novice (knows almost nothing), beginner, intermediate, advanced.
- known_concepts / gaps: from the per-concept results. Wrong answers are gaps; "I don't know" is honest, not bad.
- start_point: where the core-concepts page should begin, given what they already know.
- author_notes: concrete guidance on tone, depth, pacing, examples and analogies for this learner.
- prerequisites_to_cover: copy the given list EXACTLY; you may not add or remove items.
- confidence: lower it when the results look inconsistent (hard right but basic wrong suggests guessing)."""
    human = f"""{_topic(state)}

The learner:
{learner_text(state.get("profile"))}

Diagnostic: {result["correct"]}/{result["total"]} correct, {result["dont_know"]} "I don't know". \
Results look {"consistent" if result["consistent"] else "INCONSISTENT (possible guessing)"}.
{_results_text(diagnostic_questions, result)}
"""
    if prereq_result:
        human += f"\nPrerequisite quiz: {prereq_result['correct']}/{prereq_result['total']} correct.\n"
        human += _results_text(prerequisite_questions, prereq_result) + "\n"
    human += f"\nprerequisites_to_cover (copy exactly): {_json(to_cover)}"
    return [SystemMessage(system), HumanMessage(human)]


# --- Mastery path ----------------------------------------------------------------------------------------------

STUDY_INSTRUCTIONS = {
    "cheat_sheet": """Write a CHEAT SHEET: dense, scannable notes that fit on one or two screens.
- For quantitative topics: formulas (kind "formula", LaTeX in "formula", every symbol in "variables") with when
  to use each.
- For theoretical topics: key terms, facts and one-line rules.
- 3-6 sections, 3-8 items each, one or two lines per item. No padding.""",
    "revision_sheet": """Write a REVISION SHEET: longer notes that cover EVERY subtopic of the topic.
- 4-10 subtopics, each with a real paragraph summary, 3-6 key points, worked examples where useful, and the
  common mistakes learners make.
- End with a few final tips for revising.""",
    "practice_sheet": """Write a PRACTICE SHEET of 15-25 questions, ordered easy → medium → hard.
- Mix at least 3 types: mcq (exactly 4 options + correct_index), numerical (answer + tolerance + unit),
  short_answer (model_answer + key_points), long_answer (model_answer + rubric), code (language, starter_code,
  reference_solution, 1-5 test_cases). Use only the types that suit the topic.
- Every question has a concept, difficulty and marks. Ids "t1", "t2"…""",
}


def study_material(state, kind: str, feedback=None) -> list[BaseMessage]:
    concepts = state.get("concepts") or []
    system = f"""You write study material for a learner who ALREADY KNOWS this topic well (they aced a \
diagnostic quiz). Consolidate and sharpen; don't teach from scratch.

{STUDY_INSTRUCTIONS[kind]}

Use Markdown; LaTeX between $…$ for inline maths (in Markdown fields). Be accurate and exam-ready.
{language_rule(state.get("profile"))}"""
    human = f"""{_topic(state)}

The learner:
{learner_text(state.get("profile"))}

Key concepts that must be covered: {_json(concepts)}{_feedback(feedback)}"""
    return [SystemMessage(system), HumanMessage(human)]


# --- Stage B ---------------------------------------------------------------------------------------------------


def plan_lesson(state, feedback=None) -> list[BaseMessage]:
    settings = state["settings"]
    to_cover = state.get("prerequisites_to_cover") or []
    system = f"""You are an expert teacher planning a four-page interactive lesson for one learner.

Pages:
1. "introduction": a hook, why the topic matters, then the PREREQUISITES TO COVER (every one, listed in \
covers_prerequisites and taught in the outline), then an overview of the topic.
2. "core": the core concepts. Start at the assessment's start_point and emphasise the learner's gaps.
3. "advanced": depth, edge cases, complexity and real-world use, scaled to the learner's level.
4. The test (planned below as final_test).

Rules:
- Every outline "concept" appears on exactly ONE page; pages don't overlap or repeat each other.
- 3-6 outline parts per page, in teaching order.
- final_test: {settings.get("final_test_min", 10)}-{settings.get("final_test_max", 15)} questions. type_mix and \
difficulty_mix must each add up to question_count. Use at least 3 question types, choosing ones that suit the \
topic (code only for programming topics; numerical for quantitative topics). A novice gets mostly easy \
questions; an advanced learner mostly medium and hard.
{language_rule(state.get("profile"))}"""
    human = f"""{_topic(state)}

The learner:
{learner_text(state.get("profile"))}

Assessment: {_json(state["assessment"])}

Prerequisites to cover on the introduction page: {_json(to_cover)}{_feedback(feedback)}"""
    return [SystemMessage(system), HumanMessage(human)]


def write_page(branch, page_plan: dict, feedback=None) -> list[BaseMessage]:
    system = f"""You write one page of an interactive lesson, following the lesson plan exactly.

- Write the "{page_plan["key"]}" page. Follow its outline: one section per outline part, in order, with section \
ids "s1", "s2"…
- Each section: a clear, well-structured Markdown body (at least two paragraphs), key points, and worked examples, \
formulas (LaTeX without $ in "formula.latex"; inline maths in Markdown as $…$) or code snippets where they help.
- Pitch it at the learner's level and follow the author notes. Use concrete examples and analogies that fit \
their field and goal.
- Don't teach concepts that belong to other pages (see the full plan); you may refer to them briefly.
- Accurate. No filler.
{language_rule(branch.get("profile"))}"""
    human = f"""Topic: "{branch["topic"]}"

The learner:
{learner_text(branch.get("profile"))}

Assessment: {_json(branch["assessment"])}

The whole lesson plan: {_json(branch["plan"])}

Write this page: {_json(page_plan)}{_feedback(feedback)}"""
    return [SystemMessage(system), HumanMessage(human)]


def write_test(branch, feedback=None) -> list[BaseMessage]:
    spec = branch["plan"]["final_test"]
    system = f"""You write the final test of a lesson: exactly {spec["question_count"]} questions.

- Exactly this many of each type: {_json(spec["type_mix"])}
- Exactly this many of each difficulty: {_json(spec["difficulty_mix"])}
- Types: mcq (exactly 4 different options + correct_index), numerical (answer + tolerance + unit), short_answer \
(model_answer + key_points), long_answer (model_answer + rubric), code (language, starter_code, \
reference_solution, 1-5 test_cases).
- Test the concepts taught across the three pages; every question names its concept. No repeated questions.
- Ids "t1", "t2"… Marks: easy 1-2, medium 2-4, hard 4-8.
{language_rule(branch.get("profile"))}"""
    human = f"""Topic: "{branch["topic"]}"

Assessment: {_json(branch["assessment"])}

The lesson plan: {_json(branch["plan"])}{_feedback(feedback)}"""
    return [SystemMessage(system), HumanMessage(human)]


def _page_outline(pages: dict) -> str:
    lines = []
    for key, page in pages.items():
        lines.append(f'Page "{key}": {page["title"]}')
        lines += [f'  - section "{s["id"]}": {s["heading"]}' for s in page["sections"]]
    return "\n".join(lines)


def plan_interactives(state, feedback=None) -> list[BaseMessage]:
    max_per_page = state["settings"].get("max_interactives_per_page", 3)
    system = f"""You decide which interactive elements make a lesson teach better than text alone.

Kinds:
- interactive_graph: a Mafs coordinate graph the learner manipulates (drag points, sliders) — geometry, functions.
- simulation: a step-by-step or parameter-driven simulation (e.g. binary search stepping with low/mid/high).
- css_animation / svg_diagram: an animation or labelled diagram drawn in code (e.g. cell division stages).
- code_playground: an editable snippet with a Run button (JavaScript only).
- image / gif: a REAL photo, micrograph, diagram or animation found in an openly licensed library (Wikimedia \
Commons, Openverse). Give a short media_query (2-5 plain words, in English).

Rules:
- Every one of the three pages gets at least one, and at most {max_per_page}.
- Each anchors to one existing section id on its page ("anchor_section").
- "purpose" names the concept it teaches and why interaction or a picture helps.
- "description" says concretely what the learner sees and does; it must be buildable in one small React \
component (no network, no external data).
- Prefer real images/GIFs for things that exist in the physical world (organisms, anatomy, apparatus, places); \
prefer simulations and graphs for processes, algorithms and maths.
- Match the learner's learning preference (visual learners get more).
- Ids: short, letters/digits/underscores."""
    human = f"""Topic: "{state["topic"]}"

The learner:
{learner_text(state.get("profile"))}

The pages and their sections:
{_page_outline(state["pages"])}{_feedback(feedback)}"""
    return [SystemMessage(system), HumanMessage(human)]


def media_agent(branch, spec: dict, tools_available: list[str], feedback=None) -> list[BaseMessage]:
    system = f"""You find ONE real, openly licensed {spec["kind"]} for a lesson.

Search with the tools ({", ".join(tools_available)}), try different queries if the first results are poor, \
then call submit_media with 1-3 candidates, best first. Copy file_url, page_url, license and attribution EXACTLY \
as the search tool returned them. Only choose results that clearly show what the lesson needs, suit teaching, \
and are not diagrams full of tiny text. If nothing fits after a few searches, call submit_media with an empty \
list."""
    human = f"""Topic: "{branch["topic"]}"
What the lesson needs: {spec["description"]}
Purpose: {spec["purpose"]}
Suggested query: {spec.get("media_query") or spec["description"]}{_feedback(feedback)}"""
    return [SystemMessage(system), HumanMessage(human)]


def verify_media(branch, spec: dict, candidate: dict, image_b64: str, mime: str) -> list[BaseMessage]:
    text = f"""A lesson on "{branch["topic"]}" needs: {spec["description"]} (purpose: {spec["purpose"]}).
Candidate: "{candidate["title"]}" from {candidate["source"]}.
Does this image clearly show what is needed, and is it appropriate for teaching? Write alt text and a caption."""
    image = {"type": "image", "base64": image_b64, "mime_type": mime}
    return [HumanMessage(content=[{"type": "text", "text": text}, image])]


def generate_interactive(branch, spec: dict, name: str, section: dict | None, feedback=None) -> list[BaseMessage]:
    kind_hint = {
        "interactive_graph": "Use Mafs for the graph. Let the learner manipulate it (useMovablePoint or a Slider).",
        "simulation": "Keep the state in useState/useReducer. Give Step / Play / Reset controls; Play uses setTimeout "
        "or setInterval cleaned up in useEffect.",
        "css_animation": "Animate with motion (motion.div / motion.svg elements) and let the learner replay it.",
        "svg_diagram": "Draw an inline <svg> with labelled parts; highlight a part on hover or click.",
        "code_playground": "An editable <textarea> of JavaScript and a Run button. Run it only with a tiny "
        "interpreter you write for arithmetic/array expressions, or by showing precomputed outputs for preset "
        "inputs. (eval and Function are forbidden.)",
    }.get(spec["kind"], "")
    system = f"""You write ONE self-contained React function component (TSX) for an interactive lesson.

Contract:
- Declare exactly: function {name}() {{ … }} — no props, no imports, no exports, no render() call.
- It must work on its own: all data inline or from LESSON. Max ~200 lines. Accessible labels on controls.
- Size: full width of its container, height ≤ 480px. Style with Tailwind classes; look good in light and dark mode.
- {kind_hint}

{SCOPE_REFERENCE}"""
    human = f"""Topic: "{branch["topic"]}"
Component name: {name}
Spec: {_json(spec)}
It sits in this section of the {spec["page"]} page: {_json(section) if section else "(none)"}

Return spec_id "{spec["id"]}", component_name "{name}" and the tsx.{_feedback(feedback)}"""
    return [SystemMessage(system), HumanMessage(human)]


def alignment(state) -> list[BaseMessage]:
    specs = (state.get("interactive_plan") or {}).get("specs", [])
    built = set(state.get("interactives") or {}) | set(state.get("media") or {})
    media = {spec_id: {k: ref.get(k) for k in ("title", "caption", "alt_text", "source")}
             for spec_id, ref in (state.get("media") or {}).items()}  # fmt: skip
    system = f"""You are the final content reviewer of a personalised lesson. Judge it strictly against the \
topic and THIS learner. Score 1-5:
- topic_relevance, level_fit (right depth for this learner), prerequisite_coverage (the introduction teaches \
every required prerequisite), factual_accuracy, interactive_relevance.
List concrete issues. severity "major": factual errors, wrong level, a missing required prerequisite, a test \
question with a wrong answer. Otherwise "minor". target is "page" (target_id = page key), "final_test" \
(target_id = question id), "interactive" or "media" (target_id = spec id). fix_instruction tells the writer \
exactly what to change. Scores below {state["settings"].get("alignment_min_score", 3)} fail the lesson."""
    human = f"""{_topic(state)}

The learner:
{learner_text(state.get("profile"))}

Assessment: {_json(state["assessment"])}
Prerequisites that must be covered: {_json([p["name"] for p in state.get("prerequisites_to_cover") or []])}

Plan: {_json(state["plan"])}

Pages: {_json(state["pages"])}

Final test: {_json(state.get("final_test"))}

Interactives (built: {sorted(built)}): {_json(specs)}

Media: {_json(media)}"""
    return [SystemMessage(system), HumanMessage(human)]


# --- Stage C ---------------------------------------------------------------------------------------------------


def compile_page(branch, key: str, components: list[dict], figures: list[dict]) -> list[BaseMessage]:
    name = f"Page_{key}"
    placements = [f'- <{c["name"]} /> after section "{c["anchor"]}"  ({c["purpose"]})' for c in components]
    placements += [f'- <Figure asset="{f["asset"]}" /> after section "{f["anchor"]}"  ({f["caption"]})'
                   for f in figures]  # fmt: skip
    system = f"""You compile one page of a lesson into a React function component (TSX).

Contract:
- Declare exactly: function {name}() {{ … }} — no props, no imports, no exports, no render() call.
- The content is DATA: read it from LESSON.pages.{key} and render it; never retype, cut or change the text.
  Render EVERY section (the simplest correct way: page.sections.map(s => <Section key={{s.id}} section={{s}}>…
  </Section>)), wrapped in <PageFrame title={{page.title}}>, and end with the page summary.
- Place each interactive component and figure right after its anchor section (as children of that <Section>).
  Use each exactly once. They are already defined; just use them.
- You may add light structure (a short intro callout, a two-column layout on wide screens, a summary card) with
  Tailwind classes, but keep it simple and robust.
- Output ONLY the TSX code, no explanations, no code fences.

{SCOPE_REFERENCE}"""
    human = f"""Page key: {key}
Sections: {_json([{"id": s["id"], "heading": s["heading"]} for s in branch["pages"][key]["sections"]])}
Place these:
{chr(10).join(placements) or "- (nothing to place)"}"""
    return [SystemMessage(system), HumanMessage(human)]


def repair_code(code: str, errors: list[str], contract: str) -> list[BaseMessage]:
    system = f"""You fix TSX code for a sandboxed lesson so it passes the checks. Keep everything that works; \
change only what the errors require. Output ONLY the complete corrected code, no explanations, no code fences.

Contract: {contract}

{SCOPE_REFERENCE}"""
    human = "Errors:\n" + "\n".join(f"- {e}" for e in errors) + f"\n\nCode:\n{code}"
    return [SystemMessage(system), HumanMessage(human)]


def runtime_repair(code: str, error: dict, contract: str) -> list[BaseMessage]:
    system = f"""A lesson page crashed in the learner's browser. Fix the TSX so it renders without errors. Keep \
all content and features; change only what is needed. Output ONLY the complete corrected code, no code fences.

Contract: {contract}

{SCOPE_REFERENCE}"""
    human = f"Error: {error.get('message')}\nStack: {(error.get('stack') or '')[:2000]}\n\nCode:\n{code}"
    return [SystemMessage(system), HumanMessage(human)]
