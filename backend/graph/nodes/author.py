"""Stage B: author the lesson.

plan_lesson → validate_plan → Send ×4 (write_page ×3 ‖ write_test) → authored_join (re-send only failed items)
→ plan_interactives → validate_interactive_plan → Send per spec (find_media ‖ build_interactive) → widgets_join
→ alignment_judge → Send fix_item (only flagged items) → alignment_judge … → Stage C
"""

import re

from langgraph.runtime import Runtime
from langgraph.types import Send

from lessons.models import MediaAsset, Stage

from .. import prompts, validators
from ..codegen import sanitize
from ..context import FlowContext, emit, llm, node_settings, warn
from ..schemas import (
    MEDIA_KINDS,
    PAGE_KEYS,
    AlignmentReport,
    FinalTest,
    InteractiveComponent,
    InteractivePlan,
    LessonPlan,
    PageContent,
    component_name,
)
from .common import outcome, route_check, set_stage, update_lesson
from .media_agent import find_media_for

SHARED = ("lesson_id", "topic", "profile", "snapshot", "settings", "assessment", "plan", "pages", "interactive_plan",
          "media", "prerequisites_to_cover", "final_test")  # fmt: skip


def branch(state, **extra) -> dict:
    """The input of a Send branch: shared context plus the item it works on."""
    return {key: state.get(key) for key in SHARED} | extra


def _feedback(state, key) -> list[str]:
    return list((state.get("feedback") or {}).get(key) or [])


def _attempts(state, key) -> int:
    return (state.get("attempts") or {}).get(key, 0)


# --- plan ------------------------------------------------------------------------------------------------------


def plan_lesson(state, runtime: Runtime[FlowContext]):
    set_stage(state["lesson_id"], Stage.GENERATING_LESSON)
    messages = prompts.plan_lesson(state, _feedback(state, "plan"))
    result = llm(runtime, state, "lesson.plan", messages, schema=LessonPlan)
    return {"plan": result.output.model_dump(mode="json"), "attempts": {"plan": 1}}


def validate_plan(state, runtime: Runtime[FlowContext]):
    plan = state["plan"]
    problems = validators.validate_plan(plan, state["settings"], state.get("prerequisites_to_cover") or [])
    if not problems:
        update_lesson(state["lesson_id"], plan=plan, title=plan["title"][:200], level=plan["level"])
    return outcome(state, "plan", "lesson.plan", problems, "plan_lesson", "The lesson plan")


def authoring_sends(state, keys=(*PAGE_KEYS, "test"), fix: dict[str, list[str]] | None = None) -> list[Send]:
    sends = []
    for key in keys:
        feedback = (fix or {}).get(key) or _feedback(state, f"page:{key}" if key != "test" else "test")
        target = "write_test" if key == "test" else "write_page"
        sends.append(Send(target, branch(state, key=key, feedback=feedback)))
    return sends


def after_validate_plan(state):
    route = route_check(state, "plan", ok="fan_out", retry="plan_lesson")
    return authoring_sends(state) if route == "fan_out" else route


# --- pages and test (parallel) ----------------------------------------------------------------------------------


def _generate_page(data: dict, runtime, feedback: list[str]):
    key = data["key"]
    page_plan = next(p for p in data["plan"]["pages"] if p["key"] == key)
    result = llm(runtime, data, "page.generate", prompts.write_page(data, page_plan, feedback), schema=PageContent)
    page = result.output.model_dump(mode="json") | {"key": key}
    return page, validators.validate_page(page, page_plan, latex=runtime.context.sandbox.latex)


def write_page(data, runtime: Runtime[FlowContext]):
    key = data["key"]
    page, problems = _generate_page(data, runtime, data.get("feedback"))
    # Keep the latest version even if it has problems: authored_join decides whether to retry or accept it.
    return {"pages": {key: page}, "feedback": {f"page:{key}": problems}, "attempts": {f"page:{key}": 1}}


def _generate_test(data: dict, runtime, feedback: list[str]):
    result = llm(runtime, data, "test.generate", prompts.write_test(data, feedback), schema=FinalTest)
    test = result.output.model_dump(mode="json")
    return test, validators.validate_final_test(test, data["plan"]["final_test"], latex=runtime.context.sandbox.latex)


def write_test(data, runtime: Runtime[FlowContext]):
    test, problems = _generate_test(data, runtime, data.get("feedback"))
    return {"final_test": test, "feedback": {"test": problems}, "attempts": {"test": 1}}


