"""Deprecated: ``zotero_mcp.batch_common`` moved to ``zotero_mcp.semantic_search.batch.common``."""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.semantic_search.batch.common")
