"""Deprecated: ``zotero_mcp.epub_utils`` moved to ``zotero_mcp.attachments.epub``."""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.attachments.epub")
