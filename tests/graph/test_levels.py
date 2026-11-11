"""Unit under test: `graph.levels`, the pure value classes for a learner's level (`Level`, `StarRating`,
`RaterCategory`) and for a question's difficulty (`Difficulty`, `MarkTier`, `BandDifficulty`).

Why: every later part of the modular lesson flow (lesson shape, follow-up offers, marks, quiz mix) is decided from these
values. A star that maps to the wrong level, a name from before the rename that is refused when an old lesson is opened,
or a diagnostic band that lands on the wrong difficulty would quietly change what a learner is taught and asked.

Use cases:
- every half star from 0.5 to 5 maps to the level in the spec (0.5-1.5 Beginner, 2-3.5 Foundation, 4 Proficient,
  4.5-5 Expert)
- a star rating is stored as whole halves (1 to 10), converts from and to stars, and refuses anything else
- every half star maps to the rater category in the spec (at most 1.5 low, at least 4.5 high, the rest mid)
- a level has a rater category too, so a level found by a quiz is treated like a rating
- a level parses from its own name in any case, and from the three old names that mean something else
- the old name "beginner" is ambiguous, so only the legacy reader maps it to Foundation
- an unknown level name or a non-string is refused
- a level shifts up and down and stops at both ends
- a document (an assessment, a plan) says which level names it uses with `level_scheme`: stamped, its level is read with
  `Level.parse`; unstamped, it is legacy and read with `Level.parse_legacy`, so "beginner" means what it meant when
  written
- a level has a display label
- a difficulty parses from its name in any case, and from the old "medium" and "hard"
- an unknown difficulty or a non-string is refused
- the five difficulties are ordered easy to expert, and the first three are the normal mark tier, the last two the
  difficult tier
- every diagnostic band maps to one difficulty, one to one, and back
- a band that does not exist is refused
"""

import pytest

from graph.levels import BandDifficulty, Difficulty, Level, LevelScheme, MarkTier, RaterCategory, StarRating
from graph.schemas.diagnostic import BANDS

STAR_TABLE = [
    # halves, stars, level, rater category
    (1, 0.5, Level.BEGINNER, RaterCategory.LOW),
    (2, 1.0, Level.BEGINNER, RaterCategory.LOW),
    (3, 1.5, Level.BEGINNER, RaterCategory.LOW),
    (4, 2.0, Level.FOUNDATION, RaterCategory.MID),
    (5, 2.5, Level.FOUNDATION, RaterCategory.MID),
    (6, 3.0, Level.FOUNDATION, RaterCategory.MID),
    (7, 3.5, Level.FOUNDATION, RaterCategory.MID),
    (8, 4.0, Level.PROFICIENT, RaterCategory.MID),
    (9, 4.5, Level.EXPERT, RaterCategory.HIGH),
    (10, 5.0, Level.EXPERT, RaterCategory.HIGH),
]


class TestStarRating:
    @pytest.mark.parametrize(("halves", "stars", "level", "category"), STAR_TABLE)
    def test_every_half_star_maps_to_the_level_in_the_spec(self, halves, stars, level, category):
        rating = StarRating(halves)
        assert rating.level() == level
        assert rating.stars == stars

    @pytest.mark.parametrize(("halves", "stars", "level", "category"), STAR_TABLE)
    def test_every_half_star_maps_to_the_rater_category_in_the_spec(self, halves, stars, level, category):
        assert StarRating(halves).rater_category() == category

    @pytest.mark.parametrize(("halves", "stars", "level", "category"), STAR_TABLE)
    def test_stars_convert_to_whole_halves_and_back(self, halves, stars, level, category):
        assert StarRating.from_stars(stars) == StarRating(halves)
        assert StarRating.from_stars(stars).halves == halves

    @pytest.mark.parametrize("halves", [0, 11, -1, 100])
    def test_halves_outside_one_to_ten_are_refused(self, halves):
        with pytest.raises(ValueError):
            StarRating(halves)

    @pytest.mark.parametrize("halves", [1.0, "3", None, True])
    def test_halves_that_are_not_integers_are_refused(self, halves):
        with pytest.raises(ValueError):
            StarRating(halves)

    @pytest.mark.parametrize("stars", [0, 0.25, 1.3, 5.5, 6, -1, "3", None, float("nan")])
    def test_stars_that_are_not_a_half_step_from_half_to_five_are_refused(self, stars):
        with pytest.raises(ValueError):
            StarRating.from_stars(stars)


