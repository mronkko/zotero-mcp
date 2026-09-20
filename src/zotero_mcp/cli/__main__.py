"""Keeps ``python -m zotero_mcp.cli`` working now that ``cli`` is a package.

It is spawned from production code (``cli/updater.py`` runs
``-m zotero_mcp.cli version`` to read back the version it just installed), so it
is part of this package's own surface, not a deprecation shim.
"""

from zotero_mcp.cli.manage import main

main()
