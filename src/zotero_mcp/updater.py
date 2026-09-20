"""Deprecated: ``zotero_mcp.updater`` moved to ``zotero_mcp.cli.updater``."""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.cli.updater")
