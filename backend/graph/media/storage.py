import uuid
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


@dataclass(frozen=True)
class StoredFile:
    asset_id: str
    relative: str  # path under MEDIA_ROOT


class MediaStorage:
    """Writes media under MEDIA_ROOT. Lessons refer to a file by asset id and the API serves it through a signed URL,
    so generated code never sees where it lives."""

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root else None

    @property
    def base(self) -> Path:
        return self.root or Path(settings.MEDIA_ROOT)

    def store(self, lesson_id: str, content: bytes, extension: str) -> StoredFile:
        asset_id = str(uuid.uuid4())
        relative = f"lesson-media/{lesson_id}/{asset_id}.{extension}"
        path = self.base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return StoredFile(asset_id, relative)

    def discard(self, relative: str) -> None:
        (self.base / relative).unlink(missing_ok=True)
