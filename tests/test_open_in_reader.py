"""``zotero_open_in_reader``: point Zotero's desktop reader at an item.

The tool hands Zotero's own ``zotero://`` protocol handler a link, the same
way ``zotero-cli open`` does. Three things about that handler shape these
tests (checked against ``ZoteroProtocolHandler`` on the 7.0, 8.0 and main
branches, and live on Zotero 10.0.4):

- ``open-pdf`` needs the *attachment* key. Given a parent key it logs "not a
  file attachment" and does nothing, so the tool resolves parents itself.
- ``?page=N`` is 1-based (``pageIndex = page - 1``); ``?annotation=KEY``
  scrolls to that annotation and must name its own attachment.
- ``select`` holds one selection, and switches Zotero to the library tab.
"""

import subprocess
from unittest.mock import patch

import pytest
from conftest import DummyContext, FakeZotero
from fastmcp.exceptions import ToolError
from pyzotero.zotero_errors import ResourceNotFoundError

from zotero_mcp import reader_links
from zotero_mcp.tools import reader as reader_tools

# ---------------------------------------------------------------------------
# URL building
# ---------------------------------------------------------------------------

class TestReaderLinks:
    def test_personal_library(self):
        assert (reader_links.reader_url("A1", group_id=0)
                == "zotero://open-pdf/library/items/A1")

    def test_page(self):
        assert (reader_links.reader_url("A1", group_id=0, page=5)
                == "zotero://open-pdf/library/items/A1?page=5")

    def test_group_library(self):
        assert (reader_links.reader_url("A1", group_id=42, page=2)
                == "zotero://open-pdf/groups/42/items/A1?page=2")

    def test_annotation_wins_over_page(self):
        # The handler would apply both; the annotation is the more precise
        # target, and a page would only move the view away from it.
        assert (reader_links.reader_url("A1", group_id=0, page=3, annotation_key="N1")
                == "zotero://open-pdf/library/items/A1?annotation=N1")

    def test_select_url(self):
        assert (reader_links.select_url("P1", group_id=0)
                == "zotero://select/library/items/P1")
        assert (reader_links.select_url("P1", group_id=7)
                == "zotero://select/groups/7/items/P1")


class TestLaunchUrl:
    URL = "zotero://open-pdf/library/items/A1?page=2"

    def test_macos_uses_open(self, monkeypatch):
        monkeypatch.setattr(reader_links.sys, "platform", "darwin")
        with patch.object(reader_links.subprocess, "run") as run:
            reader_links.launch_url(self.URL)
        run.assert_called_once_with(["open", self.URL], check=True,
                                    capture_output=True, timeout=10)

    def test_linux_uses_xdg_open(self, monkeypatch):
        monkeypatch.setattr(reader_links.sys, "platform", "linux")
        with patch.object(reader_links.subprocess, "run") as run:
            reader_links.launch_url(self.URL)
        run.assert_called_once_with(["xdg-open", self.URL], check=True,
                                    capture_output=True, timeout=10)

    def test_windows_uses_startfile(self, monkeypatch):
        # os.startfile is what `start` calls, minus cmd.exe, whose parser
        # would split a query string at `&`.
        monkeypatch.setattr(reader_links.sys, "platform", "win32")
        with patch.object(reader_links.os, "startfile", create=True) as startfile, \
             patch.object(reader_links.subprocess, "run") as run:
            reader_links.launch_url(self.URL)
        startfile.assert_called_once_with(self.URL)
        run.assert_not_called()


# ---------------------------------------------------------------------------
# The tool
# ---------------------------------------------------------------------------

def _pdf(key, parent):
    return {"key": key, "data": {
        "key": key, "itemType": "attachment", "parentItem": parent,
        "contentType": "application/pdf", "filename": f"{key}.pdf",
        "title": "PDF", "linkMode": "imported_file"}}


class _Zot(FakeZotero):
    """FakeZotero whose unknown keys 404 instead of returning a stub."""

    def item(self, item_key):
        for it in self._items:
            if it.get("key") == item_key:
                return it
        raise ResourceNotFoundError(f"Code: 404\nURL: .../items/{item_key}")


@pytest.fixture
def zot():
    z = _Zot()
    z._items = [
        {"key": "P1", "data": {"key": "P1", "itemType": "journalArticle", "title": "One"}},
        {"key": "P2", "data": {"key": "P2", "itemType": "journalArticle", "title": "Two"}},
        {"key": "P3", "data": {"key": "P3", "itemType": "book", "title": "No file"}},
        _pdf("A1", "P1"),
        _pdf("A2", "P2"),
        {"key": "N1", "data": {"key": "N1", "itemType": "annotation", "parentItem": "A1"}},
        {"key": "T1", "data": {"key": "T1", "itemType": "note", "parentItem": "P1"}},
    ]
    z._children = {"P1": [_pdf("A1", "P1")], "P2": [_pdf("A2", "P2")]}
    return z