def _authoring_status(state) -> tuple[list[str], list[str]]:
    """(keys to retry, keys that are out of attempts but still have problems)."""
    retry, exhausted = [], []
    for key in (*PAGE_KEYS, "test"):
        item = f"page:{key}" if key != "test" else "test"
        node_key = "test.generate" if key == "test" else "page.generate"
        if not _feedback(state, item):
            continue
        if _attempts(state, item) < node_settings(state, node_key)["max_attempts"]:
            retry.append(key)
        else:
            exhausted.append(key)
    return retry, exhausted


def authored_join(state, runtime: Runtime[FlowContext]):
    retry, exhausted = _authoring_status(state)
    for key in retry:
        emit({"type": "attempt", "node": "write_test" if key == "test" else f"write_page:{key}",
              "reason": _feedback(state, f"page:{key}" if key != "test" else "test")[0]})  # fmt: skip
    if retry:
        return {}
    warnings = []
    for key in exhausted:
        name = "final test" if key == "test" else f"{key} page"
        problems = _feedback(state, f"page:{key}" if key != "test" else "test")
        warnings += warn(f"The {name} was kept despite: {'; '.join(problems[:3])}")
    update_lesson(state["lesson_id"], pages=state["pages"], final_test=state["final_test"])
    return {"warnings": warnings}


def route_authored(state):
    retry, _ = _authoring_status(state)
    return authoring_sends(state, keys=retry) if retry else "plan_interactives"


# --- interactives and media (parallel) --------------------------------------------------------------------------


def plan_interactives(state, runtime: Runtime[FlowContext]):
    messages = prompts.plan_interactives(state, _feedback(state, "interactive_plan"))
    result = llm(runtime, state, "interactive.plan", messages, schema=InteractivePlan)
    return {"interactive_plan": result.output.model_dump(mode="json"), "attempts": {"interactive_plan": 1}}


def _usable_specs(plan: dict, pages: dict, settings: dict) -> list[dict]:
    """Degrade: keep the specs that are individually valid, at most max per page."""
    kept, per_page, seen = [], {}, set()
    for spec in plan["specs"]:
        page = pages.get(spec["page"]) or {}
        valid = (
            spec["id"] not in seen
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,40}", spec["id"])
            and spec["anchor_section"] in {s["id"] for s in page.get("sections", [])}
            and (spec["kind"] not in MEDIA_KINDS or spec.get("media_query", "").strip())
            and per_page.get(spec["page"], 0) < settings.get("max_interactives_per_page", 3)
        )
        if valid:
            per_page[spec["page"]] = per_page.get(spec["page"], 0) + 1
            seen.add(spec["id"])
            kept.append(spec)
    return kept


def validate_interactive_plan(state, runtime: Runtime[FlowContext]):
    plan = state["interactive_plan"]
    problems = validators.validate_interactive_plan(plan, state["pages"], state["settings"])
    if not problems:
        return {"feedback": {"interactive_plan": []}}
    if _attempts(state, "interactive_plan") < node_settings(state, "interactive.plan")["max_attempts"]:
        emit({"type": "attempt", "node": "plan_interactives", "reason": problems[0]})
        return {"feedback": {"interactive_plan": problems}}
    kept = _usable_specs(plan, state["pages"], state["settings"])
    dropped = len(plan["specs"]) - len(kept)
    warnings = warn(f"Interactive plan kept {len(kept)} of {len(plan['specs'])} items ({dropped} invalid)")
    return {"interactive_plan": {"specs": kept}, "feedback": {"interactive_plan": []}, "warnings": warnings}


def widget_sends(state, spec_ids=None, fix: dict[str, list[str]] | None = None) -> list[Send]:
    sends = []
    for spec in state["interactive_plan"]["specs"]:
        if spec_ids is not None and spec["id"] not in spec_ids:
            continue
        feedback = (fix or {}).get(spec["id"]) or _feedback(state, f"widget:{spec['id']}")
        kind = (state.get("widget_kinds") or {}).get(spec["id"], spec["kind"])
        target = "find_media" if kind in MEDIA_KINDS else "build_interactive"
        sends.append(Send(target, branch(state, key=spec["id"], item=spec | {"kind": kind}, feedback=feedback)))
    return sends


