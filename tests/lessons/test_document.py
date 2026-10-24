"""Unit under test: `lessons.document` (`LessonSource`, `LessonData`, `LessonDocumentBuilder`): the `LESSON` data the
sandbox receives next to the lesson code.

Why: it is the line between what the server knows and what a learner's browser (and the generated code) may see.
If a test question's answer, a media file's private path, or an unsigned URL got in, the test could be passed by
reading the data. It is built the same way for the render check and for the browser.

Use cases:
- the data has the title, topic and level (the plan's win), the pages and the media entries keyed by asset id
- the final test's questions are public only: no correct answers, solutions, explanations or reference code
- a missing test or plan gives an empty test and falls back to the lesson's own title
- a media entry carries the URL it is given, alt text (falling back to the title), caption, attribution and licence
- a source built from a stored lesson has its media as refs keyed by spec id
- the document builder returns the code, its version and the data, with media as signed URLs
"""

import pytest
from django.core.files.base import ContentFile
from support.lesson_data import make_final_test, make_pages, make_plan
from support.media import png

from lessons.document import LessonData, LessonDocumentBuilder, LessonSource
from lessons.media_urls import MediaUrlSigner
from lessons.models import Lesson, MediaAsset

pytestmark = pytest.mark.django_db

SOLUTION_KEYS = {
    "correct_index",
    "answer",
    "tolerance",
    "model_answer",
    "key_points",
    "rubric",
    "reference_solution",
    "test_cases",
}


def ref(asset_id="a-1", **extra):
    return {
        "asset_id": asset_id, "kind": "image", "alt_text": "", "title": "Amoeba", "caption": "cap",
        "attribution": "Jane",
        "license": "cc-by-sa", "source_url": "https://c/x", "width": 400, "height": 300,
    } | extra  # fmt: skip


def test_the_data_has_the_title_pages_and_media_keyed_by_asset_id():
    source = {
        "plan": make_plan(),
        "title": "Other",
        "topic": "Binary search",
        "pages": make_pages(),
        "media": {"w": ref()},
    }

    data = LessonData.build(source, lambda asset_id: f"/m/{asset_id}")

    assert (data["title"], data["topic"], data["level"]) == ("Binary search", "Binary search", "beginner")
    assert set(data["pages"]) == {"introduction", "core", "advanced"}
    assert data["media"] == {
        "a-1": {"url": "/m/a-1", "kind": "image", "alt": "Amoeba", "caption": "cap", "attribution": "Jane",
                "license": "cc-by-sa", "source_url": "https://c/x", "width": 400, "height": 300}
    }  # fmt: skip


def test_the_test_questions_are_public_only():
    source = {"final_test": make_final_test()}

    data = LessonData.build(source, str)

    questions = data["final_test"]["questions"]
    assert len(questions) == 10 and all(not SOLUTION_KEYS & set(q) for q in questions)
    assert "explanation" not in str(questions) and all("question" in q for q in questions)


def test_without_a_test_or_plan_the_data_is_empty_but_valid():
    data = LessonData.build({"title": "Fallback", "topic": "t"}, str)

    assert data["title"] == "Fallback" and data["final_test"] == {"title": "Test", "questions": []}
    assert data["pages"] == {} and data["media"] == {}


def test_alt_text_wins_over_the_title_and_a_bare_ref_gets_defaults():
    entry = LessonData.media_entry({"alt_text": "An amoeba splitting", "title": "x"}, "/u")

    assert entry["alt"] == "An amoeba splitting"
    assert LessonData.media_entry({}, "/u") == {
        "url": "/u", "kind": "image", "alt": "", "caption": "", "attribution": "", "license": "",
        "source_url": "", "width": 0, "height": 0,
    }  # fmt: skip


@pytest.fixture
def lesson_with_media(lesson, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    Lesson.objects.filter(pk=lesson.pk).update(
        title="T", level="beginner", plan=make_plan(), pages=make_pages(), final_test=make_final_test(),
        code="render(<X />)", code_version=3,
    )  # fmt: skip
    asset = MediaAsset(
        lesson=lesson, spec_id="widget_core", kind="image", mime_type="image/png", source="wikimedia",
        title="Amoeba", license="cc0", attribution="Jane", caption="cap", width=400, height=300,
    )  # fmt: skip
    asset.file.save("a.png", ContentFile(png()), save=False)
    asset.save()
    lesson.refresh_from_db()
    return lesson, asset


def test_a_source_from_a_stored_lesson_has_its_media_as_refs_keyed_by_spec_id(lesson_with_media):
    lesson, asset = lesson_with_media

    source = LessonSource.of(lesson)

    assert source["title"] == "T" and source["media"]["widget_core"]["asset_id"] == str(asset.id)
    assert (
        source["media"]["widget_core"]["file"].endswith(".png") and source["media"]["widget_core"]["license"] == "cc0"
    )


def test_the_document_has_the_code_its_version_and_signed_media_urls(lesson_with_media):
    lesson, asset = lesson_with_media
    signer = MediaUrlSigner(secret="s", ttl_s=60, clock=lambda: 1000)

    document = LessonDocumentBuilder(signer).build(lesson)

    assert (document["code"], document["code_version"]) == ("render(<X />)", 3)
    url = document["data"]["media"][str(asset.id)]["url"]
    assert url.startswith(f"/api/media/{asset.id}?exp=1060&sig=")
    assert document["data"]["title"] == "Binary search" and len(document["data"]["final_test"]["questions"]) == 10
