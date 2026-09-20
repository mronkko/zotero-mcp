"""Deprecated: ``zotero_mcp.embeddings.ratelimit`` moved to ``zotero_mcp.semantic_search.embeddings.ratelimit``."""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.semantic_search.embeddings.ratelimit")
