"""Saving the media a flow found."""

from lessons.models import MediaAsset


class MediaAssets:
    """Saves the media the flow found as `MediaAsset` rows (the file is already stored)."""

    @staticmethod
    def persist(lesson_id: str, media: dict[str, dict]) -> None:
        for spec_id, ref in media.items():
            MediaAsset.objects.update_or_create(
                id=ref["asset_id"],
                defaults={
                    "lesson_id": lesson_id, "spec_id": spec_id, "kind": ref["kind"], "file": ref["file"],
                    "mime_type": ref["mime_type"], "width": ref["width"], "height": ref["height"],
                    "source": ref["source"], "source_url": ref["source_url"][:1000], "title": ref["title"][:300],
                    "license": ref["license"][:40], "attribution": ref["attribution"][:500],
                    "alt_text": ref["alt_text"], "caption": ref["caption"], "verified": ref["verified"],
                },
            )  # fmt: skip
