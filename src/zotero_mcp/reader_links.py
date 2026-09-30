"""zotero:// links that Zotero's desktop protocol handler resolves, and a launcher.

Shared by ``zotero-cli open`` and the ``zotero_open_in_reader`` tool. Stdlib
only, so the CLI can import it without pulling in the MCP server.

The link forms come from ``ZoteroProtocolHandler`` and are the same in Zotero
7, 8 and 10:

- ``zotero://open-pdf/library/items/KEY`` and
  ``zotero://open-pdf/groups/GROUP_ID/items/KEY``. ``KEY`` must be a file
  attachment whose file is on disk; anything else is logged and ignored, with
  nothing shown to the user. ``?page=N`` is 1-based (Zotero uses
  ``pageIndex = N - 1``), and ``?annotation=KEY`` scrolls to that annotation.
- ``zotero://select/library/items/KEY`` and
  ``zotero://select/groups/GROUP_ID/items/KEY``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from urllib.parse import urlencode


def _library_path(group_id: int) -> str:
    return f"groups/{group_id}" if group_id else "library"


def reader_url(attachment_key: str, *, group_id: int, page: int | None = None,
               annotation_key: str | None = None) -> str:
    """A zotero://open-pdf link. An annotation takes precedence over a page."""
    params: dict[str, str | int] = {}
    if annotation_key:
        params["annotation"] = annotation_key
    elif page:
        params["page"] = page
    query = f"?{urlencode(params)}" if params else ""
    return f"zotero://open-pdf/{_library_path(group_id)}/items/{attachment_key}{query}"


def select_url(item_key: str, *, group_id: int) -> str:
    """A zotero://select link, which selects the item in the library pane."""
    return f"zotero://select/{_library_path(group_id)}/items/{item_key}"


def launch_url(url: str) -> None:
    """Hand a URL to the OS, which passes zotero:// links to Zotero.

    Raises ``OSError`` when there is no launcher and
    ``subprocess.CalledProcessError`` when it fails, e.g. because no
    application is registered for zotero://.
    """
    if sys.platform == "darwin":
        subprocess.run(["open", url], check=True, capture_output=True, timeout=10)
    elif sys.platform == "win32":
        # What `start` does, without cmd.exe, whose parser splits at `&`.
        os.startfile(url)  # noqa: S606 -- a zotero:// link, not a path
    else:
        subprocess.run(["xdg-open", url], check=True, capture_output=True, timeout=10)