class TestRaterCategory:
    @pytest.mark.parametrize(
        ("level", "category"),
        [
            (Level.BEGINNER, RaterCategory.LOW),
            (Level.FOUNDATION, RaterCategory.MID),
            (Level.PROFICIENT, RaterCategory.MID),
            (Level.EXPERT, RaterCategory.HIGH),
        ],
    )
    def test_a_level_has_a_category_so_a_quiz_level_is_treated_like_a_rating(self, level, category):
        assert RaterCategory.of(level) == category


class TestLevel:
    @pytest.mark.parametrize("level", list(Level))
    @pytest.mark.parametrize("variant", [str.lower, str.upper, str.title, lambda s: f"  {s} "])
    def test_parses_its_own_name_in_any_case(self, level, variant):
        assert Level.parse(variant(level.value)) is level

    @pytest.mark.parametrize(
        ("old", "level"),
        [("novice", Level.BEGINNER), ("intermediate", Level.PROFICIENT), ("advanced", Level.EXPERT)],
    )
    def test_parses_the_old_names_that_mean_something_else_now(self, old, level):
        assert Level.parse(old) is level

    def test_beginner_means_the_new_beginner_for_the_normal_reader(self):
        assert Level.parse("beginner") is Level.BEGINNER

    @pytest.mark.parametrize(
        ("old", "level"),
        [
            ("novice", Level.BEGINNER),
            ("beginner", Level.FOUNDATION),
            ("intermediate", Level.PROFICIENT),
            ("advanced", Level.EXPERT),
        ],
    )
    def test_the_legacy_reader_maps_the_old_four_by_position(self, old, level):
        assert Level.parse_legacy(old) is level

    @pytest.mark.parametrize("new", ["foundation", "proficient", "expert"])
    def test_the_legacy_reader_also_accepts_a_name_that_only_exists_now(self, new):
        assert Level.parse_legacy(new) is Level(new)

    @pytest.mark.parametrize("raw", ["", "guru", "none", None, 3, ["expert"]])
    def test_an_unknown_level_or_a_non_string_is_refused(self, raw):
        with pytest.raises(ValueError):
            Level.parse(raw)
        with pytest.raises(ValueError):
            Level.parse_legacy(raw)

    @pytest.mark.parametrize(
        ("start", "by", "expected"),
        [
            (Level.BEGINNER, 1, Level.FOUNDATION),
            (Level.FOUNDATION, 1, Level.PROFICIENT),
            (Level.PROFICIENT, 1, Level.EXPERT),
            (Level.EXPERT, -1, Level.PROFICIENT),
            (Level.PROFICIENT, -2, Level.BEGINNER),
            (Level.BEGINNER, 0, Level.BEGINNER),
            (Level.BEGINNER, 3, Level.EXPERT),
        ],
    )
    def test_shifts_up_and_down(self, start, by, expected):
        assert start.shifted(by) is expected

    @pytest.mark.parametrize(
        ("start", "by", "expected"),
        [
            (Level.EXPERT, 1, Level.EXPERT),
            (Level.EXPERT, 9, Level.EXPERT),
            (Level.BEGINNER, -1, Level.BEGINNER),
            (Level.FOUNDATION, -9, Level.BEGINNER),
        ],
    )
    def test_shifting_stops_at_both_ends(self, start, by, expected):
        assert start.shifted(by) is expected

    def test_has_a_display_label(self):
        assert [level.label for level in Level] == ["Beginner", "Foundation", "Proficient", "Expert"]


