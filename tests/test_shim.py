"""Tests for ``zotero_mcp._shim.forwarder``, the lazy PEP 562 helper every
move PR in the structural refactor uses to keep a deprecated module path
importable. See ``src/zotero_mcp/_shim.py`` and ``docs/architecture.md``,
"Shims".

Each test builds real, importable modules under ``tmp_path`` (rather than
faking attribute access), because the behaviour under test -- warnings
pointing at the caller's line, and the target genuinely not being imported
until a name is used -- only shows up with real module objects and a real
``sys.path``/``sys.modules``. Every test cleans up the module names it
registers in ``sys.modules`` so test order cannot matter.
"""

from __future__ import annotations

import importlib
import inspect
import os
import re
import subprocess
import sys
import warnings
from pathlib import Path

import pytest
from conftest import SHIM_PATH_GATE_ENV_VAR, SHIM_PATHS_ARE_ERRORS

from zotero_mcp import _shim
from zotero_mcp._shim import MovedModuleWarning, forwarder

REPO = Path(__file__).resolve().parents[1]
SRC = str(REPO / "src")

# Modules that must never be pulled in by importing a shim module that only
# *defines* a forwarder -- nothing has been accessed on it yet.
HEAVY_MODULES = (
    "chromadb",
    "torch",
    "fitz",
    "pymupdf",
    "pydantic",
    "fastmcp",
    "pyzotero",
    "numpy",
    "bibtexparser",
    "unidecode",
)


def _purge(*names: str) -> None:
    for name in names:
        sys.modules.pop(name, None)


def test_forwarder_resolves_a_name_from_the_target_module(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "target_mod_1.py").write_text("VALUE = 'from target'\n")
    (tmp_path / "old_mod_1.py").write_text(
        "from zotero_mcp._shim import forwarder\n__getattr__ = forwarder(__name__, 'target_mod_1')\n"
    )
    try:
        import old_mod_1

        with pytest.warns(MovedModuleWarning):
            value = old_mod_1.VALUE

        assert value == "from target"
    finally:
        _purge("old_mod_1", "target_mod_1")


def test_forwarder_warns_on_every_access_at_the_callers_line(tmp_path, monkeypatch):
    """The warning is not cached or one-shot: two accesses produce two
    warnings, and each one's filename/lineno points at the line in *this*
    file that did the access -- proof that stacklevel=2 is doing its job,
    not just that *some* MovedModuleWarning fired somewhere."""
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "target_mod_2.py").write_text("VALUE = 42\n")
    (tmp_path / "old_mod_2.py").write_text(
        "from zotero_mcp._shim import forwarder\n__getattr__ = forwarder(__name__, 'target_mod_2')\n"
    )
    try:
        import old_mod_2

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            first_access_line = inspect.currentframe().f_lineno + 1
            _ = old_mod_2.VALUE
            second_access_line = inspect.currentframe().f_lineno + 1
            _ = old_mod_2.VALUE

        moved = [w for w in caught if issubclass(w.category, MovedModuleWarning)]
        assert len(moved) == 2, (
            "expected one warning per access (not cached / not one-shot); "
            f"got {len(moved)}: {[str(w.message) for w in moved]}"
        )
        assert moved[0].filename == __file__
        assert moved[0].lineno == first_access_line
        assert moved[1].filename == __file__
        assert moved[1].lineno == second_access_line
    finally:
        _purge("old_mod_2", "target_mod_2")


def test_forwarder_dict_form_resolves_per_name_and_rejects_unmapped_names(tmp_path, monkeypatch):
    """PR 9 splits utils.py across nine modules, so `new` must also accept a
    name -> module-path dict; an unmapped name still raises AttributeError."""
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "target_mod_3a.py").write_text("A = 'a-value'\n")
    (tmp_path / "target_mod_3b.py").write_text("B = 'b-value'\n")
    (tmp_path / "old_mod_3.py").write_text(
        "from zotero_mcp._shim import forwarder\n"
        "__getattr__ = forwarder(__name__, {'A': 'target_mod_3a', 'B': 'target_mod_3b'})\n"
    )
    try:
        import old_mod_3

        with pytest.warns(MovedModuleWarning):
            assert old_mod_3.A == "a-value"
        with pytest.warns(MovedModuleWarning):
            assert old_mod_3.B == "b-value"

        with pytest.raises(AttributeError):
            old_mod_3.C
    finally:
        _purge("old_mod_3", "target_mod_3a", "target_mod_3b")


