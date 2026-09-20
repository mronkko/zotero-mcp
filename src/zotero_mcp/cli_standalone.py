"""Deprecated: ``zotero_mcp.cli_standalone`` moved to ``zotero_mcp.cli.standalone``.

``main`` is the one exception, forwarded **permanently and silently** for the same reason as
``zotero_mcp.cli.main``: a console script records its target at install time, so an installation made
before the move still has ``zotero-cli = zotero_mcp.cli_standalone:main`` in its entry-point metadata and
resolves ``main`` here on every single invocation. A console-script wrapper's frame is ``__main__``, where
CPython's default ``default::DeprecationWarning:__main__`` filter shows ``DeprecationWarning`` subclasses,
so routing it through the forwarder prints a notice to a real user's terminal every time they run the
command. ``main`` is an entry-point target, not a deprecation; everything else warns.
"""

from __future__ import annotations

from zotero_mcp._shim import forwarder

__all__: list[str] = []

# stacklevel=3: the closure is called from the `__getattr__` below, one frame further in than the
# plain shims, and a warning attributed to this module instead of the caller is swallowed by
# CPython's default `ignore::DeprecationWarning`. See `_shim.forwarder`.
_forward = forwarder(__name__, "zotero_mcp.cli.standalone", stacklevel=3)


def __getattr__(name: str):
    if name == "main":  # permanent, silent: pre-move console scripts resolve `zotero_mcp.cli_standalone:main` here
        from zotero_mcp.cli.standalone import main

        return main
    return _forward(name)
