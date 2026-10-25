"""`LESSON`: the data injected into the sandbox next to the lesson code. Answers are never included.

`LessonSource` reads it from a stored lesson, `LessonData` shapes it, and `LessonDocumentBuilder` is what the API
serves: the code, its version and that data, with the media as signed URLs.
"""

import re
from collections.abc import Callable

from graph.schemas import public_question

from .media_urls import MediaUrlSigner
from .models import Lesson


class LessonSource:
    """The keys `LessonData` reads, built from a stored lesson (the graph's state has the same keys)."""

    @classmethod
    def of(cls, lesson: Lesson) -> dict:
        return {
            "title": lesson.title,
            "topic": lesson.topic,
            "level": lesson.level,
            "plan": lesson.plan,
            "pages": lesson.pages,
            "final_test": lesson.final_test,
            "media": cls.media_refs(lesson),
        }

    @staticmethod
    def media_refs(lesson: Lesson) -> dict[str, dict]:
        """The lesson's stored MediaAssets as MediaRefs keyed by spec id (the shape the graph uses)."""
        return {
            asset.spec_id: {
                "asset_id": str(asset.id),
                "kind": asset.kind,
                "file": asset.file.name,
                "mime_type": asset.mime_type,
                "width": asset.width,
                "height": asset.height,
                "source": asset.source,
                "source_url": asset.source_url,
                "title": asset.title,
                "license": asset.license,
                "attribution": asset.attribution,
                "alt_text": asset.alt_text,
                "caption": asset.caption,
                "verified": asset.verified,
            }
            for asset in lesson.media.all()
        }


class LessonData:
    @staticmethod
    def media_entry(ref: dict, url: str) -> dict:
        return {
            "url": url,
            "kind": ref.get("kind", "image"),
            "alt": ref.get("alt_text") or ref.get("title") or "",
            "caption": ref.get("caption") or "",
            "attribution": ref.get("attribution") or "",
            "license": ref.get("license") or "",
            "source_url": ref.get("source_url") or "",
            "width": ref.get("width") or 0,
            "height": ref.get("height") or 0,
        }

    @classmethod
    def build(cls, source: dict, media_url: Callable[[str], str]) -> dict:
        """`source`: the graph state, or `LessonSource.of(lesson)`. `media_url`: asset id → the URL the page loads."""
        final_test = source.get("final_test") or {"title": "Test", "questions": []}
        plan = source.get("plan") or {}
        media = source.get("media") or {}
        return {
            "title": plan.get("title") or source.get("title") or source.get("topic") or "",
            "topic": source.get("topic") or "",
            "level": plan.get("level") or source.get("level") or "",
            "pages": source.get("pages") or {},
            "final_test": {
                "title": final_test.get("title") or "Test your understanding",
                "questions": [public_question(q) for q in final_test.get("questions", [])],
            },
            "media": {ref["asset_id"]: cls.media_entry(ref, media_url(ref["asset_id"])) for ref in media.values()},
        }


class EmbeddedTest:
    """Lessons made before the final test became its own screen still declare it as a fourth page of their code
    (`{ key: "test", … render: Page_test }`). The viewer hides that page, so the test can only be taken on the
    test screen, once. A repair rebuilds the document from the three content pages, which drops it for good."""

    PAGE = re.compile(r'\{\s*key:\s*"test"\s*,[^}]*\brender:\s*Page_test\b')

    def in_code(self, code: str) -> bool:
        return bool(self.PAGE.search(code))


class LessonDocumentBuilder:
    def __init__(self, signer: MediaUrlSigner | None = None, embedded: EmbeddedTest | None = None):
        self.signer = signer or MediaUrlSigner()
        self.embedded = embedded or EmbeddedTest()

    def build(self, lesson: Lesson) -> dict:
        data = LessonData.build(LessonSource.of(lesson), self.signer.sign)
        return {
            "code": lesson.code,
            "code_version": lesson.code_version,
            "has_embedded_test": self.embedded.in_code(lesson.code),
            "data": data,
        }
