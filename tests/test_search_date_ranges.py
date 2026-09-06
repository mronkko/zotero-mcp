"""Date range comparisons must be chronological, not lexicographic.

Zotero's web/pyzotero API exposes only the *display* half of its multipart
date value ("October 1, 2016"), so the API backend used to compare that free
text lexicographically: "nov/dec 1990" > "2024" is True in code-point order,
and a "papers since 2024" filter returned papers from 1990. These tests pin
the chronological behaviour and the fail-closed rule for dates that carry no
year at all.

The expected ISO prefixes below are not invented: they are what Zotero's own
parser stored alongside each display string in a real 27k-item library.
"""

import pytest

from zotero_mcp.search_semantics import compare, matches, parse_display_date


# (display text, ISO prefix Zotero itself stored for it)
REAL_LIBRARY_DATES = [
    ("2018-05-01", "2018-05-01"),
    ("2019", "2019-00-00"),
    ("October 1, 2016", "2016-10-01"),
    ("March 2, 2018", "2018-03-02"),
    ("October 26, 2018", "2018-10-26"),
    ("September 1, 1991", "1991-09-01"),
    ("February 2015", "2015-02-00"),
    ("March 2018", "2018-03-00"),
    ("Oct 1975", "1975-10-00"),
    ("Dec 2020", "2020-12-00"),
    ("Sep 2022", "2022-09-00"),
    ("12/1998", "1998-12-00"),
    ("03/2021", "2021-03-00"),
    ("9/1993", "1993-09-00"),
    ("06/01/2012", "2012-06-01"),
    ("05/01/2001", "2001-05-01"),
    ("2022/11/28", "2022-11-28"),
    ("17 July 2000", "2000-07-17"),
    ("December 10th-13th 2006", "2006-12-10"),
    # A contiguous month range takes the LAST month; a range that repeats the
    # month around a day range takes the first. Both verified against a real
    # library's stored values.
    ("Nov/Dec 1990", "1990-12-00"),
    ("Sep/Oct 2010", "2010-10-00"),
    ("Jul. - Aug., 2000", "2000-08-00"),
    ("Jun 8-Jun 11, 2016", "2016-06-08"),
    ("29th-31st of May 2024", "2024-05-29"),
    ("-32676 1990", "1990-00-00"),
    ("Summer99 1999", "1999-00-00"),
]


@pytest.mark.parametrize("display,iso", REAL_LIBRARY_DATES,
                         ids=[d for d, _ in REAL_LIBRARY_DATES])
def test_parses_real_library_dates_the_way_zotero_did(display, iso):
    assert parse_display_date(display) == iso


def test_never_emits_an_impossible_month_or_day():
    """A month of 31 would sort after December; the parser must not invent one.

    "31.7.2021" is day-first, and Zotero reads it that way. Where a swap
    cannot rescue it ("22/1987"), the unusable component is dropped rather
    than carried into the comparison.
    """
    assert parse_display_date("31.7.2021") == "2021-07-31"
    assert parse_display_date("22/1987") == "1987-00-00"
    for text in ["31.7.2021", "22/1987", "13/45/2001", "99/1987"]:
        iso = parse_display_date(text)
        assert iso is not None
        assert 0 <= int(iso[5:7]) <= 12, f"{text} -> {iso}"
        assert 0 <= int(iso[8:10]) <= 31, f"{text} -> {iso}"


@pytest.mark.parametrize("text", ["", "   ", "in press", "submitted", "Forthcoming",
                                  "None", "20201203", "20020", "-5", "May", "n.d."])
def test_dates_without_a_year_are_unparseable(text):
    """Zotero stores these as year 0000 — they carry no chronological info."""
    assert parse_display_date(text) is None


# ---------------------------------------------------------------------------
# The bug: every one of these returned True before the fix.
# ---------------------------------------------------------------------------

PRE_2024 = ["October 1, 2016", "Nov/Dec 1990", "9/1993", "Sep 2022",
            "Jun 8-Jun 11, 2016", "2018-05-01", "2019", "03/2021", "2022/11/28"]


@pytest.mark.parametrize("display", PRE_2024, ids=PRE_2024)
def test_pre_2024_dates_are_not_after_2024(display):
    assert compare(display, "2024", "isAfter", field="date") is False


@pytest.mark.parametrize("display", PRE_2024, ids=PRE_2024)
def test_post_1900_dates_are_not_before_1900(display):
    assert compare(display, "1900", "isBefore", field="date") is False


def test_range_operators_still_order_dates_correctly():
    assert compare("Sep 2022", "2010", "isAfter", field="date") is True
    assert compare("October 1, 2016", "2020", "isBefore", field="date") is True
    assert compare("Nov/Dec 1990", "1985", "isGreaterThan", field="date") is True
    assert compare("9/1993", "1999", "isLessThan", field="date") is True


def test_full_date_granularity_is_honoured():
    """A cutoff mid-year must split items within that year."""
    assert compare("March 2, 2018", "2018-06-01", "isBefore", field="date") is True
    assert compare("October 1, 2016", "2016-06-01", "isAfter", field="date") is True


def test_unparseable_date_matches_no_range_operator():
    for op in ["isAfter", "isBefore", "isGreaterThan", "isLessThan"]:
        assert matches(["in press"], "2024", op, field="date") is False
        assert matches([""], "2024", op, field="date") is False
        assert matches([], "2024", op, field="date") is False


def test_display_operators_still_compare_display_text():
    """Only the ordering operators switch to the ISO prefix."""
    assert compare("October 1, 2016", "October", "contains", field="date") is True
    assert compare("2019", "2019", "is", field="date") is True
    assert compare("October 1, 2016", "2016-10-01", "is", field="date") is False


def test_non_date_fields_keep_their_existing_comparison():
    """dateAdded/dateModified are ISO already; year is numeric."""
    assert compare("2024-06-01 00:00:00", "2024-01-01", "isAfter", field="dateAdded") is True
    assert compare("2016", "2010", "isGreaterThan", field="year") is True
