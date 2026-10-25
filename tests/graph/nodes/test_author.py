"""Unit under test: the Stage B nodes and routers in `graph.nodes.author` and `graph.nodes.author_routers`: planning,
writing pages and the test in parallel, planning and building interactives and media, and the alignment judge with its
targeted fixes.

Why: Stage B turns an assessment into everything the learner will read. A page that fails its rules must be regenerated
alone, not with its siblings; an item that keeps failing must be kept, degraded or dropped with a warning, never loop;
a fix must be held to the same rules as a first draft and must never make things worse; and no router may send work to
an item that does not exist.

Use cases:
- plan_lesson asks for a LessonPlan; validate_plan saves a valid plan (and its title and level) or asks again, and
  gives up with a readable error when attempts run out
- the plan router fans out three page writers and the test writer, each with the shared context; or retries, or fails
- a page and the test are kept even when they have problems, and the join node decides: wait for a retry, or accept
  with a warning once attempts run out, saving what there is
- the authoring router re-sends only the items that failed, with their problems as feedback
- the interactive plan is regenerated on problems, then degraded to what is usable (within the per-page maximum)
- widgets are sent to the media agent (image/gif) or the code writer, only the failed ones again
- a component is sanitised and checked by the sandbox, and kept only when it passes
- when no media is found the spec is drawn as an SVG diagram, with a warning
- the widgets join saves media and the final specs, drops widgets that kept failing, and reports it
- the alignment judge records its decision (pass, fix, accept, fail); the router sends only the fixable items
- a fix replaces the item when it passes its checks and keeps the old one, with a warning, when it does not
"""

import pytest
from langgraph.types import Send
from support.lesson_data import make_final_test, make_interactive_plan, make_pages, make_plan, make_state

from graph.alignment import AlignmentPolicy
from graph.nodes.author import (
    AlignmentJudgeNode,
    AuthoredJoinNode,
    BuildInteractiveNode,
    FindMediaNode,
    FixItemNode,
    PlanInteractivesNode,
    PlanLessonNode,
    ValidateInteractivePlanNode,
    ValidatePlanNode,
    WidgetsJoinNode,
    WritePageNode,
    WriteTestNode,
)
from graph.nodes.author_routers import (
    AlignmentRouter,
    AuthoringRouter,
    InteractivePlanRouter,
    PlanRouter,
    WidgetRouter,
)
from graph.schemas import InteractivePlan, LessonPlan
from lessons.models import Lesson, MediaAsset, Stage

BAD_PAGE_TEXT = "Too short."


def authored(lesson_state, **extra):
    """The state when Stage B starts writing: assessment, plan, and (later) pages, test and interactive plan."""
    full = make_state()
    keys = ("assessment", "plan", "pages", "final_test", "interactive_plan")
    return lesson_state | {k: full[k] for k in keys} | {"prerequisites_to_cover": []} | extra


def short_page(state, key="core"):
    """A state whose `key` page has a section that is too thin."""
    pages = make_pages()
    pages[key]["sections"][0]["body"] = BAD_PAGE_TEXT
    return state | {"pages": pages}


class TestPlan:
    def test_plan_lesson_asks_for_a_plan_with_the_assessment_and_the_feedback(
        self, lesson, lesson_state, gateway, runtime
    ):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.GENERATING_LESSON)
        gateway.script("lesson.plan", make_plan())
        state = authored(lesson_state, feedback={"plan": ["Plan exactly three pages."]})

        update = PlanLessonNode()(state, runtime)

        assert update == {"plan": make_plan(), "attempts": {"plan": 1}}
        call = gateway.called("lesson.plan")[0]
        assert call.schema is LessonPlan and "Plan exactly three pages." in call.messages[1].content
        assert "Halving the range" in call.messages[1].content  # the assessment's start point

    def test_a_valid_plan_is_saved_with_its_title_and_level(self, lesson, lesson_state, runtime):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.GENERATING_LESSON)

        update = ValidatePlanNode()(authored(lesson_state), runtime)

        assert update == {"feedback": {"plan": []}}
        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.title, stored.level, stored.plan) == ("Binary search", "beginner", make_plan())

    def test_an_invalid_plan_is_not_saved_and_the_problems_are_kept(self, lesson, lesson_state, runtime, events):
        plan = make_plan()
        plan["pages"].pop()

        update = ValidatePlanNode()(authored(lesson_state, plan=plan, attempts={"plan": 1}), runtime)

        assert "Plan exactly three pages" in update["feedback"]["plan"][0] and "error" not in update
        assert Lesson.objects.get(pk=lesson.pk).plan is None
        assert events.of_type("attempt")[0]["node"] == "plan_lesson"

    def test_gives_up_with_a_readable_error_when_attempts_run_out(self, lesson_state, runtime):
        plan = make_plan()
        plan["pages"].pop()

        update = ValidatePlanNode()(authored(lesson_state, plan=plan, attempts={"plan": 2}), runtime)

        assert update["error"].startswith("The lesson plan still failed its checks after 2 attempts")
        assert (update["failed_node"], update["retry_keys"]) == ("plan_lesson", ["plan"])

    def test_the_introduction_must_cover_the_prerequisites_to_cover(self, lesson_state, runtime):
        state = authored(lesson_state, prerequisites_to_cover=[{"name": "Arrays", "why_needed": "x"}])

        update = ValidatePlanNode()(state, runtime)

        assert 'must cover the prerequisite "Arrays"' in update["feedback"]["plan"][0]