def after_validate_interactive_plan(state):
    if _feedback(state, "interactive_plan"):
        return "plan_interactives"
    return widget_sends(state) or "widgets_join"


def _section(data: dict, spec: dict) -> dict | None:
    page = (data.get("pages") or {}).get(spec["page"]) or {}
    return next((s for s in page.get("sections", []) if s["id"] == spec["anchor_section"]), None)


def build_component(data: dict, spec: dict, runtime, feedback: list[str]) -> tuple[dict, list[str]]:
    """interactive.generate + the sandbox static/security check → (component, problems)."""
    name = component_name(spec["id"])
    messages = prompts.generate_interactive(data, spec, name, _section(data, spec), feedback)
    output: InteractiveComponent = llm(
        runtime, data, "interactive.generate", messages, schema=InteractiveComponent
    ).output
    tsx = sanitize(output.tsx)
    check = runtime.context.sandbox.check_code(tsx, required=[name])
    component = {"spec_id": spec["id"], "component_name": name, "tsx": tsx, "page": spec["page"],
                 "anchor": spec["anchor_section"], "kind": spec["kind"], "purpose": spec["purpose"]}  # fmt: skip
    return component, check.errors


def build_interactive(data, runtime: Runtime[FlowContext]):
    spec = data["item"]
    component, problems = build_component(data, spec, runtime, data.get("feedback"))
    key = f"widget:{spec['id']}"
    update = {"feedback": {key: problems}, "attempts": {key: 1}}
    if not problems:
        update["interactives"] = {spec["id"]: component}
    return update


def find_media(data, runtime: Runtime[FlowContext]):
    spec = data["item"]
    key = f"widget:{spec['id']}"
    ref = find_media_for(data, spec, runtime, data.get("feedback"))
    if ref:
        return {"media": {spec["id"]: ref}, "feedback": {key: []}, "attempts": {key: 1}}
    # No acceptable media: draw it instead, so the lesson never has an empty slot.
    fallback = spec | {"kind": "svg_diagram"}
    warnings = warn(f'No suitable {spec["kind"]} found for "{spec["id"]}": drawing an SVG diagram instead')
    component, problems = build_component(data, fallback, runtime, [])
    update = {"widget_kinds": {spec["id"]: "svg_diagram"}, "feedback": {key: problems}, "attempts": {key: 1},
              "warnings": warnings}  # fmt: skip
    if not problems:
        update["interactives"] = {spec["id"]: component}
    return update


def _widget_status(state) -> tuple[list[str], list[str]]:
    retry, exhausted = [], []
    limit = node_settings(state, "interactive.generate")["max_attempts"]
    for spec in state["interactive_plan"]["specs"]:
        key = f"widget:{spec['id']}"
        if not _feedback(state, key):
            continue
        (retry if _attempts(state, key) < limit else exhausted).append(spec["id"])
    return retry, exhausted


def _store_media(state) -> None:
    for spec_id, ref in (state.get("media") or {}).items():
        MediaAsset.objects.update_or_create(
            id=ref["asset_id"],
            defaults={
                "lesson_id": state["lesson_id"], "spec_id": spec_id, "kind": ref["kind"], "file": ref["file"],
                "mime_type": ref["mime_type"], "width": ref["width"], "height": ref["height"],
                "source": ref["source"], "source_url": ref["source_url"][:1000], "title": ref["title"][:300],
                "license": ref["license"][:40], "attribution": ref["attribution"][:500],
                "alt_text": ref["alt_text"], "caption": ref["caption"], "verified": ref["verified"],
            },
        )  # fmt: skip


def widgets_join(state, runtime: Runtime[FlowContext]):
    retry, exhausted = _widget_status(state)
    if retry:
        return {}
    warnings = []
    for spec_id in exhausted:
        warnings += warn(f'Dropped the interactive "{spec_id}": it kept failing the code checks')
    _store_media(state)
    kinds = state.get("widget_kinds") or {}
    specs = [spec | {"kind": kinds.get(spec["id"], spec["kind"]), "dropped": spec["id"] in exhausted}
             for spec in state["interactive_plan"]["specs"]]  # fmt: skip
    update_lesson(state["lesson_id"], interactive_plan={"specs": specs})
    return {"warnings": warnings}


def route_widgets(state):
    retry, _ = _widget_status(state)
    return widget_sends(state, spec_ids=set(retry)) if retry else "alignment_judge"


