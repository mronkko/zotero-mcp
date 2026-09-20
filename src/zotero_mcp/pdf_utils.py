"""Deprecated: ``zotero_mcp.pdf_utils`` moved to ``zotero_mcp.attachments.pdf``."""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.attachments.pdf")