class TestPlanRouter:
    def test_fans_out_the_three_pages_and_the_test_with_the_shared_context(self, lesson_state):
        state = authored(lesson_state, feedback={"plan": []})

        sends = PlanRouter()(state)

        assert [(s.node, s.arg["key"]) for s in sends] == [
            ("write_page", "introduction"), ("write_page", "core"), ("write_page", "advanced"), ("write_test", "test"),
        ]  # fmt: skip
        assert all(isinstance(s, Send) and s.arg["plan"] == make_plan() and s.arg["lesson_id"] for s in sends)
        assert all(s.arg["feedback"] == [] for s in sends)

    def test_retries_the_plan_or_fails(self, lesson_state):
        assert PlanRouter()(authored(lesson_state, feedback={"plan": ["bad"]})) == "plan_lesson"
        assert PlanRouter()(authored(lesson_state, feedback={"plan": ["bad"]}, error="gave up")) == "mark_failed"


class TestWriters:
    def branch(self, lesson_state, key, feedback=None, **extra):
        return authored(lesson_state, key=key, feedback=feedback or [], **extra)

    def test_a_page_is_written_with_its_key_and_checked(self, lesson_state, gateway, runtime):
        gateway.script("page.generate", make_pages()["core"])

        update = WritePageNode()(self.branch(lesson_state, "core"), runtime)

        assert update["pages"]["core"]["key"] == "core"
        assert update["feedback"] == {"page:core": []} and update["attempts"] == {"page:core": 1}
        assert "core" in gateway.called("page.generate")[0].messages[0].content

    def test_a_page_with_problems_is_still_kept_for_the_join_to_judge(self, lesson_state, gateway, runtime):
        page = make_pages()["core"]
        page["sections"][0]["body"] = BAD_PAGE_TEXT
        gateway.script("page.generate", page)

        update = WritePageNode()(self.branch(lesson_state, "core"), runtime)

        assert update["pages"]["core"]["sections"][0]["body"] == BAD_PAGE_TEXT
        assert any("too thin" in p for p in update["feedback"]["page:core"])

    def test_the_branch_feedback_reaches_the_model(self, lesson_state, gateway, runtime):
        gateway.script("page.generate", make_pages()["core"])

        WritePageNode()(self.branch(lesson_state, "core", ["Write longer sections."]), runtime)

        assert "- Write longer sections." in gateway.called("page.generate")[0].messages[1].content

    def test_the_test_is_written_and_checked_against_the_plans_spec(self, lesson_state, gateway, runtime):
        test = make_final_test()
        test["questions"].pop()
        gateway.script("test.generate", test)

        update = WriteTestNode()(self.branch(lesson_state, "test"), runtime)

        assert any("exactly 10 questions" in p for p in update["feedback"]["test"])
        assert len(update["final_test"]["questions"]) == 9 and update["attempts"] == {"test": 1}


