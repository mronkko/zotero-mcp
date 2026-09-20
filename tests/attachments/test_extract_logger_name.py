"""The literals that silence the PDF extractor's logger must name the module
whose logger they mean.

``local_db.py`` and ``semantic_search.py`` each raise the extractor's logger to
CRITICAL for the duration of an indexing run, because roughly 0.4% of real PDFs
fail to parse and a warning printed mid-scan lands in the middle of a ``\\r``
progress line. Both do it by **literal string**, not by importing the module and
reading its ``logger``, because the point is to silence it without paying for
the import.

A literal cannot follow a move. If the extractor's module name and either
literal ever drift apart, the silencer raises the level of a logger nobody logs
to, PDF-extraction warnings reach stdout mid-indexing, and that corrupts
``zotero-cli --json`` output and the MCP server's stdio JSON-RPC stream — while
the suite stays green, because nothing else covers this:
``test_library_code_keeps_stdout_clean.py`` only asserts that library code never
calls bare ``print()``, and ``test_issue_455_toc_stdout_pollution.py`` is about
PyMuPDF's own notice in a subprocess. Neither would notice.

So the literal is read back out of the source file rather than written here a
second time: a copy in this file would be rewritten by the same sweep that
renames the module, and would go on agreeing with a literal that no longer
resolves.
"""

from __future__ import annotations

import importlib.util
import logging
import re
from pathlib import Path

import pytest

from zotero_mcp.attachments import extract

# Every module that silences the extractor by name. Add a row if another one
# starts doing it; a module that stops must lose its row, and both are meant to
# be a deliberate edit rather than a silent drift.
SILENCERS = ("zotero_mcp.local_db", "zotero_mcp.semantic_search")

# ``logging.getLogger("zotero_mcp....")`` with a *literal* argument. A module
# naming its own logger with ``getLogger(__name__)`` is never at risk and is
# deliberately not matched.
_LITERAL_GET_LOGGER_RE = re.compile(r"""getLogger\(\s*(?P<q>['"])(?P<name>zotero_mcp[\w.]*)(?P=q)\s*\)""")


def _literal_logger_names(module: str) -> list[str]:
    """Return every ``zotero_mcp.*`` logger name `module`'s source hard-codes.

    The file is located through the import system rather than by walking up
    from this test's ``__file__``, so it keeps pointing at the right source
    when either module moves. ``find_spec`` does not execute the module.
    """
    spec = importlib.util.find_spec(module)
    assert spec is not None and spec.origin, f"cannot locate the source of {module}"
    source = Path(spec.origin).read_text(encoding="utf-8")
    return [m.group("name") for m in _LITERAL_GET_LOGGER_RE.finditer(source)]


@pytest.mark.parametrize("module", SILENCERS)
def test_the_silencer_literal_resolves_to_the_extractors_own_logger(module):
    """The name in the source must reach the very Logger object the extractor
    logs to — not merely look plausible."""
    names = _literal_logger_names(module)

    assert names == [extract.__name__], (
        f"{module} should hard-code exactly one zotero_mcp logger name, the extractor's "
        f"({extract.__name__}); its source has {names}. The count is asserted, not just the "
        "name: a second literal silencer added to this file would fail here, so raising "
        "another zotero_mcp logger to CRITICAL has to be a deliberate change to this test "
        "rather than something that appears unnoticed."
    )
    assert logging.getLogger(names[0]) is extract.logger, (
        f"{module} silences logging.getLogger({names[0]!r}), which is not the logger "
        f"{extract.__name__} logs to ({extract.logger.name!r}). The literal has drifted "
        "away from the module: extraction warnings will reach stdout during indexing and "
        "corrupt the --json envelope and the MCP stdio stream."
    )


def test_the_extractor_logs_to_the_logger_named_after_its_module():
    """The tie the literals depend on: ``logger = getLogger(__name__)``. If the
    extractor ever named its logger something else, every silencer above would
    be addressing the wrong object while still matching ``__name__``."""
    assert extract.logger.name == extract.__name__


def test_the_worker_initializer_really_lowers_the_extractors_logger():
    """The same property end to end, through the code that runs it.

    ``_init_extraction_worker`` is the multiprocessing initializer: the parent's
    level setting means nothing in a worker, so this is the only thing standing
    between a corrupt PDF and a warning on the worker's stdout.
    """
    from zotero_mcp import local_db

    previous = extract.logger.level
    try:
        extract.logger.setLevel(logging.NOTSET)
        local_db._init_extraction_worker()
        assert extract.logger.level == logging.CRITICAL, (
            "the worker initializer left the extractor's logger at "
            f"{extract.logger.level}; it silenced some other logger instead"
        )
    finally:
        extract.logger.setLevel(previous)
