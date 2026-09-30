"""Showing items in the Zotero desktop reader."""

from fastmcp.exceptions import ToolError
from pyzotero.zotero_errors import ResourceNotFoundError

from zotero_mcp import client as _client
from zotero_mcp import reader_links
from zotero_mcp import utils as _utils
from zotero_mcp._app import mcp
from zotero_mcp._context import Context
from zotero_mcp.client import with_zotero_api_lock
from zotero_mcp.tools import _helpers

#: Each key opens a reader tab, so a runaway list would bury the user in tabs.
MAX_KEYS = 10


def _resolve(zot, key: str) -> tuple[str, str | None, str]:
    """Return ``(attachment_key, annotation_key, key_to_select)`` for a key.

    Raises ``LookupError`` with a message for the caller when the key cannot
    be opened.
    """
    try:
        item = zot.item(key)
    except ResourceNotFoundError:
        raise LookupError("no such item in the active library") from None
    data = item.get("data", {})
    item_type = data.get("itemType")
    if item_type == "annotation":
        # The reader finds an annotation only through its own attachment.
        attachment_key = data.get("parentItem")
        if not attachment_key:
            raise LookupError("annotation has no attachment")
        return attachment_key, key, attachment_key
    if item_type == "note":
        raise LookupError("a note has no file to open")
    attachment = (_client.get_attachment_details(zot, item, priority=("pdf",))
                  or _client.get_attachment_details(zot, item))
    if attachment is None:
        raise LookupError("no file attachment")
    return attachment.key, None, key


@mcp.tool(
    name="zotero_open_in_reader",
    description=(
        "Open items in the Zotero desktop app's reader so the user can look at "
        "the passage you are discussing, instead of only quoting a page number. "
        "keys: item, attachment or annotation keys (max 10); each opens one "
        "reader tab. A regular item opens its PDF (else its first file "
        "attachment); an annotation opens its PDF scrolled to it. "
        "page: 1-based page position, counted like zotero_read_pdf_pages (not "
        "the printed page label); ignored for annotation keys. "
        "select: also select the first key's item in the library pane. "
        "Uses the active library, groups included. Needs Zotero running on the "
        "machine this server runs on, and the file downloaded there: Zotero "
        "silently ignores a link to a file it does not have. In web mode "
        "nothing is opened and the zotero:// links are returned instead."
    ),
)
@with_zotero_api_lock
def open_in_reader(
    keys: list[str] | str,
    page: int | None = None,
    select: bool = False,
    *,
    ctx: Context,
) -> str:
    """Resolve each key to an attachment and hand Zotero a zotero:// link."""
    try:
        keys = _helpers._normalize_str_list_input(keys, "keys")
    except ValueError as e:
        raise ToolError(str(e)) from e
    if not keys:
        raise ToolError("Pass at least one item, attachment or annotation key.")
    if len(keys) > MAX_KEYS:
        raise ToolError(f"Pass at most {MAX_KEYS} keys; each one opens a reader tab.")
    if page is not None and page < 1:
        raise ToolError("page is 1-based; pass 1 or more.")

    zot = _client.get_zotero_client()
    group_id = _client.get_active_group_id()
    links: list[tuple[str, str]] = []  # (label, url)
    skipped: list[str] = []
    for key in keys:
        try:
            attachment_key, annotation_key, select_key = _resolve(zot, key)
        except Exception as e:
            skipped.append(f"- `{key}`: {e}")
            continue
        if select and not links:
            links.append((f"`{select_key}` in the library pane",
                          reader_links.select_url(select_key, group_id=group_id)))
        target = f"`{key}`" if key == attachment_key else f"`{key}` (attachment `{attachment_key}`)"
        links.append((target, reader_links.reader_url(
            attachment_key, group_id=group_id, page=page, annotation_key=annotation_key)))

    if not links:
        raise ToolError("Nothing to open:\n" + "\n".join(skipped))

    lines: list[str] = []
    if not _utils.is_local_mode():
        lines.append("Web mode: nothing was opened. Open these links on a "
                     "machine where Zotero is running:")
        lines.extend(f"- {label}: {url}" for label, url in links)
    else:
        failed = 0
        for label, url in links:
            try:
                reader_links.launch_url(url)
            except Exception as e:
                failed += 1
                ctx.warning(f"Could not open {url}: {e}")
                lines.append(f"- Could not open {label}: {url} ({type(e).__name__}: {e})")
            else:
                verb = "Selected" if url.startswith("zotero://select/") else "Opened"
                lines.append(f"- {verb} {label}: {url}")
        if failed == len(links):
            raise ToolError("Could not hand any link to Zotero:\n" + "\n".join(lines))
    if skipped:
        lines.append("Not opened:")
        lines.extend(skipped)
    return "\n".join(lines)