class TestAuthoredJoin:
    def state(self, lesson_state, bad: tuple[str, ...] = (), attempts: int = 1):
        feedback = {"page:introduction": [], "page:core": [], "page:advanced": [], "test": []}
        for key in bad:
            feedback["test" if key == "test" else f"page:{key}"] = [f"{key} is wrong"]
        counts = {"page:introduction": attempts, "page:core": attempts, "page:advanced": attempts, "test": attempts}
        return authored(lesson_state, feedback=feedback, attempts=counts)

    def test_saves_the_pages_and_the_test_when_everything_is_valid(self, lesson, lesson_state, runtime):
        update = AuthoredJoinNode()(self.state(lesson_state), runtime)

        assert update == {"warnings": []}
        stored = Lesson.objects.get(pk=lesson.pk)
        assert set(stored.pages) == {"introduction", "core", "advanced"} and len(stored.final_test["questions"]) == 10

    def test_waits_for_a_retry_while_attempts_remain(self, lesson, lesson_state, runtime, events):
        update = AuthoredJoinNode()(self.state(lesson_state, bad=("core",)), runtime)

        assert update == {}
        assert Lesson.objects.get(pk=lesson.pk).pages is None
        assert events.of_type("attempt") == [{"type": "attempt", "node": "write_page:core", "reason": "core is wrong"}]

    def test_accepts_what_there_is_with_a_warning_when_attempts_run_out(self, lesson, lesson_state, runtime):
        update = AuthoredJoinNode()(self.state(lesson_state, bad=("advanced", "test"), attempts=2), runtime)

        assert update["warnings"] == [
            "The advanced page was kept despite: advanced is wrong",
            "The final test was kept despite: test is wrong",
        ]
        assert Lesson.objects.get(pk=lesson.pk).pages is not None


class TestAuthoringRouter:
    def test_sends_only_the_items_that_failed_with_their_problems(self, lesson_state):
        feedback = {
            "page:core": ["core is wrong"],
            "test": ["test is wrong"],
            "page:introduction": [],
            "page:advanced": [],
        }
        state = authored(lesson_state, feedback=feedback, attempts={"page:core": 1, "test": 1})

        sends = AuthoringRouter()(state)

        assert [(s.node, s.arg["key"], s.arg["feedback"]) for s in sends] == [
            ("write_page", "core", ["core is wrong"]), ("write_test", "test", ["test is wrong"]),
        ]  # fmt: skip

    def test_goes_on_to_the_interactives_when_nothing_needs_a_retry(self, lesson_state):
        state = authored(lesson_state, feedback={"page:core": ["x"]}, attempts={"page:core": 2})  # out of attempts

        assert AuthoringRouter()(state) == "plan_interactives"


class TestInteractivePlan:
    def test_plan_interactives_asks_for_a_plan_listing_the_sections(self, lesson, lesson_state, gateway, runtime):
        gateway.script("interactive.plan", make_interactive_plan())

        update = PlanInteractivesNode()(authored(lesson_state), runtime)

        assert update == {"interactive_plan": make_interactive_plan(), "attempts": {"interactive_plan": 1}}
        call = gateway.called("interactive.plan")[0]
        assert call.schema is InteractivePlan and 'section "s1"' in call.messages[1].content

    def test_a_valid_plan_clears_the_feedback(self, lesson_state, runtime):
        assert ValidateInteractivePlanNode()(authored(lesson_state), runtime) == {"feedback": {"interactive_plan": []}}

    def test_an_invalid_plan_is_regenerated_while_attempts_remain(self, lesson_state, runtime, events):
        plan = make_interactive_plan()
        plan["specs"][0]["anchor_section"] = "s99"

        update = ValidateInteractivePlanNode()(
            authored(lesson_state, interactive_plan=plan, attempts={"interactive_plan": 1}), runtime
        )

        assert "anchors to section" in update["feedback"]["interactive_plan"][0] and "warnings" not in update
        assert events.of_type("attempt")[0]["node"] == "plan_interactives"

    def test_out_of_attempts_it_keeps_what_is_usable_and_warns(self, lesson_state, runtime):
        plan = make_interactive_plan()
        plan["specs"][0]["anchor_section"] = "s99"
        plan["specs"][1]["kind"] = "image"  # a media spec without a media_query
        state = authored(lesson_state, interactive_plan=plan, attempts={"interactive_plan": 2})

        update = ValidateInteractivePlanNode()(state, runtime)

        assert [s["id"] for s in update["interactive_plan"]["specs"]] == ["widget_advanced"]
        assert update["feedback"] == {"interactive_plan": []}
        assert update["warnings"] == ["Interactive plan kept 1 of 3 items (2 invalid)"]

    def test_degrading_respects_the_maximum_per_page(self, lesson_state, runtime):
        plan = make_interactive_plan()
        first = plan["specs"][0]
        plan["specs"] = [{**first, "id": f"w{n}"} for n in range(4)]
        state = authored(lesson_state, interactive_plan=plan, attempts={"interactive_plan": 2})
        state["settings"] = state["settings"] | {"max_interactives_per_page": 2}

        update = ValidateInteractivePlanNode()(state, runtime)

        assert [s["id"] for s in update["interactive_plan"]["specs"]] == ["w0", "w1"]


