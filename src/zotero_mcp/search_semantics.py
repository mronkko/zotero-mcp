"""One definition of search-condition semantics, shared by both backends.

``zotero_advanced_search`` can run two ways: the pyzotero path in
``tools/search.py``, which fetches items and filters them in Python, and the
direct-SQL path in ``local_db.py`` used when ``ZOTERO_SEARCH_BACKEND=sqlite``.
Both have to answer a condition like ``creator contains "muller"`` identically,
or the same tool call returns different results depending on one environment
variable.

Keeping them identical by hand did not work. Three divergences appeared while
#417 was in review — collection recursion, unescaped ``LIKE`` metacharacters,
and, most consequentially, normalization: the Python path folded diacritics on
both sides while the SQL path folded neither, so a creator search for
``muller`` returned 4 items through SQL and 15 through the API on a real
57,000-item library. Every accented spelling was silently missing.

So the semantics live here once, and each backend consumes them rather than
restating them:

* :func:`compare` / :func:`matches` are the Python path's comparator.
* :func:`normalize` is *also* registered on the SQLite connection as
  ``zsearch_norm`` (see :func:`register_sqlite_functions`), so SQL compares
  the same folded form of the same strings via the same Python function.

What is deliberately *not* shared is which column or expression a field maps
to. The SQL path reads Zotero's raw multipart ``date`` value and slices the ISO
prefix, where the pyzotero path can only see the display half; that difference
is a fix, not a divergence, and belongs to each backend.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Iterable, Sequence

from .utils import _normalize_for_search

# The ten operators the advanced-search tool accepts. Frozen: they are part of
# the public tool schema and appear in stored saved-search definitions.
OPERATORS: frozenset[str] = frozenset(
    {
        "is",
        "isNot",
        "contains",
        "doesNotContain",
        "beginsWith",
        "endsWith",
        "isGreaterThan",
        "isLessThan",
        "isBefore",
        "isAfter",
    }
)

#: Operators that assert the *absence* of a match.
NEGATED: frozenset[str] = frozenset({"isNot", "doesNotContain"})

#: Each negated operator's positive counterpart. Both backends evaluate the
#: positive form and invert, rather than implementing negation twice.
POSITIVE_OF: dict[str, str] = {"isNot": "is", "doesNotContain": "contains"}

#: Ordering comparisons. These are never normalized — see :func:`sql_expression`.
RANGE_OPS: frozenset[str] = frozenset(
    {"isGreaterThan", "isLessThan", "isBefore", "isAfter"}
)

#: Operators whose SQL form is a ``LIKE`` pattern rather than an equality or
#: an inequality.
PATTERN_OPS: frozenset[str] = frozenset({"contains", "beginsWith", "endsWith"})

#: Condition-field spellings accepted from callers, mapped to the canonical
#: name. Callers lowercase the incoming field before looking it up.
FIELD_ALIASES: dict[str, str] = {
    "author": "creator",
    "authors": "creator",
    "creator": "creator",
    "creators": "creator",
    "tag": "tag",
    "tags": "tag",
    "collection": "collection",
    "collections": "collection",
    "itemtype": "itemType",
    "dateadded": "dateAdded",
    "datemodified": "dateModified",
    "doi": "DOI",
}

#: Name under which :func:`normalize` is registered on a SQLite connection.
SQLITE_NORM_FUNCTION = "zsearch_norm"

#: Escape character used with ``LIKE ... ESCAPE``. Backslash rather than a
#: rarer character because the values being escaped are bibliographic text,
#: where a literal backslash is far less common than ``%`` or ``_``.
LIKE_ESCAPE = "\\"


def canonical_field(field: str) -> str:
    """Resolve a caller-supplied condition field to its canonical spelling."""
    return FIELD_ALIASES.get(field.lower(), field)


def normalize(text: str | None) -> str:
    """Fold *text* into the form both backends compare against.

    ASCII transliteration (via ``unidecode``, so ``Müller`` and ``Muller``
    agree), dash unification, then case folding. Registered on SQLite as
    ``zsearch_norm`` so the stored side is folded the same way as the query
    side — folding only the query would still miss a stored ``Müller``.
    """
    return _normalize_for_search(text or "").lower()


def escape_like(value: str) -> str:
    """Neutralise ``LIKE`` metacharacters in a user-supplied value.

    Without this, a search for a title containing ``%`` or ``_`` matches as a
    wildcard under SQL while matching literally through the Python path. The
    escape character itself is escaped first, or escaping would corrupt values
    that already contain a backslash.
    """
    return (
        value.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )


def like_pattern(operation: str, value: str) -> str:
    """Build the ``LIKE`` pattern for *operation* from an already-escaped value."""
    positive = POSITIVE_OF.get(operation, operation)
    if positive == "contains":
        return f"%{value}%"
    if positive == "beginsWith":
        return f"{value}%"
    if positive == "endsWith":
        return f"%{value}"
    raise ValueError(f"{operation!r} is not a pattern operator")


def sql_expression(column_expr: str, operation: str) -> str:
    """Wrap a column expression so SQL compares the normalized form.

    Range operators are returned unwrapped. :func:`compare` normalizes before
    its numeric parse, but the values that reach an ordering comparison are
    ASCII digits and ISO date prefixes, where normalization is the identity —
    so skipping it is behaviour-preserving and avoids a Python callback per
    row. ``tests/test_search_parity_offline.py`` pins that equivalence.
    """
    if operation in RANGE_OPS:
        return column_expr
    return f"{SQLITE_NORM_FUNCTION}({column_expr})"


def register_sqlite_functions(conn: sqlite3.Connection) -> None:
    """Register :func:`normalize` on *conn* as ``zsearch_norm``.

    ``deterministic=True`` lets SQLite reuse results within a statement, but it
    raises ``NotSupportedError`` against SQLite older than 3.8.3; fall back to
    a plain registration there rather than failing to open the database.
    """
    try:
        conn.create_function(SQLITE_NORM_FUNCTION, 1, normalize, deterministic=True)
    except sqlite3.NotSupportedError:  # pragma: no cover - very old SQLite
        conn.create_function(SQLITE_NORM_FUNCTION, 1, normalize)


#: Month names and abbreviations, as they appear in Zotero display dates.
_MONTH_NAMES: dict[str, int] = {}
for _i, _full in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1
):
    _MONTH_NAMES[_full] = _i
    _MONTH_NAMES[_full[:3]] = _i
_MONTH_NAMES["sept"] = 9

#: A four-digit year standing alone, i.e. not part of a longer run of digits.
#: "20201203" and "20020" must NOT yield a year — Zotero cannot parse them
#: either and stores them as 0000.
_YEAR_RE = re.compile(r"(?<!\d)(1\d{3}|2\d{3})(?!\d)")
_ISO_RE = re.compile(r"^\s*(1\d{3}|2\d{3})[-/.](\d{1,2})(?:[-/.](\d{1,2}))?(?!\d)")
_NUM_MDY_RE = re.compile(r"(?<!\d)(\d{1,2})[/.-](\d{1,2})[/.-](1\d{3}|2\d{3})(?!\d)")
_NUM_MY_RE = re.compile(r"(?<!\d)(\d{1,2})[/.-](1\d{3}|2\d{3})(?!\d)")
_MONTH_WORD_RE = re.compile(
    r"(?<![a-z])(" + "|".join(sorted(_MONTH_NAMES, key=len, reverse=True)) + r")(?![a-z])"
)
_SMALL_NUM_RE = re.compile(r"(?<!\d)(\d{1,2})(?!\d)")


def _iso(year: int, month: int = 0, day: int = 0) -> str:
    """Zotero's stored form: zero-padded, ``00`` for the parts it did not learn.

    A month or day outside its real range is dropped rather than emitted: an
    impossible ``"2021-31-07"`` would sort *after* December in the string
    comparison these values exist for. Where the two are simply the wrong way
    round ("31.7.2021", written day-first) the swap is recovered instead.
    """
    if month > 12 and day == 0 or (month > 12 and 1 <= day <= 12):
        month, day = day, month
    if not 1 <= month <= 12:
        month, day = 0, 0
    if not 1 <= day <= 31:
        day = 0
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_display_date(text: str | None) -> str | None:
    """Re-derive Zotero's ISO date prefix from the display text it exposes.

    Zotero stores a date as ``"<ISO> <display text>"`` and the web/pyzotero API
    returns only the display half, so the API backend cannot read the ISO
    prefix the SQLite backend compares against (see ``local_db.py``'s
    ``_DATE_RANGE_SQL``). This reconstructs it, returning ``YYYY-MM-DD`` with
    ``00`` for parts the text does not state — the same shape Zotero itself
    stores, so the two backends order items identically.

    Returns ``None`` when the text states no year. Those are the values Zotero
    records as ``0000-00-00`` ("in press", "submitted", "n.d."): they carry no
    chronological information, so a range comparison must reject them rather
    than guess. Callers rely on that to fail *closed*.
    """
    if not text:
        return None
    s = text.strip().lower()
    if not s:
        return None

    # "2018-05-01", "2022/11/28" — the year leads, so the rest is unambiguous.
    m = _ISO_RE.match(s)
    if m:
        return _iso(int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))

    # "06/01/2012" — Zotero reads bare numeric dates in US month/day/year order.
    m = _NUM_MDY_RE.search(s)
    if m:
        return _iso(int(m.group(3)), int(m.group(1)), int(m.group(2)))

    # "03/2021", "9/1993"
    m = _NUM_MY_RE.search(s)
    if m:
        return _iso(int(m.group(2)), int(m.group(1)))

    year_match = _YEAR_RE.search(s)
    if year_match is None:
        return None
    year = int(year_match.group(1))

    # A month *name* may sit anywhere: "February 2015", "17 July 2000".
    # Where two month names run together with nothing but punctuation between
    # them ("Nov/Dec 1990", "Jul. - Aug., 2000") Zotero keeps the LAST of the
    # run; where they are separated by other content, as when a month is
    # repeated around a day range ("Jun 8-Jun 11, 2016"), it keeps the first.
    month_match = _MONTH_WORD_RE.search(s)
    if month_match is None:
        return _iso(year)
    while True:
        following = _MONTH_WORD_RE.search(s, month_match.end())
        if following is None or s[month_match.end():following.start()].strip(" .,-/–—"):
            break
        month_match = following
    month = _MONTH_NAMES[month_match.group(1)]

    # The day, if stated, is a 1-2 digit number that is not part of the year.
    # Blank the year out first so "1990" cannot be mistaken for one, then take
    # the first number after the month name ("October 1, 2016",
    # "December 10th-13th 2006") or, failing that, the first one before it
    # ("17 July 2000", "29th-31st of May 2024"). First, not last: a day range
    # is stored by its start.
    masked = s[:year_match.start()] + " " * len(year_match.group(1)) + s[year_match.end():]
    after = _SMALL_NUM_RE.search(masked, month_match.end())
    if after is not None:
        return _iso(year, month, int(after.group(1)))
    before = _SMALL_NUM_RE.search(masked[: month_match.start()])
    if before is not None:
        return _iso(year, month, int(before.group(1)))
    return _iso(year, month)


def _as_float(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


#: Fields whose ordering comparisons are chronological rather than textual.
#: Only ``date`` needs re-deriving: ``dateAdded``/``dateModified`` are already
#: ISO timestamps, where lexicographic order *is* chronological order.
DATE_FIELDS: frozenset[str] = frozenset({"date"})


def compare(candidate: str, expected: str, operation: str, field: str | None = None) -> bool:
    """Evaluate one operator against one candidate value.

    Both sides are normalized first. Ordering operators compare numerically
    when both sides parse as numbers and lexically otherwise, so ``year
    isGreaterThan 2010`` orders by magnitude while a string field still
    orders sensibly.

    *field* selects the ordering rule. On ``date``, an ordering operator
    compares the ISO prefix re-derived by :func:`parse_display_date` against
    the raw query value — exactly what the SQLite backend compares
    (``local_db.py``'s ``_DATE_RANGE_SQL``, ``SUBSTR(value, 1, 10)``) and what
    Zotero's own ``search.js`` does. Without it a display date such as
    ``"Nov/Dec 1990"`` fell through to a *lexicographic* comparison, where
    ``"nov/dec 1990" > "2024"`` is true and a "since 2024" filter returned
    papers from 1990.
    """
    if operation in RANGE_OPS and field and field.lower() in DATE_FIELDS:
        left_iso = parse_display_date(candidate)
        if left_iso is None:
            # No year in the text, or no date at all: no chronological
            # information, so it satisfies no ordering comparison. Fail closed
            # rather than guess — the same rule :func:`matches` applies to an
            # item with no value for the field at all.
            return False
        # Compared against the *unpadded* query value, as SQL does: "2024-00-00"
        # sorts after "2024", so `isAfter "2024"` includes items dated 2024.
        if operation in {"isGreaterThan", "isAfter"}:
            return left_iso > expected.strip()
        return left_iso < expected.strip()

    left = normalize(candidate)
    right = normalize(expected)

    if operation == "is":
        return left == right
    if operation == "isNot":
        return left != right
    if operation == "contains":
        return right in left
    if operation == "doesNotContain":
        return right not in left
    if operation == "beginsWith":
        return left.startswith(right)
    if operation == "endsWith":
        return left.endswith(right)

    left_num = _as_float(left)
    right_num = _as_float(right)
    if operation in RANGE_OPS and left_num is not None and right_num is not None:
        if operation in {"isGreaterThan", "isAfter"}:
            return left_num > right_num
        return left_num < right_num

    if operation in {"isGreaterThan", "isAfter"}:
        return left > right
    return left < right


def matches(
    values: Sequence[str] | Iterable[str],
    expected: str,
    operation: str,
    field: str | None = None,
) -> bool:
    """Evaluate an operator against a field that may hold several values.

    An item with no value for the field satisfies *nothing* — not even a
    negated operator. That rule is what keeps ``creator isNot "X"`` from
    sweeping in every item that has no creators at all, and the SQL builders
    reproduce it with an ``EXISTS`` guard alongside the negation.
    """
    values = list(values)
    if not values:
        return False

    comparisons = [compare(value, expected, operation, field=field) for value in values]
    if operation in NEGATED:
        return all(comparisons)
    return any(comparisons)
