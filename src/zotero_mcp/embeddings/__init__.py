"""Deprecated: ``zotero_mcp.embeddings`` moved to ``zotero_mcp.semantic_search.embeddings``.

Three explicit files, not a ``sys.modules`` alias. A dotted import (``import
zotero_mcp.embeddings.base``) never consults a parent package's ``__getattr__``, so each submodule
needs a real file of its own; and aliasing the old dotted paths to the new module objects would
make the interpreter execute every provider module a second time under its old name, registering
each embedding function with ChromaDB twice. ``providers/`` gets no shim at all: nothing outside
this package ever referenced it.
"""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.semantic_search.embeddings")