class TestWidgetRouters:
    def specs_with_media(self):
        plan = make_interactive_plan()
        plan["specs"][0] |= {"kind": "image", "media_query": "amoeba"}
        return plan

    def test_sends_media_to_the_agent_and_code_to_the_writer(self, lesson_state):
        state = authored(lesson_state, interactive_plan=self.specs_with_media(), feedback={"interactive_plan": []})

        sends = InteractivePlanRouter()(state)

        assert [(s.node, s.arg["key"], s.arg["item"]["kind"]) for s in sends] == [
            ("find_media", "widget_introduction", "image"),
            ("build_interactive", "widget_core", "simulation"),
            ("build_interactive", "widget_advanced", "svg_diagram"),
        ]

    def test_plans_again_on_problems_and_goes_straight_on_without_specs(self, lesson_state):
        assert (
            InteractivePlanRouter()(authored(lesson_state, feedback={"interactive_plan": ["bad"]}))
            == "plan_interactives"
        )
        empty = authored(lesson_state, interactive_plan={"specs": []}, feedback={"interactive_plan": []})
        assert InteractivePlanRouter()(empty) == "widgets_join"

    def test_after_the_join_only_failed_widgets_are_sent_again_with_their_problems(self, lesson_state):
        state = authored(
            lesson_state,
            feedback={"widget:widget_core": ["line 3: bad"], "widget:widget_advanced": []},
            attempts={"widget:widget_core": 1},
        )

        sends = WidgetRouter()(state)

        assert [(s.node, s.arg["key"], s.arg["feedback"]) for s in sends] == [
            ("build_interactive", "widget_core", ["line 3: bad"])
        ]

    def test_a_widget_that_became_an_svg_diagram_is_retried_as_code(self, lesson_state):
        plan = self.specs_with_media()
        state = authored(
            lesson_state, interactive_plan=plan, widget_kinds={"widget_introduction": "svg_diagram"},
            feedback={"widget:widget_introduction": ["bad"]}, attempts={"widget:widget_introduction": 1},
        )  # fmt: skip

        sends = WidgetRouter()(state)

        assert [(s.node, s.arg["item"]["kind"]) for s in sends] == [("build_interactive", "svg_diagram")]

    def test_goes_to_the_alignment_judge_when_no_widget_needs_a_retry(self, lesson_state):
        state = authored(lesson_state, feedback={"widget:widget_core": ["bad"]}, attempts={"widget:widget_core": 2})

        assert WidgetRouter()(state) == "alignment_judge"


class TestBuildInteractive:
    def branch(self, lesson_state, **extra):
        spec = make_interactive_plan()["specs"][1]
        return authored(lesson_state, key=spec["id"], item=spec, feedback=[], **extra)

    def test_a_component_is_sanitised_checked_and_kept(self, lesson_state, gateway, runtime):
        fenced = "```tsx\nfunction Interactive_widget_core() { return null; }\n```"
        gateway.script("interactive.generate", {"spec_id": "widget_core", "component_name": "x", "tsx": fenced})

        update = BuildInteractiveNode()(self.branch(lesson_state), runtime)

        component = update["interactives"]["widget_core"]
        assert component["tsx"] == "function Interactive_widget_core() { return null; }\n"
        assert (component["component_name"], component["page"], component["anchor"]) == (
            "Interactive_widget_core",
            "core",
            "s1",
        )
        assert update["feedback"] == {"widget:widget_core": []} and update["attempts"] == {"widget:widget_core": 1}
        prompt = gateway.called("interactive.generate")[0].messages[1].content
        assert "Component name: Interactive_widget_core" in prompt and "Halving the range" in prompt

    def test_a_component_that_fails_the_sandbox_is_not_kept(self, lesson_state, gateway, runtime, sandbox):
        sandbox.code_errors = ["line 1:0 [forbidden-global] `fetch` is not allowed"]
        gateway.script("interactive.generate", {"spec_id": "widget_core", "component_name": "x", "tsx": "bad"})

        update = BuildInteractiveNode()(self.branch(lesson_state), runtime)

        assert "interactives" not in update
        assert update["feedback"] == {"widget:widget_core": sandbox.code_errors}


