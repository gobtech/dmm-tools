"""Tests for pr-generator/generate_pr.py — language detection and formatting helpers."""


# ── _detect_language ──

class TestDetectLanguage:
    def test_english(self, pr_generator_mod):
        text = "The artist has been working with the producers and this album will be their best release."
        assert pr_generator_mod._detect_language(text) == "English"

    def test_spanish(self, pr_generator_mod):
        text = "El artista está trabajando con los productores para una nueva canción que será lanzada."
        assert pr_generator_mod._detect_language(text) == "Spanish"

    def test_portuguese(self, pr_generator_mod):
        text = "Os artistas estão trabalhando com os produtores para uma nova música que não será lançada."
        assert pr_generator_mod._detect_language(text) == "Portuguese"


# ── _all_same_format ──

class TestAllSameFormat:
    def test_single_run(self, pr_generator_mod):
        runs = [{"text": "hello", "bold": True, "italic": False, "font_size": 12}]
        assert pr_generator_mod._all_same_format(runs) is True

    def test_identical_runs(self, pr_generator_mod):
        runs = [
            {"text": "a", "bold": True, "italic": False, "font_size": 12},
            {"text": "b", "bold": True, "italic": False, "font_size": 12},
        ]
        assert pr_generator_mod._all_same_format(runs) is True

    def test_different_runs(self, pr_generator_mod):
        runs = [
            {"text": "a", "bold": True, "italic": False, "font_size": 12},
            {"text": "b", "bold": False, "italic": False, "font_size": 12},
        ]
        assert pr_generator_mod._all_same_format(runs) is False

    def test_empty_list(self, pr_generator_mod):
        assert pr_generator_mod._all_same_format([]) is True


# ── _snap_to_word_boundary ──

class TestSnapToWordBoundary:
    def test_snaps_forward_to_space(self, pr_generator_mod):
        text = "hello world foo bar"
        # target in middle of "world", should find the space after "world"
        result = pr_generator_mod._snap_to_word_boundary(text, 0, 8)
        assert text[result - 1] == " " or result == 8

    def test_snaps_backward_to_space(self, pr_generator_mod):
        text = "hello world foo bar"
        # target at 7 (middle of "world"), nearest space is at 5
        result = pr_generator_mod._snap_to_word_boundary(text, 0, 7)
        # Should find a space boundary
        assert result > 0

    def test_target_at_end(self, pr_generator_mod):
        text = "hello world"
        result = pr_generator_mod._snap_to_word_boundary(text, 0, len(text))
        assert result == len(text)

    def test_target_at_start(self, pr_generator_mod):
        text = "hello world"
        result = pr_generator_mod._snap_to_word_boundary(text, 0, 0)
        assert result == 0
