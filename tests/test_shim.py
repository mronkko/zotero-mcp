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


# --- Console-script entry-point targets ------------------------------------
#
# A console script records its target module and attribute when it is
# *installed*, so an installation made before a move keeps resolving the old
# path on every single invocation of the command: there is no import in the
# user's own code to update, and nothing but a reinstall changes it. Routing
# that resolution through the forwarder prints a deprecation notice to a real
# user's terminal every time they run the command -- and for the stdio MCP
# server it lands on the wrong stream. The shims a console script can land on
# therefore special-case `main` and forward it permanently and silently; see
# docs/architecture.md, "Entry-point targets are not on this table's terms".
#
# Neither the commands nor the old paths are written out here. The commands
# come from `[project.scripts]`, so a fourth one cannot be added without being
# covered, and the stale path each one recorded is looked up by inverting
# `SHIMS` -- which is also what keeps this file clean for
# `test_module_layout.py`'s guard, since a quoted old path anywhere under
# tests/ is a violation and this file is not the exempt one.

from test_module_layout import SHIMS  # noqa: E402  (the guard's single source of truth)

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

# A name that is *not* an entry-point target, defined by every module a console
# script resolves through, used to prove the exemption is one name and not a
# blanket silence.
NON_ENTRY_POINT_ATTRIBUTE = "setup_zotero_environment"

# pip writes a console script in this shape, and line 4 is the resolution the
# shim's `__getattr__` serves. The real tail is `sys.exit(main())`; exiting 0
# instead leaves the streams carrying nothing but what resolving the entry
# point emits, so the command's own output can neither mask a warning nor
# stand in for one. What matters is that `__name__` is `__main__`: CPython's
# default filters are `default::DeprecationWarning:__main__` followed by
# `ignore::DeprecationWarning`, so a DeprecationWarning subclass is shown here
# and nowhere else -- which is why this has to run as a script rather than as
# an attribute access inside the suite.
_CONSOLE_SCRIPT = """\
#!{python}
# -*- coding: utf-8 -*-
import sys
from {module} import {name}
if __name__ == '__main__':
    sys.exit(0)
"""
_RESOLUTION_LINE = 4  # the `from ... import ...` line of the wrapper above


def _console_scripts() -> dict[str, tuple[str, str]]:
    """`[project.scripts]` as command -> (module, attribute), read from pyproject.toml.

    Parsed with a regex rather than `tomllib`, which is 3.11+ while this
    package supports 3.10, and read rather than taken from installed metadata
    because the installed tool is not what this checkout's tests may consult.
    """
    text = _PYPROJECT.read_text(encoding="utf-8")
    block = re.search(r"^\[project\.scripts\]$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    assert block, "pyproject.toml has no [project.scripts] table"
    entries = re.findall(r"""^\s*([\w.-]+)\s*=\s*["']([\w.]+):(\w+)["']""", block.group(1), re.M)
    assert entries, f"no console scripts parsed from:\n{block.group(1)}"
    return {command: (module, attribute) for command, module, attribute in entries}


def _stale_target(module: str) -> str:
    """The path a pre-move installation recorded for a command that now names
    ``module`` -- the `SHIMS` row pointing at it, or ``module`` itself if it
    has never moved."""
    return {new: old for old, new in SHIMS.items()}.get(module, module)


def _run_console_script(tmp_path, command: str, module: str, name: str = "main"):
    """Run a pip-shaped console-script wrapper for ``module:name`` against this
    checkout, under the interpreter's *default* warning filters.

    Nothing is installed: PYTHONPATH points at `src/`, and PYTHONWARNINGS is
    dropped so a developer's environment can neither silence the warning this
    asserts on nor manufacture one.
    """
    script = tmp_path / command
    script.write_text(_CONSOLE_SCRIPT.format(python=sys.executable, module=module, name=name))
    env = {k: v for k, v in os.environ.items() if k != "PYTHONWARNINGS"}
    env["PYTHONPATH"] = SRC
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_the_console_scripts_are_the_three_this_project_documents():
    """Guard on the parametrisation below: it is driven by pyproject.toml, so
    it silently covers nothing if the table stops parsing, and silently misses
    a command if one is added. Both show up here."""
    scripts = _console_scripts()
    assert sorted(scripts) == ["zotero-cli", "zotero-mcp", "zotero-mcp-server"]
    assert {attribute for _module, attribute in scripts.values()} == {"main"}, (
        f"a console script names an attribute other than `main`, which nothing exempts: {scripts}"
    )


@pytest.mark.parametrize("command", sorted(_console_scripts()))
def test_a_stale_console_script_resolves_main_without_warning(tmp_path, command):
    """Every console script this project installs must resolve its recorded
    `main` silently, including when the recorded target is a path that has
    since moved -- which is what every installation made before the move has.

    Both streams are asserted empty, not just stderr: `zotero-mcp` serves the
    MCP protocol over stdio, where a stray line on stdout corrupts the session
    outright.
    """
    module, attribute = _console_scripts()[command]
    stale = _stale_target(module)

    proc = _run_console_script(tmp_path, command, stale, name=attribute)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "", f"{command} ({stale}:{attribute}) wrote to stdout: {proc.stdout!r}"
    assert proc.stderr == "", f"{command} ({stale}:{attribute}) wrote to stderr: {proc.stderr!r}"


@pytest.mark.parametrize("module", sorted({module for module, _attribute in _console_scripts().values()}))
def test_every_other_name_on_an_entry_point_shim_still_warns_at_the_callers_line(tmp_path, module):
    """The `main` exemption must not leak to the rest of the module, and the
    warning must still be *visible*.

    Both of these shims wrap `forwarder`'s closure in a `__getattr__` of their
    own, one frame further from the access than the plain shims, so they pass
    ``stacklevel=3``. With the default 2 the warning is attributed to the shim
    module instead of the caller, `ignore::DeprecationWarning` swallows it,
    and the deprecation is announced to nobody -- a failure no in-process
    `pytest.warns` check can see, because that arms a filter of its own.
    Asserting the reported location is the wrapper's own line pins the
    visibility and the stacklevel together.
    """
    stale = _stale_target(module)
    if stale == module:
        pytest.skip(f"{module} has no shim row; there is no old path to warn from")

    proc = _run_console_script(tmp_path, "probe", stale, name=NON_ENTRY_POINT_ATTRIBUTE)

    assert proc.returncode == 0, proc.stderr
    assert proc.stderr.count("MovedModuleWarning") == 1, f"expected exactly one warning, got: {proc.stderr!r}"
    assert f"probe:{_RESOLUTION_LINE}: MovedModuleWarning" in proc.stderr, (
        f"the warning must point at the caller's line, not inside the shim: {proc.stderr!r}"
    )
    assert f"{stale}.{NON_ENTRY_POINT_ATTRIBUTE} moved to" in proc.stderr
