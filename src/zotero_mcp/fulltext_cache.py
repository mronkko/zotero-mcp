"""Deprecated: ``zotero_mcp.fulltext_cache`` moved to
``zotero_mcp.attachments.fulltext_cache``."""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.attachments.fulltext_cache")
