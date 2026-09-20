"""Importing a submodule must not drag in the MCP server.

``zotero_mcp/__init__.py`` used to do ``from .server import mcp`` eagerly,
so any ``import zotero_mcp.<anything>`` pulled in FastMCP, the MCP SDK,
pydantic, pyzotero, bibtexparser and unidecode first. On 0.9.1 that made
``from zotero_mcp.schema import valid_fields`` -- a stdlib-only, offline
field lookup -- cost roughly 1.45 s and ~1480 modules.

These tests pin the lazy behaviour. They run each import in a *subprocess*
because import cost is only observable on a cold interpreter: by the time
the test suite is running, ``conftest`` has already imported half the
package.
"""

import subprocess
import sys
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")

# Packages that only the server needs. `schema` and `identifiers` are
# stdlib-only by design and must not reach any of them.
SERVER_ONLY_MODULES = ("fastmcp", "mcp", "pydantic", "pyzotero", "bibtexparser")


def _modules_after_importing(statement: str) -> set[str]:
    """Top-level module names loaded by `statement` in a fresh interpreter."""
    code = (
        "import sys\n"
        f"sys.path.insert(0, {SRC!r})\n"
        f"{statement}\n"
        "print(' '.join(sorted({m.split('.')[0] for m in sys.modules})))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    return set(result.stdout.split())


@pytest.mark.parametrize(
    "statement",
    [
        "from zotero_mcp.schema import valid_fields",
        "from zotero_mcp.identifiers import normalize_doi",
    ],
)
def test_stdlib_only_submodules_do_not_import_the_server(statement: str) -> None:
    loaded = _modules_after_importing(statement)
    leaked = sorted(set(SERVER_ONLY_MODULES) & loaded)
    assert not leaked, (
        f"{statement!r} pulled in server-only dependencies {leaked}. "
        f"Something re-introduced an eager import in zotero_mcp/__init__.py "
        f"or in the submodule itself."
    )


def test_version_is_available_without_the_server() -> None:
    loaded = _modules_after_importing("import zotero_mcp; zotero_mcp.__version__")
    leaked = sorted(set(SERVER_ONLY_MODULES) & loaded)
    assert not leaked, (
        f"`import zotero_mcp` alone pulled in {leaked}; the package root "
        f"should expose __version__ without loading the server."
    )


def test_mcp_attribute_still_resolves() -> None:
    """The lazy path must be transparent: `from zotero_mcp import mcp`
    keeps working, it just happens on first access now."""
    from zotero_mcp import mcp
    from zotero_mcp.server import mcp as direct

    assert mcp is direct


def test_mcp_is_advertised_by_dir() -> None:
    import zotero_mcp

    assert "mcp" in dir(zotero_mcp)


def test_unknown_attribute_raises_attribute_error() -> None:
    import zotero_mcp

    with pytest.raises(AttributeError):
        zotero_mcp.does_not_exist


# ---------------------------------------------------------------------------
# `semantic_search/` stays lazy: the property the #485 gates below rest on
# ---------------------------------------------------------------------------

# The engine, under its full dotted name. `_modules_after_importing` keeps only
# each name's top-level part -- enough for `chromadb`, blind to a submodule of
# `zotero_mcp` itself, which is exactly what has to stay unimported here.
ENGINE = "zotero_mcp.semantic_search.engine"

# Every way into the package that must not cost the engine: the package itself,
# and a real submodule reached through it. The second one is the one that can
# break silently -- `semantic_search/__init__.py` forwards unknown names to the
# engine, so a submodule missing from its `_SUBMODULES` set is resolved by the
# forwarder instead of by the import system, and importing the engine imports
# ChromaDB. PRs 12-15 all edit that file.
PATHS_INTO_SEMANTIC_SEARCH = (
    "import zotero_mcp.semantic_search",
    "from zotero_mcp.semantic_search import chroma",
)


def _sys_modules_after_importing(statement: str) -> set[str]:
    """Full `sys.modules` names loaded by `statement` in a fresh interpreter.

    Nothing may be imported between the statement and the snapshot -- not even
    `json` -- or the count below measures the probe instead of the import.
    """
    code = (
        "import sys\n"
        f"sys.path.insert(0, {SRC!r})\n"
        f"{statement}\n"
        "loaded = sorted(sys.modules)\n"
        "print(' '.join(loaded))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    return set(result.stdout.split())


@pytest.mark.parametrize("statement", PATHS_INTO_SEMANTIC_SEARCH)
def test_reaching_into_semantic_search_does_not_load_the_engine(statement: str) -> None:
    """Neither the package nor one of its submodules may pull in the engine.

    This is the headline property of the move: `semantic_search.py` became a
    package whose `__init__.py` imports nothing, so `_app.py` and `cli.py` can
    decide from config *whether* to use semantic search before paying for it
    (#485). Two ways to lose it, both of which leave the rest of the suite
    green: an eager `from zotero_mcp.semantic_search import engine` in the
    `__init__`, and a submodule name dropped from `_SUBMODULES`, after which
    `from zotero_mcp.semantic_search import <name>` is answered by the
    forwarder -- which imports the engine to answer it.
    """
    loaded = _sys_modules_after_importing(statement)

    assert ENGINE not in loaded, (
        f"{statement!r} imported {ENGINE} ({len(loaded)} modules loaded). "
        f"Either something in semantic_search/__init__.py imports the engine "
        f"eagerly, or a submodule is missing from its `_SUBMODULES` set and is "
        f"being resolved by the forwarder instead of by the import system."
    )


def test_importing_the_semantic_search_package_loads_no_chromadb() -> None:
    """The package itself must stay inside the import-cost budget.

    Only the package: `chroma` is the ChromaDB client, so importing *it*
    loads chromadb by design, and only the engine assertion above applies
    there. Measured for docs/architecture.md, "The budget": 65 modules on
    CPython 3.11, against the same under-100 budget every lazy `__init__.py`
    in the tree is held to; importing the engine instead costs ~1111.
    """
    loaded = _sys_modules_after_importing("import zotero_mcp.semantic_search")

    assert "chromadb" not in loaded, (
        f"`import zotero_mcp.semantic_search` pulled in chromadb "
        f"({len(loaded)} modules loaded); the #485 startup gates decide from "
        f"config precisely to avoid that cost."
    )
    assert len(loaded) < 100, (
        f"`import zotero_mcp.semantic_search` loaded {len(loaded)} modules, "
        f"over the under-100 budget in docs/architecture.md; the package "
        f"__init__ must import nothing."
    )


# ---------------------------------------------------------------------------
# #485: startup gates must decide from config before importing ChromaDB
# ---------------------------------------------------------------------------

_WARMUP_PROBE = """
import json, pathlib, sys, threading
sys.path.insert(0, {src!r})

home = pathlib.Path(sys.argv[1])
(home / ".config" / "zotero-mcp").mkdir(parents=True, exist_ok=True)
if sys.argv[2] != "__none__":
    (home / ".config" / "zotero-mcp" / "config.json").write_text(sys.argv[2])
pathlib.Path.home = staticmethod(lambda: home)

from zotero_mcp.cli import _warmup_reranker_in_background

_warmup_reranker_in_background()
for thread in threading.enumerate():
    if thread.name == "zmcp-reranker-warmup":
        thread.join(timeout=120)

print(json.dumps({{
    "semantic_search": "zotero_mcp.semantic_search.engine" in sys.modules,
    "chromadb": "chromadb" in sys.modules,
}}))
"""


def _warmup_imports(tmp_path, raw_config):
    """Run the reranker warmup in a fresh interpreter; report what it imported."""
    import json

    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            _WARMUP_PROBE.format(src=SRC),
            str(home),
            "__none__" if raw_config is None else raw_config,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize(
    "label,raw_config",
    [
        ("no config file", None),
        ("reranker block absent", '{"semantic_search": {}}'),
        ("reranker disabled", '{"semantic_search": {"reranker": {"enabled": false}}}'),
        ("unparseable config", "{not json"),
    ],
)
def test_reranker_warmup_gates_before_importing_chromadb(tmp_path, label, raw_config):
    """A disabled reranker must not cost a ChromaDB import on every `serve`.

    `warmup_reranker` applies the `enabled` check itself, but it lives in
    `semantic_search`, so reaching it already paid for chromadb + numpy. That
    is the #485 pattern a second time, in `cli.py` rather than `_app.py`: the
    import above the check rather than below it. Measured before the fix:
    892 ms and chromadb loaded with the reranker explicitly disabled.
    """
    seen = _warmup_imports(tmp_path, raw_config)
    assert not seen["semantic_search"], f"{label}: imported zotero_mcp.semantic_search.engine"
    assert not seen["chromadb"], f"{label}: imported chromadb"


def test_config_light_answers_the_reranker_gate_on_its_own():
    """The gate must be reachable without the module it is gating."""
    modules = _modules_after_importing("import zotero_mcp.config_light")
    assert "chromadb" not in modules
    assert "numpy" not in modules

    from zotero_mcp.config_light import reranker_enabled

    assert reranker_enabled(None) is False


_CONFIGURED = '{"semantic_search": {"embedding_model": "default"}}'


@pytest.mark.parametrize(
    "label,raw_config,platform,expected",
    [
        # The mitigation applies only where the stall was observed...
        ("windows, configured", _CONFIGURED, "win32", True),
        # ...and must not undo the other two #485 fixes for anyone else.
        ("windows, not configured", '{"semantic_search": {}}', "win32", False),
        ("windows, no config file", None, "win32", False),
        ("windows, unparseable config", "{not json", "win32", False),
        ("macos, configured", _CONFIGURED, "darwin", False),
        ("linux, configured", _CONFIGURED, "linux", False),
    ],
)
def test_main_thread_preimport_is_gated(tmp_path, label, raw_config, platform, expected):
    """Pre-import ChromaDB on Windows with semantic configured, nowhere else.

    Importing chromadb inside the AnyIO worker thread that serves a tool call
    wedges the process on Windows (#485), confirmed on two machines; the same
    import on the main thread takes ~2s. Doing it unconditionally would put
    the ChromaDB cost back on every install, which is exactly what the other
    two fixes in this issue removed.

    The predicate is tested rather than the import: faking ``sys.platform`` to
    exercise the Windows branch on a Mac makes asyncio look for
    ``_overlapped`` and fail for a reason that has nothing to do with #485.
    The real end-to-end path is covered by the test below, which runs on
    whatever host it finds — including the Windows CI job.
    """
    from zotero_mcp.cli import _should_preimport_semantic

    config_path = tmp_path / "config.json"
    if raw_config is not None:
        config_path.write_text(raw_config)

    assert _should_preimport_semantic(platform, str(config_path)) is expected, label


def test_preimport_matches_its_own_gate_on_this_host(tmp_path):
    """End-to-end on the real platform, whatever that is.

    Asserts the action agrees with the predicate rather than hardcoding an
    outcome, so it is meaningful on the Windows runner and on the others.
    """
    import json as _json
    import subprocess as _sub

    home = tmp_path / "home"
    (home / ".config" / "zotero-mcp").mkdir(parents=True)
    (home / ".config" / "zotero-mcp" / "config.json").write_text(_CONFIGURED)

    code = (
        "import json, pathlib, sys\n"
        f"sys.path.insert(0, {SRC!r})\n"
        f"pathlib.Path.home = staticmethod(lambda: pathlib.Path({str(home)!r}))\n"
        "from zotero_mcp.cli import (_preimport_semantic_search_on_main_thread,\n"
        "                            _should_preimport_semantic, _semantic_config_path)\n"
        "want = _should_preimport_semantic(sys.platform, str(_semantic_config_path(None)))\n"
        "_preimport_semantic_search_on_main_thread()\n"
        "print(json.dumps({'want': want, 'got': 'chromadb' in sys.modules}))\n"
    )
    proc = _sub.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    out = _json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["got"] is out["want"], out