class TestDifficulty:
    @pytest.mark.parametrize("difficulty", list(Difficulty))
    @pytest.mark.parametrize("variant", [str.lower, str.upper, str.title, lambda s: f" {s}\n"])
    def test_parses_its_own_name_in_any_case(self, difficulty, variant):
        assert Difficulty.parse(variant(difficulty.value)) is difficulty

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            ("medium", Difficulty.STANDARD),
            ("hard", Difficulty.DIFFICULT),
            ("Medium", Difficulty.STANDARD),
            ("easy", Difficulty.EASY),
        ],
    )
    def test_parses_the_old_names(self, old, new):
        assert Difficulty.parse(old) is new

    @pytest.mark.parametrize("raw", ["", "impossible", None, 2, ["easy"]])
    def test_an_unknown_difficulty_or_a_non_string_is_refused(self, raw):
        with pytest.raises(ValueError):
            Difficulty.parse(raw)

    def test_the_five_difficulties_run_from_easy_to_expert(self):
        assert [d.value for d in Difficulty] == ["easy", "basic", "standard", "difficult", "expert"]

    @pytest.mark.parametrize(
        ("difficulty", "tier"),
        [
            (Difficulty.EASY, MarkTier.NORMAL),
            (Difficulty.BASIC, MarkTier.NORMAL),
            (Difficulty.STANDARD, MarkTier.NORMAL),
            (Difficulty.DIFFICULT, MarkTier.DIFFICULT),
            (Difficulty.EXPERT, MarkTier.DIFFICULT),
        ],
    )
    def test_the_first_three_are_the_normal_tier_and_the_last_two_the_difficult_tier(self, difficulty, tier):
        assert difficulty.tier is tier


class TestBandDifficulty:
    @pytest.mark.parametrize(
        ("band", "difficulty"),
        [
            ("basic", Difficulty.EASY),
            ("easy_moderate", Difficulty.BASIC),
            ("moderate", Difficulty.STANDARD),
            ("moderate_hard", Difficulty.DIFFICULT),
            ("hard", Difficulty.EXPERT),
        ],
    )
    def test_each_band_maps_to_one_difficulty_and_back(self, band, difficulty):
        assert BandDifficulty.of(band) is difficulty
        assert BandDifficulty.band_of(difficulty) == band

    def test_every_diagnostic_band_maps_one_to_one(self):
        mapped = [BandDifficulty.of(band) for band in BANDS]
        assert len(set(mapped)) == len(BANDS) == len(Difficulty)
        assert mapped == list(Difficulty)

    @pytest.mark.parametrize("band", ["", "medium", "easy", "Basic", None])
    def test_a_band_that_does_not_exist_is_refused(self, band):
        with pytest.raises(ValueError):
            BandDifficulty.of(band)


class TestLevelScheme:
    def test_stamping_adds_the_marker_and_leaves_the_document_as_it_was(self):
        document = {"level": "beginner", "gaps": []}

        stamped = LevelScheme.stamp(document)

        assert stamped == {"level": "beginner", "gaps": [], "level_scheme": 2}
        assert "level_scheme" not in document

    @pytest.mark.parametrize(
        ("document", "level"),
        [
            ({"level": "beginner", "level_scheme": 2}, Level.BEGINNER),
            ({"level": "Foundation", "level_scheme": 2}, Level.FOUNDATION),
            ({"level": "proficient", "level_scheme": 2}, Level.PROFICIENT),
            ({"level": "expert", "level_scheme": 2}, Level.EXPERT),
        ],
    )
    def test_a_stamped_document_is_read_with_the_new_names(self, document, level):
        assert LevelScheme.level_of(document) is level

    @pytest.mark.parametrize(
        ("document", "level"),
        [
            ({"level": "novice"}, Level.BEGINNER),
            ({"level": "beginner"}, Level.FOUNDATION),  # what it meant when it was written
            ({"level": "intermediate"}, Level.PROFICIENT),
            ({"level": "advanced"}, Level.EXPERT),
            ({"level": "expert"}, Level.EXPERT),
            ({"level": "beginner", "level_scheme": 1}, Level.FOUNDATION),
            ({"level": "beginner", "level_scheme": None}, Level.FOUNDATION),
        ],
    )
    def test_an_unstamped_document_is_legacy(self, document, level):
        assert LevelScheme.level_of(document) is level

    @pytest.mark.parametrize("document", [{}, {"level": ""}, {"level": "guru", "level_scheme": 2}, {"level": None}])
    def test_a_document_without_a_readable_level_is_refused(self, document):
        with pytest.raises(ValueError):
            LevelScheme.level_of(document)

    def test_upgrading_rewrites_a_legacy_document_to_the_new_names_and_stamps_it(self):
        legacy = {"level": "beginner", "title": "x"}

        assert LevelScheme.upgraded(legacy) == {"level": "foundation", "title": "x", "level_scheme": 2}
        assert legacy == {"level": "beginner", "title": "x"}

    def test_upgrading_a_stamped_document_changes_nothing(self):
        current = {"level": "beginner", "level_scheme": 2}

        assert LevelScheme.upgraded(current) == current
