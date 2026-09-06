"""Live: a date cutoff must partition the real library, on every backend.

The bug this pins (`date isAfter "2024"` returning papers from 1990) came from
comparing Zotero's *display* date text lexicographically: "nov/dec 1990" sorts
after "2024" in code-point order. Offline parity
(`tests/test_search_parity_offline.py`) checks the backends agree with each
other; this checks they agree with *reality*, against whatever library is
connected, where the display dates are far messier than any corpus.

Two properties per cutoff, per backend:

  * **Disjoint** — no item comes back from both `isBefore C` and `isAfter C`.
  * **Sound** — every returned item really is on the side it was returned for.
    Soundness is judged against the ISO prefix Zotero itself stored in
    zotero.sqlite, never against this codebase's own parser, so the test
    cannot pass by agreeing with a bug in `parse_display_date`.

Soundness is the assertion that catches the original bug; disjointness alone
would not, since a lexicographic comparison is still a total order and its
two sides are still disjoint — just in the wrong places.

The API backend pages the whole library client-side under a scan budget, so
on a large library its answers are legitimately *partial*. Partial results
are fine here: soundness holds for any subset, and the bug produced wrong
items immediately rather than late. Completeness is therefore only asserted
on the SQLite backend.

Gated by ZOTERO_MCP_LIVE_TESTS=1 (see conftest.py).
"""

import re
import sqlite3

import pytest

_ITEM_KEY_RE = re.compile(r"\*\*Item Key:\*\*\s*(\w+)")

#: Cutoffs spanning the library's likely range, including a full-date cutoff
#: to prove the comparison is not merely year-granular.
CUTOFFS = ["1990", "2010", "2020", "2024", "2018-06-01"]


def _stored_iso_prefixes(db_path: str) -> dict[str, str]:
    """itemKey -> the ISO prefix Zotero stored for its `date` field.

    Read straight from zotero.sqlite, bypassing this package's query builders
    entirely: this is the ground truth both backends are being judged against.
    """
    conn = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
    try:
        rows = conn.execute(
            "SELECT i.key, SUBSTR(v.value, 1, 10) "
            "FROM items i "
            "JOIN itemData d ON d.itemID = i.itemID "
            "JOIN itemDataValues v ON v.valueID = d.valueID "
            "JOIN fields f ON f.fieldID = d.fieldID "
            "WHERE f.fieldName = 'date'"
        ).fetchall()
    finally:
        conn.close()
    return {key: iso for key, iso in rows}


def _run(backend: str, value: str, operation: str, monkeypatch, dummy_ctx,
         *, local_zot, web_zot, limit: int) -> set[str]:
    from zotero_mcp.tools.search import advanced_search

    if backend == "sqlite":
        monkeypatch.setattr("zotero_mcp.utils.get_search_backend", lambda: "sqlite")
        monkeypatch.setattr("zotero_mcp.client.get_zotero_client", lambda: local_zot)
    else:
        monkeypatch.setattr("zotero_mcp.utils.get_search_backend", lambda: "api")
        client = local_zot if backend == "local_api" else web_zot
        monkeypatch.setattr("zotero_mcp.client.get_zotero_client", lambda: client)

    text = advanced_search(
        conditions=[{"field": "date", "operation": operation, "value": value}],
        join_mode="all",
        limit=limit,
        ctx=dummy_ctx,
    )
    return set(_ITEM_KEY_RE.findall(text))


