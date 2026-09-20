"""Deprecated: ``zotero_mcp.extract`` moved to ``zotero_mcp.attachments.extract``."""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.attachments.extract")