def test_forwarder_dunder_access_raises_without_importing_the_target(tmp_path, monkeypatch):
    """pytest/inspect probe dunders like __path__ constantly; those must not
    import the target module at all -- the property that makes a shim free
    to import. Checked directly against the closure `forwarder` returns,
    against a target that is genuinely importable and genuinely absent from
    sys.modules both before and after the probe."""
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "target_mod_4.py").write_text("VALUE = 1\n")
    try:
        assert "target_mod_4" not in sys.modules

        dunder_getattr = forwarder("old_mod_4", "target_mod_4")
        with pytest.raises(AttributeError):
            dunder_getattr("__path__")

        assert "target_mod_4" not in sys.modules
    finally:
        _purge("target_mod_4")


def test_forwarder_dunder_access_via_a_real_shim_module_does_not_import_target(tmp_path, monkeypatch):
    """Same property, exercised end-to-end through a real shim module (as
    later move PRs actually use it), not just the closure directly."""
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "target_mod_5.py").write_text("VALUE = 1\n")
    (tmp_path / "old_mod_5.py").write_text(
        "from zotero_mcp._shim import forwarder\n__getattr__ = forwarder(__name__, 'target_mod_5')\n"
    )
    try:
        import old_mod_5

        assert "target_mod_5" not in sys.modules

        with pytest.raises(AttributeError):
            old_mod_5.__path__

        assert "target_mod_5" not in sys.modules, "a dunder probe must not import the target module"
    finally:
        _purge("old_mod_5", "target_mod_5")


