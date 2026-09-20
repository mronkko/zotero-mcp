"""Deprecated: ``zotero_mcp.cli_standalone`` moved to ``zotero_mcp.cli.standalone``."""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.cli.standalone")