class TestFindMedia:
    class Finder:
        def __init__(self, ref):
            self.ref, self.calls = ref, []

        def find(self, ctx, branch, spec, feedback=None):
            self.calls.append((spec["id"], feedback))
            return self.ref

    def branch(self, lesson_state):
        spec = make_interactive_plan()["specs"][0] | {"kind": "image", "media_query": "amoeba"}
        return authored(lesson_state, key=spec["id"], item=spec, feedback=["try a diagram"])

    def test_a_found_ref_is_the_widget(self, lesson_state, runtime):
        ref = {"asset_id": "a1", "caption": "c"}
        finder = self.Finder(ref)

        update = FindMediaNode(finder)(self.branch(lesson_state), runtime)

        assert update == {
            "media": {"widget_introduction": ref}, "feedback": {"widget:widget_introduction": []},
            "attempts": {"widget:widget_introduction": 1},
        }  # fmt: skip
        assert finder.calls == [("widget_introduction", ["try a diagram"])]

    def test_nothing_found_means_an_svg_diagram_instead_with_a_warning(self, lesson_state, gateway, runtime):
        gateway.script(
            "interactive.generate",
            {
                "spec_id": "widget_introduction",
                "component_name": "x",
                "tsx": "function Interactive_widget_introduction() {}",
            },
        )

        update = FindMediaNode(self.Finder(None))(self.branch(lesson_state), runtime)

        assert update["widget_kinds"] == {"widget_introduction": "svg_diagram"}
        assert update["interactives"]["widget_introduction"]["kind"] == "svg_diagram"
        assert update["warnings"] == [
            'No suitable image found for "widget_introduction": drawing an SVG diagram instead'
        ]
        assert "svg_diagram" in gateway.called("interactive.generate")[0].messages[1].content

    def test_a_diagram_that_fails_its_checks_leaves_the_widget_to_be_retried(
        self, lesson_state, gateway, runtime, sandbox
    ):
        sandbox.code_errors = ["bad"]
        gateway.script("interactive.generate", {"spec_id": "w", "component_name": "x", "tsx": "oops"})

        update = FindMediaNode(self.Finder(None))(self.branch(lesson_state), runtime)

        assert "interactives" not in update and update["feedback"] == {"widget:widget_introduction": ["bad"]}


class TestWidgetsJoin:
    def test_waits_while_a_widget_can_be_retried(self, lesson_state, runtime):
        state = authored(lesson_state, feedback={"widget:widget_core": ["bad"]}, attempts={"widget:widget_core": 1})

        assert WidgetsJoinNode()(state, runtime) == {}

    def test_saves_media_and_the_final_specs_and_drops_what_kept_failing(self, lesson, lesson_state, runtime):
        ref = {
            "asset_id": "5a1b6f0e-5d6e-4ac1-9a6f-0a1b2c3d4e5f", "kind": "image", "file": "lesson-media/x/a.png",
            "mime_type": "image/png", "width": 400, "height": 300, "source": "wikimedia", "source_url": "https://c/x",
            "title": "Amoeba", "license": "cc-by-sa", "attribution": "Jane", "alt_text": "alt", "caption": "cap",
            "verified": True,
        }  # fmt: skip
        state = authored(
            lesson_state,
            media={"widget_introduction": ref},
            widget_kinds={"widget_advanced": "svg_diagram"},
            feedback={"widget:widget_core": ["bad"]},
            attempts={"widget:widget_core": 2},
        )

        update = WidgetsJoinNode()(state, runtime)

        assert update == {"warnings": ['Dropped the interactive "widget_core": it kept failing the code checks']}
        asset = MediaAsset.objects.get(spec_id="widget_introduction")
        assert (asset.lesson_id, asset.license, asset.verified, asset.alt_text) == (lesson.id, "cc-by-sa", True, "alt")
        specs = {s["id"]: s for s in Lesson.objects.get(pk=lesson.pk).interactive_plan["specs"]}
        assert specs["widget_core"]["dropped"] is True and specs["widget_introduction"]["dropped"] is False
        assert specs["widget_advanced"]["kind"] == "svg_diagram"

    def test_saving_the_same_media_twice_keeps_one_row(self, lesson, lesson_state, runtime):
        ref = {
            "asset_id": "5a1b6f0e-5d6e-4ac1-9a6f-0a1b2c3d4e5f", "kind": "gif", "file": "f.gif",
            "mime_type": "image/gif", "width": 1, "height": 1, "source": "giphy", "source_url": "", "title": "t",
            "license": "giphy", "attribution": "a", "alt_text": "", "caption": "", "verified": False,
        }  # fmt: skip
        state = authored(lesson_state, media={"widget_core": ref})

        WidgetsJoinNode()(state, runtime)
        WidgetsJoinNode()(state, runtime)

        assert MediaAsset.objects.count() == 1


