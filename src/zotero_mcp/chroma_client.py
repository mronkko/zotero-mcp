"""Deprecated: ``zotero_mcp.chroma_client`` moved to ``zotero_mcp.semantic_search.chroma``."""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.semantic_search.chroma")