def test_importtime_of_a_forwarder_only_module_shows_no_heavy_imports(tmp_path):
    """`-X importtime` of a module that only *defines* a forwarder (never
    accesses an attribute on it) must not drag in anything the target would
    need -- only warnings/importlib machinery, run in a subprocess since
    import cost is only observable on a cold interpreter.

    The target must have genuinely heavy transitive imports, or an eager
    `import_module(target)` regression (the exact bug this test exists to
    catch) would leave the trace looking identical to the lazy case.
    `zotero_mcp.server` is confirmed (by a direct `-X importtime` run) to
    pull in fastmcp, mcp, pydantic, pyzotero, bibtexparser and unidecode --
    six of the ten names in HEAVY_MODULES below -- unlike a stdlib-only
    target such as `zotero_mcp.schema`, whose eager import would never touch
    that blocklist and so could pass whether the forwarder is lazy or not."""
    (tmp_path / "shim_only_mod.py").write_text(
        "from zotero_mcp._shim import forwarder\n__getattr__ = forwarder(__name__, 'zotero_mcp.server')\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), SRC])

    proc = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", "import shim_only_mod"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr

    trace = proc.stderr  # -X importtime writes its trace to stderr
    leaked = [m for m in HEAVY_MODULES if m in trace]
    assert not leaked, f"importing a forwarder-only module pulled in heavy modules {leaked}:\n{trace}"

    assert "zotero_mcp._shim" in trace
    assert "warnings" in trace
    assert "importlib" in trace


def test_dash_W_error_flag_turns_the_warning_into_an_error(tmp_path):
    """`MovedModuleWarning` is addressable as a warning category by its own
    dotted name, so a *downstream* caller can promote it to an error with
    `-W error::zotero_mcp._shim.MovedModuleWarning` -- which is the whole
    point of giving the deprecation its own subclass rather than raising a
    bare DeprecationWarning.

    This is a plain interpreter, where the class the flag binds at startup
    stays the class the shim warns with. It is *not* how this suite gates
    itself: `tests/conftest.py` purges `zotero_mcp*` from `sys.modules`,
    which invalidates a startup-bound category, so the gate is armed from
    conftest instead. See
    `test_the_suites_own_configuration_turns_a_shim_access_into_an_error`.
    """
    (tmp_path / "target_mod_6.py").write_text("VALUE = 1\n")
    (tmp_path / "old_mod_6.py").write_text(
        "from zotero_mcp._shim import forwarder\n__getattr__ = forwarder(__name__, 'target_mod_6')\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), SRC])

    proc = subprocess.run(
        [
            sys.executable,
            "-W",
            "error::zotero_mcp._shim.MovedModuleWarning",
            "-c",
            "import old_mod_6\nold_mod_6.VALUE\n",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode != 0, "the -W error switch must turn the access into a failure"
    assert "MovedModuleWarning" in proc.stderr


@pytest.mark.skipif(
    not SHIM_PATHS_ARE_ERRORS,
    reason=f"the shim-path gate is disabled by {SHIM_PATH_GATE_ENV_VAR}=1",
)
def test_the_suites_own_configuration_turns_a_shim_access_into_an_error(tmp_path, monkeypatch):
    """The gate `tests/conftest.py` arms must actually bite, under the filters
    this suite really runs with.

    This is a regression test for an *inert* gate, so it deliberately touches
    no warning filters of its own: no ``pytest.warns``, no
    ``catch_warnings`` -- just an attribute access on a real shim module,
    asserting the ambient configuration turns it into an exception. Arming the
    same filter through the interpreter's ``-W`` flag passes every "is the
    filter registered?" check and still fails here, because ``-W`` binds the
    category class at interpreter startup, `conftest`'s ``sys.modules`` purge
    then discards that class, and the re-imported module's class is a
    different object the registered filter cannot match -- after which
    pyproject's ``ignore::DeprecationWarning`` swallows the warning and the
    suite goes green having tested nothing.
    """
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "target_mod_7.py").write_text("VALUE = 'from target'\n")
    (tmp_path / "old_mod_7.py").write_text(
        "from zotero_mcp._shim import forwarder\n__getattr__ = forwarder(__name__, 'target_mod_7')\n"
    )
    try:
        import old_mod_7

        with pytest.raises(MovedModuleWarning):
            old_mod_7.VALUE
    finally:
        _purge("old_mod_7", "target_mod_7")


def test_the_warning_reads_the_release_plan_from_the_two_constants(tmp_path, monkeypatch):
    """The versions in the warning are `MOVED_IN` / `REMOVED_IN` as they stand when the name is used,
    not a literal that happens to equal them: set both to versions no release will have and the
    message follows."""
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(_shim, "MOVED_IN", "98.0.0")
    monkeypatch.setattr(_shim, "REMOVED_IN", "99.0.0")
    (tmp_path / "target_mod_8.py").write_text("VALUE = 1\n")
    (tmp_path / "old_mod_8.py").write_text(
        "from zotero_mcp._shim import forwarder\n__getattr__ = forwarder(__name__, 'target_mod_8')\n"
    )
    try:
        import old_mod_8

        with pytest.warns(MovedModuleWarning) as record:
            old_mod_8.VALUE

        assert str(record[0].message) == (
            "old_mod_8.VALUE moved to target_mod_8.VALUE in 98.0.0; this alias is removed in 99.0.0"
        )
    finally:
        _purge("old_mod_8", "target_mod_8")


def _release_mentions(path: Path) -> list[tuple[Path, int, str]]:
    """Every line of `path` that spells out `MOVED_IN` or `REMOVED_IN`, as (path, line number, text).
    A version is matched whole: `10.14.0` or `0.14.0.1` is not `0.14.0`."""
    pattern = re.compile(
        "|".join(rf"(?<![\d.]){re.escape(v)}(?!\.?\d)" for v in (_shim.MOVED_IN, _shim.REMOVED_IN))
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    return [(path, n, line.strip()) for n, line in enumerate(lines, 1) if pattern.search(line)]


def test_no_shim_module_names_a_release():
    """The release plan lives in `_shim.MOVED_IN` / `REMOVED_IN` and nowhere else. A version spelled
    out in a shim's docstring or comment, or in docs/architecture.md, goes stale the day the plan
    moves -- as it did once, when 0.13.0 shipped without the refactor and left every shim saying it
    had moved in 0.13.0."""
    package = REPO / "src" / "zotero_mcp"
    shim_modules = sorted(
        p for p in package.rglob("*.py")
        if p.name != "_shim.py" and "_shim import" in p.read_text(encoding="utf-8")
    )
    hits = [hit for p in [*shim_modules, REPO / "docs" / "architecture.md"] for hit in _release_mentions(p)]
    assert not hits, "name `_shim.MOVED_IN` / `_shim.REMOVED_IN` instead of the version:\n" + "\n".join(
        f"{p.relative_to(REPO).as_posix()}:{n}: {text}" for p, n, text in hits
    )


def test_the_release_scan_flags_a_spelled_out_version(tmp_path):
    """Until a move PR adds a shim module, the guard above has only the architecture document to
    read, so the matcher is proven here on a synthetic file: both versions are flagged however they
    are punctuated, and a longer version that merely contains one is not."""
    moved, removed = _shim.MOVED_IN, _shim.REMOVED_IN
    path = tmp_path / "old_mod_9.py"
    path.write_text(
        f'"""Deprecated: moved in {moved}; removed in {removed}."""\n'
        f"# installs made before v{moved}, which record the old path\n"
        f"# not a release of ours: 1{moved}, {moved}.1, {removed}1\n"
    )
    assert [n for _, n, _ in _release_mentions(path)] == [1, 2]


# --------------------------------------------------------------------------
# A package that is its own shim (PR 3's `semantic_search/`, PR 4's `cli/`)
# --------------------------------------------------------------------------


@pytest.fixture
def package_as_shim(tmp_path, monkeypatch):
    """A real, importable package shaped exactly like ``semantic_search/``.

    A package whose ``__init__`` forwards every name that is not a submodule
    to a submodule of its own (``engine``), which is where the real globals
    live, plus a second submodule (``chroma``) reached through the package.
    PR 4 gives ``cli/`` the same shape.

    ``engine`` deliberately holds a global named after that sibling submodule.
    The real engine has no such collision today, so there the damage of a name
    missing from ``_SUBMODULES`` is only that the engine (and with it ChromaDB)
    gets imported to answer the lookup; the decoy makes the other half --
    binding the engine's global *instead of* the module -- visible now rather
    than waiting for the first collision to introduce it silently.

    It is built here rather than reached under its real name because
    ``tests/test_module_layout.py`` forbids any test file from naming a shim's
    old dotted path — that static ban is the other half of this same guard —
    and because a write to the real package would leak into the rest of the
    suite. Testing the *shape* also means PR 4 inherits the guard for free.
    """
    monkeypatch.syspath_prepend(str(tmp_path))
    pkg_dir = tmp_path / "pkg_as_shim"
    pkg_dir.mkdir()
    (pkg_dir / "chroma.py").write_text("MARKER = 'the real submodule'\n")
    (pkg_dir / "engine.py").write_text(
        "chroma = 'THE ENGINE GLOBAL, NOT THE SUBMODULE'\n"
        "\n"
        "\n"
        "def get_client():\n"
        "    return 'REAL CLIENT'\n"
        "\n"
        "\n"
        "def use_client():\n"
        "    # Engine code reads its own module global, exactly as\n"
        "    # ZoteroSemanticSearch.__init__ reads `get_zotero_client`.\n"
        "    return get_client()\n"
    )
    (pkg_dir / "__init__.py").write_text(
        "from zotero_mcp._shim import forwarder\n"
        "\n"
        "_SUBMODULES = frozenset({'engine', 'chroma'})\n"
        "_forward = forwarder(__name__, 'pkg_as_shim.engine')\n"
        "\n"
        "\n"
        "def __getattr__(name):\n"
        "    if name in _SUBMODULES:\n"
        "        raise AttributeError(name)\n"
        "    return _forward(name)\n"
    )
    try:
        yield importlib.import_module("pkg_as_shim")
    finally:
        _purge("pkg_as_shim", "pkg_as_shim.engine", "pkg_as_shim.chroma")


class TestPatchingAPackageAsShimPatchesNothing:
    """Writing to a package-as-shim looks like it worked and changes nothing.

    ``monkeypatch.setattr(package, "get_zotero_client", fake)`` puts the fake
    in the *package's* ``__dict__``; every read inside the engine resolves the
    engine's own global and never sees it. A test written that way passes
    while exercising the real client, and no static scan can catch it —
    ``tests/test_module_layout.py`` reads imports and quoted paths, not a
    runtime ``setattr`` on a module object held in a variable.

    What does catch it is the forwarder's own warning, because
    ``monkeypatch.setattr`` reads the old value before writing the new one and
    that read goes through ``__getattr__``. These tests pin that protection
    and the semantics underneath it, including the one form that slips past —
    a bare assignment, which never reads and so never warns.

    The only correct target is the module that holds the name: patch
    ``<package>.engine``, never ``<package>``.
    """

    @staticmethod
    def _fake():
        return "FAKE CLIENT"

    def test_reads_forward_to_the_engine_while_submodules_stay_real(self, package_as_shim):
        """Baseline for the three tests below: the forwarding works, and it
        does not swallow the submodules it sits in front of.

        The submodule half runs first, and through an ``import`` statement,
        because both matter. Once anything has imported ``pkg_as_shim.chroma``
        the import system has bound ``chroma`` in the package's ``__dict__``,
        normal attribute lookup finds it there and ``__getattr__`` is never
        consulted again — so ``package.chroma is <the module>`` holds even
        with ``_SUBMODULES`` emptied, and asserting it proves nothing.

        What the ``_SUBMODULES`` check actually buys shows up only on the
        first import of the name: the import system resolves it, so the engine
        is not imported to answer the lookup (in the real package that import
        is ChromaDB, and the #485 startup gates are only meaningful while it
        is unimported), and the engine's own global of that name cannot shadow
        the module.
        """
        assert "pkg_as_shim.engine" not in sys.modules, "precondition: the fixture leaves the engine unimported"

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            from pkg_as_shim import chroma

        assert [w for w in caught if issubclass(w.category, MovedModuleWarning)] == [], (
            "a submodule name must be resolved by the import system, not by the forwarder"
        )
        assert chroma is sys.modules.get("pkg_as_shim.chroma"), (
            f"the forwarder answered with the engine's global instead of the submodule: {chroma!r}"
        )
        assert "pkg_as_shim.engine" not in sys.modules, (
            "reaching a submodule imported the engine — the package __init__ must import nothing"
        )

        engine = importlib.import_module("pkg_as_shim.engine")

        with pytest.warns(MovedModuleWarning):
            assert package_as_shim.get_client is engine.get_client

    @pytest.mark.skipif(
        not SHIM_PATHS_ARE_ERRORS,
        reason=f"the shim-path gate is disabled by {SHIM_PATH_GATE_ENV_VAR}=1",
    )
    def test_monkeypatching_the_package_fails_under_the_suites_gate(self, package_as_shim, monkeypatch):
        """The protection: the bad patch must fail the build at the patch line.

        ``monkeypatch.setattr`` does ``getattr(target, name)`` first, to save
        the value it will restore. On a package-as-shim that read goes through
        the forwarder, which warns, and `tests/conftest.py` makes
        `MovedModuleWarning` an error for the whole suite — so the patch never
        completes. This test exists so that protection cannot go inert
        unnoticed: it is incidental, a side effect of monkeypatch's read, not
        something the package does deliberately.

        Deliberately no ``pytest.warns``/``catch_warnings`` here — like
        `test_the_suites_own_configuration_turns_a_shim_access_into_an_error`,
        it has to run under the suite's real, ambient filters to mean anything.
        """
        with pytest.raises(MovedModuleWarning):
            monkeypatch.setattr(package_as_shim, "get_client", self._fake)

        engine = importlib.import_module("pkg_as_shim.engine")
        assert engine.get_client is not self._fake, "the patch must not have landed"

    def test_a_bare_assignment_lands_on_the_package_and_the_engine_never_sees_it(self, package_as_shim):
        """The residue, pinned: ``package.name = fake`` reads nothing, so it
        never warns and nothing fails — and it still patches nothing.

        This is the one form the gate above cannot see. It is also why the
        rule is written as "patch the engine", not "monkeypatch is safe".
        """
        engine = importlib.import_module("pkg_as_shim.engine")
        package_as_shim.get_client = self._fake
        try:
            assert package_as_shim.get_client is self._fake, "the write lands on the package"

            assert engine.get_client is not self._fake, "but the engine's own global is untouched"
            assert engine.use_client() == "REAL CLIENT", (
                "and every read inside the engine still resolves the real implementation -- "
                "a test patching the package would exercise the real client and pass"
            )
        finally:
            vars(package_as_shim).pop("get_client", None)

    def test_a_write_to_the_package_permanently_shadows_the_forwarder(self, package_as_shim):
        """Worse than a no-op: the write also silences the warning.

        Module ``__getattr__`` runs only when normal lookup fails, so once a
        name is in the package's ``__dict__`` the forwarder stops firing for
        it — for the rest of the process. That is why the gate above is only
        a first line of defence: ``monkeypatch``'s *teardown* writes the value
        it read (the engine's real function) back onto the package, so with
        the gate off, one such test leaves the name permanently shadowed and a
        later one is no longer caught.
        """

        def moved_warnings():
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                package_as_shim.get_client
            return [w for w in caught if issubclass(w.category, MovedModuleWarning)]

        assert len(moved_warnings()) == 1, "a forwarded read warns"

        package_as_shim.get_client = self._fake
        try:
            assert moved_warnings() == [], (
                "once the name is in the package __dict__ the forwarder is never consulted again, "
                "so the access is silent"
            )
        finally:
            vars(package_as_shim).pop("get_client", None)

        assert len(moved_warnings()) == 1, "removing the shadow restores the forwarder"