@pytest.fixture
def run(zot, monkeypatch):
    """Call the tool in local mode, recording the URLs it launches."""
    monkeypatch.setenv("ZOTERO_LOCAL", "true")
    launched = []

    def _run(*, group_id=0, launch=launched.append, **kwargs):
        # Patch the module objects the tool holds: other tests reload
        # zotero_mcp.client, and a string target would miss this reference.
        with patch.object(reader_tools._client, "get_zotero_client", return_value=zot), \
             patch.object(reader_tools._client, "get_active_group_id", return_value=group_id), \
             patch.object(reader_tools.reader_links, "launch_url", side_effect=launch):
            return reader_tools.open_in_reader(ctx=DummyContext(), **kwargs)

    _run.launched = launched
    return _run


class TestOpenInReader:
    def test_parent_key_opens_its_pdf_at_the_page(self, run):
        text = run(keys=["P1"], page=5)
        assert run.launched == ["zotero://open-pdf/library/items/A1?page=5"]
        assert "A1" in text and "P1" in text

    def test_attachment_key_opens_itself(self, run):
        run(keys=["A2"])
        assert run.launched == ["zotero://open-pdf/library/items/A2"]

    def test_annotation_key_opens_its_own_attachment_on_the_annotation(self, run):
        run(keys=["N1"], page=9)
        assert run.launched == ["zotero://open-pdf/library/items/A1?annotation=N1"]

    def test_several_keys_open_one_tab_each(self, run):
        run(keys=["P1", "P2"])
        assert run.launched == ["zotero://open-pdf/library/items/A1",
                                "zotero://open-pdf/library/items/A2"]

    def test_group_library(self, run):
        run(keys=["P1"], page=2, group_id=42)
        assert run.launched == ["zotero://open-pdf/groups/42/items/A1?page=2"]

    def test_select_runs_first_so_the_reader_ends_in_front(self, run):
        # zotero://select switches Zotero to the library tab; selecting after
        # opening would hide the reader the caller just asked for.
        text = run(keys=["P1", "P2"], select=True)
        assert run.launched == ["zotero://select/library/items/P1",
                                "zotero://open-pdf/library/items/A1",
                                "zotero://open-pdf/library/items/A2"]
        assert "Selected `P1` in the library pane" in text

    def test_select_on_annotation_selects_the_item_it_belongs_to(self, run):
        run(keys=["N1"], select=True)
        assert run.launched[0] == "zotero://select/library/items/A1"

    def test_one_bad_key_does_not_stop_the_others(self, run):
        text = run(keys=["P3", "ZZZZZZZZ", "T1", "P2"])
        assert run.launched == ["zotero://open-pdf/library/items/A2"]
        assert "P3" in text and "T1" in text
        assert "`ZZZZZZZZ`: no such item in the active library" in text

    def test_nothing_openable_is_an_error(self, run):
        with pytest.raises(ToolError, match="P3"):
            run(keys=["P3"])
        assert run.launched == []

    def test_web_mode_returns_links_without_opening(self, run, monkeypatch):
        monkeypatch.setenv("ZOTERO_LOCAL", "false")
        text = run(keys=["P1"], page=4, select=True)
        assert run.launched == []
        assert "zotero://open-pdf/library/items/A1?page=4" in text
        assert "zotero://select/library/items/P1" in text

    def test_a_link_that_fails_to_launch_is_returned_for_the_user(self, run):
        def fail_a1(url):
            if "A1" in url:
                raise FileNotFoundError("xdg-open")

        text = run(keys=["P1", "P2"], launch=fail_a1)
        assert "Could not open" in text and "zotero://open-pdf/library/items/A1" in text
        assert "xdg-open" in text
        assert "Opened `P2`" in text

    def test_launcher_failure_for_every_link_is_an_error(self, run):
        def fail(url):
            raise subprocess.CalledProcessError(1, ["open", url])

        with pytest.raises(ToolError, match="zotero://open-pdf/library/items/A1"):
            run(keys=["P1"], launch=fail)

    @pytest.mark.parametrize("kwargs", [
        {"keys": []},
        {"keys": ["P1"], "page": 0},
        {"keys": [f"K{i:07d}" for i in range(reader_tools.MAX_KEYS + 1)]},
    ])
    def test_bad_arguments_are_refused_before_anything_opens(self, run, kwargs):
        with pytest.raises(ToolError):
            run(**kwargs)
        assert run.launched == []

    def test_a_single_key_string_is_accepted(self, run):
        # Models often pass one key as a bare string rather than a list.
        run(keys="P1")
        assert run.launched == ["zotero://open-pdf/library/items/A1"]


def test_tool_is_in_its_own_opt_in_toolset():
    from zotero_mcp.toolsets import DEFAULT_ON, TOOLSETS

    assert TOOLSETS["reader"] == frozenset({"zotero_open_in_reader"})
    assert "reader" not in DEFAULT_ON
