"""Deprecated: ``zotero_mcp.embeddings`` moved to ``zotero_mcp.semantic_search.embeddings``.

Four explicit files, not a ``sys.modules`` alias. A dotted import (``import
zotero_mcp.embeddings.base``) never consults a parent package's ``__getattr__``, so each submodule
needs a real file of its own; and aliasing the old dotted paths to the new module objects would
make the interpreter execute every provider module a second time under its old name, registering
each embedding function with ChromaDB twice. ``providers/`` gets no shim at all: it is internal to
``semantic_search/``. Its importers at the old paths -- the registry, ``chroma_client.py`` and
``gemini_batch.py`` -- are all inside that package now; every other caller reaches a provider
through the registry.
"""

from zotero_mcp._shim import forwarder

__all__: list[str] = []
__getattr__ = forwarder(__name__, "zotero_mcp.semantic_search.embeddings")