# --- alignment judge and targeted fixes --------------------------------------------------------------------------


def alignment_judge(state, runtime: Runtime[FlowContext]):
    report: AlignmentReport = llm(runtime, state, "alignment.judge", prompts.alignment(state),
                                  schema=AlignmentReport).output  # fmt: skip
    settings = state["settings"]
    rounds = _attempts(state, "alignment") + 1
    passed = report.recompute_passed(settings.get("alignment_min_score", 3))
    data = report.model_dump(mode="json") | {"passed": passed, "round": rounds}
    update: dict = {"alignment": data, "attempts": {"alignment": 1}}
    fixable = _fixable_issues(state, data["issues"])
    if passed:
        data["decision"] = "pass"
        update["warnings"] = [f"Content review note: {i['problem']}" for i in data["issues"]][:5]
    elif rounds <= settings.get("alignment_max_rounds", 2) and fixable:
        data["decision"] = "fix"
        emit({"type": "attempt", "node": "alignment_judge", "attempt": rounds + 1,
              "reason": f"{len(fixable)} item(s) to fix: {fixable[0]['problem']}"})  # fmt: skip
    elif not any(issue["severity"] == "major" for issue in data["issues"]):
        data["decision"] = "accept"
        remaining = "; ".join(i["problem"] for i in data["issues"][:3]) or "some scores are below the threshold"
        update["warnings"] = warn(f"Content review: minor issues remain: {remaining}")
    else:
        data["decision"] = "fail"
        majors = [i["problem"] for i in data["issues"] if i["severity"] == "major"]
        update |= {"error": "The content review found problems it could not fix: " + "; ".join(majors[:3]),
                   "failed_node": "alignment_judge", "retry_keys": ["alignment"]}  # fmt: skip
    return update


def _fixable_issues(state, issues: list[dict]) -> list[dict]:
    specs = {s["id"] for s in (state.get("interactive_plan") or {}).get("specs", [])}
    fixable, seen = [], set()
    for issue in issues:
        target, target_id = issue["target"], issue["target_id"]
        if target == "page" and target_id not in PAGE_KEYS:
            continue
        if target in ("interactive", "media") and target_id not in specs:
            continue
        slot = ("final_test", "") if target == "final_test" else (target, target_id)
        if slot not in seen:
            seen.add(slot)
            fixable.append(issue)
    return fixable


def route_alignment(state):
    decision = state["alignment"]["decision"]
    if decision == "fix":
        issues = _fixable_issues(state, state["alignment"]["issues"])
        return [Send("fix_item", branch(state, key=f"{i['target']}:{i['target_id']}", item=i,
                                        feedback=[i["problem"], i["fix_instruction"]]))
                for i in issues]  # fmt: skip
    if decision == "fail":
        return "mark_failed"
    from .build import build_sends

    return build_sends(state)


def fix_item(data, runtime: Runtime[FlowContext]):
    """Redo one flagged item with the judge's instruction. A fix that fails its own checks keeps the old version."""
    issue = data["item"]
    feedback = [f"A reviewer flagged: {issue['problem']}", f"Fix: {issue['fix_instruction']}"]
    target, target_id = issue["target"], issue["target_id"]
    if target == "page":
        page, problems = _generate_page(data | {"key": target_id}, runtime, feedback)
        if problems:
            return {"warnings": warn(f"Could not apply the review fix to the {target_id} page: {problems[0]}")}
        update_lesson(data["lesson_id"])  # touch updated_at; pages are persisted when authoring ends
        return {"pages": {target_id: page}}
    if target == "final_test":
        feedback[0] += f" (question {target_id})"
        test, problems = _generate_test(data, runtime, feedback)
        if problems:
            return {"warnings": warn(f"Could not apply the review fix to the test: {problems[0]}")}
        return {"final_test": test}
    spec = next(s for s in data["interactive_plan"]["specs"] if s["id"] == target_id)
    if spec["kind"] in MEDIA_KINDS and target == "media":
        ref = find_media_for(data, spec, runtime, feedback)
        if ref:
            return {"media": {target_id: ref}}
        return {"warnings": warn(f'Could not find better media for "{target_id}"')}
    component, problems = build_component(data, spec | {"kind": spec.get("kind")}, runtime, feedback)
    if problems:
        return {"warnings": warn(f'Could not apply the review fix to "{target_id}": {problems[0]}')}
    return {"interactives": {target_id: component}}
