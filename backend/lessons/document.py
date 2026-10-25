"""`LESSON`: the data injected into the sandbox next to the lesson code. Answers are never included."""

from collections.abc import Callable

from graph.schemas import public_question


def _media_entry(ref: dict, url: str) -> dict:
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


def lesson_data(source: dict, media_url: Callable[[str], str]) -> dict:
    """source: graph state (or the same keys built from a Lesson): pages, final_test, media {spec_id: MediaRef}."""
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
        "media": {ref["asset_id"]: _media_entry(ref, media_url(ref["asset_id"])) for ref in media.values()},
    }


def media_refs(lesson) -> dict[str, dict]:
    """The lesson's stored MediaAssets as MediaRefs keyed by spec id (same shape the graph uses)."""
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
        }  # fmt: skip
        for asset in lesson.media.all()
    }


def lesson_source(lesson) -> dict:
    return {
        "title": lesson.title,
        "topic": lesson.topic,
        "level": lesson.level,
        "plan": lesson.plan,
        "pages": lesson.pages,
        "final_test": lesson.final_test,
        "media": media_refs(lesson),
    }