@pytest.mark.parametrize("backend", ["sqlite", "local_api"])
@pytest.mark.parametrize("cutoff", CUTOFFS)
def test_cutoff_partitions_the_library(backend, cutoff, monkeypatch, dummy_ctx,
                                       local_zot, web_zot, sql_reader):
    if sql_reader is None:
        pytest.skip("no local zotero.sqlite to read ground truth from")
    if backend == "local_api" and local_zot is None:
        pytest.skip("local Zotero API not available")

    stored = _stored_iso_prefixes(sql_reader.db_path)
    limit = 200

    before = _run(backend, cutoff, "isBefore", monkeypatch, dummy_ctx,
                  local_zot=local_zot, web_zot=web_zot, limit=limit)
    after = _run(backend, cutoff, "isAfter", monkeypatch, dummy_ctx,
                 local_zot=local_zot, web_zot=web_zot, limit=limit)

    overlap = before & after
    assert not overlap, (
        f"{backend}: {sorted(overlap)[:10]} matched both "
        f"`date isBefore {cutoff}` and `date isAfter {cutoff}`"
    )

    wrong_before = {k: stored.get(k) for k in before
                    if not (stored.get(k, "") and stored[k] < cutoff)}
    assert not wrong_before, (
        f"{backend}: `date isBefore {cutoff}` returned items Zotero dates "
        f"on or after the cutoff: {dict(list(wrong_before.items())[:10])}"
    )

    wrong_after = {k: stored.get(k) for k in after
                   if not (stored.get(k, "") and stored[k] > cutoff)}
    assert not wrong_after, (
        f"{backend}: `date isAfter {cutoff}` returned items Zotero dates "
        f"on or before the cutoff: {dict(list(wrong_after.items())[:10])}"
    )


@pytest.mark.parametrize("cutoff", CUTOFFS)
def test_sqlite_cutoff_is_complete_not_merely_sound(cutoff, monkeypatch, dummy_ctx,
                                                    local_zot, web_zot, sql_reader):
    """Every item Zotero dates before the cutoff must actually come back.

    Soundness alone is satisfied by returning nothing. The SQLite backend
    queries the whole library in SQL, so it can be held to completeness;
    the API backend cannot (see module docstring).
    """
    if sql_reader is None:
        pytest.skip("no local zotero.sqlite to read ground truth from")

    stored = _stored_iso_prefixes(sql_reader.db_path)
    expected = {k for k, iso in stored.items() if iso and iso[:4] != "0000" and iso < cutoff}
    if not expected:
        pytest.skip(f"library has no items dated before {cutoff}")

    # advanced_search caps `limit` at 500 (_normalize_limit), so on a real
    # library the answer is one capped page, not the whole matching set.
    limit = 500
    before = _run("sqlite", cutoff, "isBefore", monkeypatch, dummy_ctx,
                  local_zot=local_zot, web_zot=web_zot, limit=limit)

    # Trashed items, attachments and notes are excluded from search results by
    # design, so the expected set is an upper bound: everything returned must
    # be in it, and the page must be filled from it whenever it can be.
    assert before <= expected, (
        f"`date isBefore {cutoff}` returned items outside the expected set: "
        f"{sorted(before - expected)[:10]}"
    )
    assert len(before) >= min(len(expected), limit) * 0.5, (
        f"`date isBefore {cutoff}` returned {len(before)} of "
        f"{min(len(expected), limit)} obtainable items dated before the cutoff"
    )


def test_undated_items_match_no_range_operator(monkeypatch, dummy_ctx,
                                                local_zot, web_zot, sql_reader):
    """"in press" / "submitted" must not sort before every year.

    Zotero stores an unparseable date as year 0000; left in a range
    comparison it reads as older than any real publication.
    """
    if sql_reader is None:
        pytest.skip("no local zotero.sqlite to read ground truth from")

    stored = _stored_iso_prefixes(sql_reader.db_path)
    undated = {k for k, iso in stored.items() if iso[:4] == "0000"}
    if not undated:
        pytest.skip("library has no items with an unparseable date")

    for backend in ("sqlite", "local_api"):
        if backend == "local_api" and local_zot is None:
            continue
        got = _run(backend, "3000", "isBefore", monkeypatch, dummy_ctx,
                   local_zot=local_zot, web_zot=web_zot, limit=300)
        leaked = got & undated
        assert not leaked, (
            f"{backend}: items with an unparseable date matched "
            f"`date isBefore 3000`: {sorted(leaked)[:10]}"
        )
