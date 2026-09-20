"""Deprecated: ``zotero_mcp.gemini_batch`` moved to ``zotero_mcp.semantic_search.batch.gemini``."""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.semantic_search.batch.gemini")
