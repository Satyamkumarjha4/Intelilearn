"""Unit under test: `graph.media.licenses.LicensePolicy`, which normalises licence names and decides which may be used.

Why: lesson media is shown with attribution to learners. Using something whose licence we misread, or refusing
everything because "CC BY-SA 4.0" did not match "cc-by-sa", leaves lessons with either unlicensed images or none.

Use cases:
- common spellings of the same licence normalise to one name, ignoring versions and case
- public domain and CC0 variants normalise to pdm and cc0
- unknown licences are kept as written (lowercased) so they fail the allow-list instead of being guessed
- a licence is allowed only if its normalised name is in the allow-list
"""

import pytest

from graph.media import LicensePolicy


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CC BY-SA 4.0", "cc-by-sa"),
        ("cc-by-sa-3.0", "cc-by-sa"),
        ("by-sa", "cc-by-sa"),
        ("CC BY 2.0", "cc-by"),
        ("by", "cc-by"),
        ("CC BY-NC-ND 4.0", "cc-by-nc-nd"),
        ("CC0 1.0", "cc0"),
        ("cc0", "cc0"),
        ("CC Zero", "cc0"),
        ("Public domain", "pdm"),
        ("PD-old", "pdm"),
        ("pdm", "pdm"),
        ("GFDL", "gfdl"),
        ("giphy", "giphy"),
        ("", ""),
        (None, ""),
    ],
    ids=repr,
)
def test_spellings_normalise_to_one_name(raw, expected):
    assert LicensePolicy.normalise(raw) == expected


def test_a_licence_is_allowed_only_when_its_normalised_name_is_listed():
    allowed = {"cc0", "pdm", "cc-by", "cc-by-sa"}

    assert LicensePolicy.allowed("CC BY-SA 4.0", allowed) is True
    assert LicensePolicy.allowed("Public domain", allowed) is True
    assert LicensePolicy.allowed("CC BY-NC 4.0", allowed) is False
    assert LicensePolicy.allowed("GFDL", allowed) is False
    assert LicensePolicy.allowed("", allowed) is False
