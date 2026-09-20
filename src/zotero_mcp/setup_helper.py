"""Deprecated: ``zotero_mcp.setup_helper`` moved to ``zotero_mcp.cli.wizard``."""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.cli.wizard")
