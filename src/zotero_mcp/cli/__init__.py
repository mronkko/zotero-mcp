"""Console entry points: ``manage`` (zotero-mcp), ``standalone`` (zotero-cli), ``envelope`` (``--json``
output), ``wizard`` (setup), ``updater``, ``skill_install``.

Nothing is imported at package import time: ``zotero-cli --help`` must not pay for the server's dependency
tree, and the ``#485`` config gates in ``manage`` are only meaningful while ChromaDB is still unimported
(``tests/test_lightweight_imports.py`` pins both).

This ``__init__`` is also the shim for the flat ``zotero_mcp/cli.py`` this package replaced, so
attribute access forwards to :mod:`zotero_mcp.cli.manage`. ``main`` is the one exception: it forwards
**permanently and silently**. A console script records its target at install time, so an installation made
before the move still has ``zotero-mcp = zotero_mcp.cli:main`` in its entry-point metadata and resolves
``main`` here on every single invocation. Routing it through the deprecation forwarder would print a notice
to a real user's terminal each time they run the command -- and for a stdio MCP server, output on the wrong
stream is worse than noise. ``main`` is an entry-point target, not a deprecation; everything else warns.
"""

from __future__ import annotations

from zotero_mcp._shim import forwarder

# Real modules in this package. They must raise AttributeError from `__getattr__` so that the import system
# falls through to loading the submodule itself; returning something here would shadow the module object.
# `semantic_db` is listed ahead of the PR that creates it: it is a submodule name either way, never a name
# the old `cli.py` exported.
_SUBMODULES = frozenset({"manage", "standalone", "envelope", "wizard", "updater", "skill_install", "semantic_db"})

# stacklevel=3: the closure is called from the `__getattr__` below, one frame further in than the
# plain shims, and a warning attributed to this module instead of the caller is swallowed by
# CPython's default `ignore::DeprecationWarning`. See `_shim.forwarder`.
_forward = forwarder(__name__, "zotero_mcp.cli.manage", stacklevel=3)


def __getattr__(name: str):
    if name in _SUBMODULES:  # let the import system load the submodule itself
        raise AttributeError(name)
    if name == "main":  # permanent, silent: pre-move console scripts resolve `zotero_mcp.cli:main` here
        from zotero_mcp.cli.manage import main

        return main
    return _forward(name)
