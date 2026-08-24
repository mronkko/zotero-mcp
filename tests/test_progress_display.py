"""The single-line progress display must measure the terminal in columns.

Two defects motivated these tests, both reproducible on a plain 80-column
terminal:

* The fulltext-extraction line budgets its width with ``len()``. A CJK title
  occupies two columns per character, so a line ``len()`` calls 76 characters
  can occupy 110 columns, wrap, and leave ``\\r`` returning to the start of the
  *last* visual row -- the progress line smears down the screen instead of
  overwriting itself.

* The embedding line never consulted the terminal width at all and never
  padded, so a short title following a long one left the previous title's tail
  on screen. That one needs no wide characters to reproduce.
"""

import unicodedata

from zotero_mcp.semantic_search import (
    _display_width,
    _fit_to_width,
    _item_progress_line,
    _progress_line,
    _scan_progress_line,
)

# A real-world CJK title: 34 characters, 68 columns.
CJK_TITLE = "中国企业创新绩效的实证研究：基于制度环境的调节效应分析与政策含义探讨"


def _columns(text: str) -> int:
    """Independent width oracle, so the tests do not assert via the code under
    test."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


class TestDisplayWidth:
    def test_ascii_is_one_column_per_character(self):
        assert _display_width("hello") == 5

    def test_wide_characters_are_two_columns(self):
        assert _display_width("中文") == 4

    def test_mixed_text_sums_both_kinds(self):
        # 2 ASCII + 2 wide = 2 + 4
        assert _display_width("ab中文") == 6


class TestFitToWidth:
    def test_short_text_is_returned_unchanged(self):
        assert _fit_to_width("hello", 20) == "hello"

    def test_a_wide_string_is_cut_to_the_column_budget(self):
        fitted = _fit_to_width(CJK_TITLE, 20)
        assert _columns(fitted) <= 20

    def test_an_ascii_string_is_cut_to_the_column_budget(self):
        fitted = _fit_to_width("x" * 100, 20)
        assert _columns(fitted) <= 20

    def test_a_cut_string_is_marked_as_truncated(self):
        assert _fit_to_width("x" * 100, 20).endswith("...")

    def test_a_budget_too_small_for_the_marker_still_respects_it(self):
        # Degenerate but reachable on a very narrow terminal; must never
        # return something wider than asked for.
        assert _columns(_fit_to_width(CJK_TITLE, 2)) <= 2


class TestProgressLine:
    TERM_WIDTH = 80

    def test_a_cjk_title_never_exceeds_the_terminal_width(self):
        """The path A defect: `len()` said this fits, the terminal disagreed."""
        text = f"  Processing 1234/5678 — {CJK_TITLE}"
        payload = _progress_line(text, self.TERM_WIDTH).lstrip("\r")
        assert _columns(payload) <= self.TERM_WIDTH - 1

    def test_an_ascii_line_never_exceeds_the_terminal_width(self):
        text = "  Processing 1234/5678 — " + "A Long Article Title " * 10
        payload = _progress_line(text, self.TERM_WIDTH).lstrip("\r")
        assert _columns(payload) <= self.TERM_WIDTH - 1

    def test_the_line_starts_with_a_carriage_return(self):
        assert _progress_line("x", self.TERM_WIDTH).startswith("\r")

    def test_a_short_line_erases_a_longer_predecessor(self):
        """The path B defect: without padding, the tail of the previous title
        stayed on screen."""
        long_payload = _progress_line(
            "  [ 45%] 123/4567 — A Very Long Article Title About Something",
            self.TERM_WIDTH,
        ).lstrip("\r")
        short_payload = _progress_line(
            "  [ 46%] 124/4567 — Short", self.TERM_WIDTH
        ).lstrip("\r")
        assert _columns(short_payload) >= _columns(long_payload)

    def test_a_wide_line_erases_a_wide_predecessor(self):
        """Padding is computed in columns too, or a CJK line leaves residue."""
        long_payload = _progress_line(f"  [ 45%] 1/2 — {CJK_TITLE}", self.TERM_WIDTH).lstrip("\r")
        short_payload = _progress_line("  [ 46%] 2/2 — 短", self.TERM_WIDTH).lstrip("\r")
        assert _columns(short_payload) >= _columns(long_payload)


class TestItemProgressLine:
    """The embedding path (`_report_item_progress`)."""

    TERM_WIDTH = 80

    def test_a_cjk_title_never_exceeds_the_terminal_width(self):
        payload = _item_progress_line(123, 4567, CJK_TITLE, self.TERM_WIDTH).lstrip("\r")
        assert _columns(payload) <= self.TERM_WIDTH - 1

    def test_a_short_title_erases_a_longer_predecessor(self):
        long_payload = _item_progress_line(
            123, 4567, "A Very Long Article Title About Something", self.TERM_WIDTH
        ).lstrip("\r")
        short_payload = _item_progress_line(124, 4567, "Short", self.TERM_WIDTH).lstrip("\r")
        assert _columns(short_payload) >= _columns(long_payload)

    def test_a_missing_title_still_renders_a_line(self):
        assert "processing..." in _item_progress_line(1, 10, "", self.TERM_WIDTH)

    def test_a_zero_total_does_not_divide_by_zero(self):
        assert _item_progress_line(0, 0, "x", self.TERM_WIDTH).startswith("\r")


class TestScanProgressLine:
    """The fulltext-extraction path."""

    TERM_WIDTH = 80

    def test_a_cjk_title_never_exceeds_the_terminal_width(self):
        payload = _scan_progress_line(
            1234, 5678, 200, 30, CJK_TITLE, self.TERM_WIDTH
        ).lstrip("\r")
        assert _columns(payload) <= self.TERM_WIDTH - 1

    def test_the_counters_survive_a_title_that_fills_the_row(self):
        """Truncation must eat the title, not the progress numbers."""
        payload = _scan_progress_line(
            1234, 5678, 0, 0, CJK_TITLE * 5, self.TERM_WIDTH
        ).lstrip("\r")
        assert "1234/5678" in payload

    def test_status_counts_are_reported_when_present(self):
        payload = _scan_progress_line(5, 10, 3, 2, "T", self.TERM_WIDTH)
        assert "3 up to date" in payload and "2 extracted" in payload

    def test_status_is_omitted_when_there_is_nothing_to_report(self):
        payload = _scan_progress_line(5, 10, 0, 0, "T", self.TERM_WIDTH)
        assert "up to date" not in payload and "extracted" not in payload
