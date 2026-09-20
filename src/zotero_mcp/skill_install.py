"""Deprecated: ``zotero_mcp.skill_install`` moved to ``zotero_mcp.cli.skill_install``."""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.cli.skill_install")