REPORT = {
    "topic_relevance": 5, "level_fit": 5, "prerequisite_coverage": 5, "factual_accuracy": 5,
    "interactive_relevance": 5, "issues": [], "passed": True,
}  # fmt: skip


def issue(target, target_id, severity="major", problem="needs work"):
    return {
        "target": target,
        "target_id": target_id,
        "severity": severity,
        "problem": problem,
        "fix_instruction": "do X",
    }


class TestAlignment:
    def test_a_good_report_passes_and_notes_become_warnings(self, lesson_state, gateway, runtime):
        gateway.script("alignment.judge", REPORT | {"issues": [issue("page", "core", "minor", "tone")]})

        update = AlignmentJudgeNode()(authored(lesson_state), runtime)

        assert update["alignment"]["decision"] == "pass" and update["attempts"] == {"alignment": 1}
        assert update["warnings"] == ["Content review note: tone"]

    def test_a_report_with_problems_asks_for_fixes_and_announces_the_round(
        self, lesson_state, gateway, runtime, events
    ):
        gateway.script("alignment.judge", REPORT | {"level_fit": 2, "issues": [issue("page", "advanced")]})

        update = AlignmentJudgeNode()(authored(lesson_state), runtime)

        assert update["alignment"]["decision"] == "fix"
        assert events.of_type("attempt")[0]["reason"].startswith("1 item(s) to fix")

    def test_out_of_rounds_with_a_major_issue_fails_the_run(self, lesson_state, gateway, runtime):
        gateway.script("alignment.judge", REPORT | {"issues": [issue("page", "core", problem="wrong fact")]})

        update = AlignmentJudgeNode()(authored(lesson_state, attempts={"alignment": 2}), runtime)

        assert update["error"].endswith("wrong fact")
        assert (update["failed_node"], update["retry_keys"]) == ("alignment_judge", ["alignment"])

    def test_out_of_rounds_with_minor_issues_is_accepted_with_a_warning(self, lesson_state, gateway, runtime):
        gateway.script("alignment.judge", REPORT | {"level_fit": 2, "issues": [issue("page", "core", "minor", "dry")]})

        update = AlignmentJudgeNode()(authored(lesson_state, attempts={"alignment": 2}), runtime)

        assert update["alignment"]["decision"] == "accept" and "dry" in update["warnings"][0]

    def test_the_judge_sees_everything_that_was_authored(self, lesson_state, gateway, runtime):
        gateway.script("alignment.judge", REPORT)

        AlignmentJudgeNode()(authored(lesson_state), runtime)

        user = gateway.called("alignment.judge")[0].messages[1].content
        assert "Halving the range" in user and "Interactives (built:" in user and "Final test" in user


class TestAlignmentRouter:
    def state(self, lesson_state, decision, issues=()):
        return authored(lesson_state, alignment={"decision": decision, "issues": list(issues)})

    def test_fix_sends_only_the_fixable_items(self, lesson_state):
        issues = [issue("page", "core"), issue("page", "ghost"), issue("interactive", "widget_core")]

        sends = AlignmentRouter(on_pass="plan")(self.state(lesson_state, "fix", issues))

        assert [(s.node, s.arg["key"]) for s in sends] == [
            ("fix_item", "page:core"),
            ("fix_item", "interactive:widget_core"),
        ]

    @pytest.mark.parametrize(("decision", "expected"), [("pass", "plan"), ("accept", "plan"), ("fail", "mark_failed")])
    def test_pass_and_accept_go_on_and_fail_ends_the_run(self, lesson_state, decision, expected):
        assert AlignmentRouter(on_pass="plan")(self.state(lesson_state, decision)) == expected

    def test_uses_the_policys_idea_of_fixable(self, lesson_state):
        state = authored(lesson_state)

        assert AlignmentPolicy.fixable(state, [issue("media", "widget_core")]) == [issue("media", "widget_core")]


