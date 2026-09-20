"""Deprecated: ``zotero_mcp.pdf_layout`` moved to ``zotero_mcp.attachments.pdf_layout``."""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.attachments.pdf_layout")
