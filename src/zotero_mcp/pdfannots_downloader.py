"""Deprecated: ``zotero_mcp.pdfannots_downloader`` moved to
``zotero_mcp.attachments.pdfannots_installer``."""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.attachments.pdfannots_installer")
