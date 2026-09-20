"""Deprecated: ``zotero_mcp.pdfannots_helper`` moved to
``zotero_mcp.attachments.pdfannots``."""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.attachments.pdfannots")
