import re


class LicensePolicy:
    """Which licences may be shown and used. Names are normalised first, so 'CC BY-SA 4.0' and 'by-sa' agree."""

    BY_FAMILY = ("by", "by-sa", "by-nd", "by-nc", "by-nc-sa", "by-nc-nd")

    @classmethod
    def normalise(cls, raw: str) -> str:
        """'CC BY-SA 4.0' / 'by-sa' / 'Public domain' → 'cc-by-sa' / 'pdm' / 'cc0' (versions ignored)."""
        value = (raw or "").strip().lower().replace("_", "-")
        if value in ("cc0", "cc-zero") or "cc0" in value or "cc zero" in value:
            return "cc0"
        if value in ("pdm", "pd") or "public domain" in value or value.startswith("pd-"):
            return "pdm"
        value = re.sub(r"^cc[\s-]+", "", value)
        value = re.sub(r"[\s-]*\d+(\.\d+)?.*$", "", value).replace(" ", "-")
        return f"cc-{value}" if value in cls.BY_FAMILY else value

    @classmethod
    def allowed(cls, raw: str, allowed: set[str]) -> bool:
        return cls.normalise(raw) in allowed