class TestFixItem:
    def branch(self, lesson_state, item):
        return authored(lesson_state, key="k", item=item, feedback=[])

    def test_a_fixed_page_replaces_the_old_one_and_the_judges_instruction_is_the_feedback(
        self, lesson_state, gateway, runtime
    ):
        better = make_pages()["core"]
        better["summary"] = "A better recap."
        gateway.script("page.generate", better)

        update = FixItemNode()(self.branch(lesson_state, issue("page", "core", problem="Too shallow")), runtime)

        assert update["pages"]["core"]["summary"] == "A better recap."
        prompt = gateway.called("page.generate")[0].messages[1].content
        assert "A reviewer flagged: Too shallow" in prompt and "Fix: do X" in prompt

    def test_a_fix_that_fails_its_checks_keeps_the_old_page_with_a_warning(self, lesson_state, gateway, runtime):
        page = make_pages()["core"]
        page["sections"][0]["body"] = BAD_PAGE_TEXT
        gateway.script("page.generate", page)

        update = FixItemNode()(self.branch(lesson_state, issue("page", "core")), runtime)

        assert "pages" not in update
        assert update["warnings"][0].startswith("Could not apply the review fix to the core page:")

    def test_a_fixed_test_names_the_question(self, lesson_state, gateway, runtime):
        gateway.script("test.generate", make_final_test())

        update = FixItemNode()(self.branch(lesson_state, issue("final_test", "t3")), runtime)

        assert len(update["final_test"]["questions"]) == 10
        assert "(question t3)" in gateway.called("test.generate")[0].messages[1].content

    def test_a_fix_for_the_test_that_fails_its_checks_keeps_the_old_test(self, lesson_state, gateway, runtime):
        bad = make_final_test()
        bad["questions"].pop()
        gateway.script("test.generate", bad)

        update = FixItemNode()(self.branch(lesson_state, issue("final_test", "t3")), runtime)

        assert "final_test" not in update and "Could not apply the review fix to the test" in update["warnings"][0]

    def test_a_fixed_interactive_is_rebuilt_and_checked(self, lesson_state, gateway, runtime):
        gateway.script(
            "interactive.generate",
            {"spec_id": "widget_core", "component_name": "x", "tsx": "function Interactive_widget_core() {}"},
        )

        update = FixItemNode()(self.branch(lesson_state, issue("interactive", "widget_core")), runtime)

        assert update["interactives"]["widget_core"]["component_name"] == "Interactive_widget_core"

    def test_a_failing_interactive_fix_keeps_the_old_component(self, lesson_state, gateway, runtime, sandbox):
        sandbox.code_errors = ["bad code"]
        gateway.script("interactive.generate", {"spec_id": "widget_core", "component_name": "x", "tsx": "oops"})

        update = FixItemNode()(self.branch(lesson_state, issue("interactive", "widget_core")), runtime)

        assert (
            "interactives" not in update and 'Could not apply the review fix to "widget_core"' in update["warnings"][0]
        )

    def test_better_media_replaces_the_old(self, lesson_state, runtime):
        plan = make_interactive_plan()
        plan["specs"][1] |= {"kind": "image", "media_query": "q"}
        ref = {"asset_id": "new"}

        class Finder:
            def find(self, ctx, branch, spec, feedback=None):
                return ref

        state = authored(lesson_state, interactive_plan=plan, key="k", item=issue("media", "widget_core"), feedback=[])

        update = FixItemNode(Finder())(state, runtime)

        assert update == {"media": {"widget_core": ref}}

    def test_no_better_media_keeps_the_old_with_a_warning(self, lesson_state, runtime):
        plan = make_interactive_plan()
        plan["specs"][1] |= {"kind": "image", "media_query": "q"}

        class Finder:
            def find(self, ctx, branch, spec, feedback=None):
                return None

        state = authored(lesson_state, interactive_plan=plan, key="k", item=issue("media", "widget_core"), feedback=[])

        update = FixItemNode(Finder())(state, runtime)

        assert update == {"warnings": ['Could not find better media for "widget_core"']}
