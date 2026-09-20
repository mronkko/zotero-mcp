"""Deprecated: ``zotero_mcp.cli_json`` moved to ``zotero_mcp.cli.envelope``."""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.cli.envelope")
