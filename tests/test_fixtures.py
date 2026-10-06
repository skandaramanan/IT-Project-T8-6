"""The fixture set is complete and intact.

Later tests will glob these files by name, so this guards the naming convention
as much as the bytes: a typo'd role, a half-copied file or a record someone
added without all four pages fails here, instead of somewhere confusing
downstream. See tests/fixtures/README.md for what the four pages are.
"""

from pathlib import Path

from support import assert_intact_jpeg

FIXTURES = Path(__file__).parent / "fixtures"
RECORDS = [f"r{n:02d}" for n in range(1, 6)]
ROLES = ["survey-front", "survey-back", "coding-front", "coding-back"]


def test_fixture_set_is_five_complete_records():
    expected = {f"{record}-{role}.jpg" for record in RECORDS for role in ROLES}
    assert {path.name for path in FIXTURES.glob("*.jpg")} == expected


def test_fixtures_are_intact_jpegs():
    for path in sorted(FIXTURES.glob("*.jpg")):
        assert_intact_jpeg(path)
