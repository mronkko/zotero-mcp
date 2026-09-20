"""Deprecated: ``zotero_mcp.embeddings.registry`` moved to ``zotero_mcp.semantic_search.embeddings.registry``."""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.semantic_search.embeddings.registry")
