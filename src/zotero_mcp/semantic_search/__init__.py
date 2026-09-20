"""Semantic search: the ChromaDB index over library text and the queries against it. Nothing is imported here.

This package is also the shim for the flat ``zotero_mcp.semantic_search`` module it replaced: every
name that is not a submodule is forwarded lazily to :mod:`zotero_mcp.semantic_search.engine`. Nothing
is imported at package import time -- ``_app.py`` and ``cli.py`` both decide from config *whether* to
use semantic search, and those gates (#485) are only meaningful while ChromaDB is still unimported.

Writing to this package does not reach the engine: see docs/architecture.md, "Patching a
package-as-shim patches nothing".
"""

from __future__ import annotations

from zotero_mcp._shim import forwarder

# Names the import system must be allowed to resolve as real submodules rather than forward to the
# engine. Four of them are modules today -- `engine`, `chroma`, `batch`, `embeddings`; the rest are
# listed ahead of the split PRs that create them (`lock`, `chunking`, ... come out of the engine in
# PRs 12-15), and a name here that has no module on disk simply raises ImportError, as it would have
# without this package. Nothing prunes this set as those PRs land: a name is needed here from the
# commit that creates the module, and harmless before it.
_SUBMODULES = frozenset(
    {
        "engine",
        "chroma",
        "batch",
        "embeddings",
        "lock",
        "chunking",
        "reranker",
        "settings",
        "documents",
        "sync_state",
        "sources",
        "_env",
        "indexer",
        "query",
        "doc_ids",
        "attachment_hashes",
    }
)

_forward = forwarder(__name__, "zotero_mcp.semantic_search.engine")


def __getattr__(name: str):
    if name in _SUBMODULES:  # let the import system load the submodule itself
        raise AttributeError(name)
    return _forward(name)
