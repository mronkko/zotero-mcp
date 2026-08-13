import os

import pytest

LIVE_TESTS_ENV_VAR = "ZOTERO_MCP_LIVE_TESTS"


def pytest_collection_modifyitems(config, items):
    if os.environ.get(LIVE_TESTS_ENV_VAR, "").strip() == "1":
        return
    skip = pytest.mark.skip(
        reason=f"set {LIVE_TESTS_ENV_VAR}=1 to run live cross-backend parity tests"
    )
    for item in items:
        if "tests/live" in str(item.fspath).replace(os.sep, "/"):
            item.add_marker(skip)


# -- embedding-provider fixtures -------------------------------------------
#
# Everything below this line is the *embedding* half of tests/live/conftest.py
# (sentinel/provider/fault-injection/roundtrip live tests). PR #417 adds a
# second, disjoint half to this same file (search/Zotero-library live tests,
# with fixtures named local_zot / web_zot / sql_reader) -- the two additions
# will need to be merged by hand into one file. Only the
# pytest_collection_modifyitems hook above must stay character-identical
# between the two so that merge is a straight dedup.
#
# Everything under tests/live/ hits a real network service (a local Ollama
# server, or a paid provider API using the machine's production config)
# rather than a mock. A bare ``uv run pytest tests/`` always collects these
# tests (they show up as skipped, via the hook above) but never talks to the
# network; ``ZOTERO_MCP_LIVE_TESTS=1 uv run pytest tests/live/ -v`` runs them
# for real.
#
# Two independent gates exist on top of the module-wide skip:
#
# - ``ollama_available`` (session fixture): skips if a local Ollama server
#   isn't reachable or doesn't have the required model pulled.
# - ``configured_provider`` (fixture factory) / ``load_live_config``: the
#   "config-match gate" -- a test asking for provider X only runs if the
#   machine's actual ``~/.config/zotero-mcp/config.json`` has
#   ``semantic_search.embedding_model == X``, in which case it gets that
#   provider's real production ``embedding_config`` (including api_key). This
#   is intentional: whoever runs live tests is exercising the exact
#   configuration their own deployment uses, so a real paid API call is
#   justified. The api_key is never printed or logged by anything in this
#   file.

import json  # noqa: E402
import math  # noqa: E402
from collections.abc import Callable  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import requests  # noqa: E402

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
CONFIG_PATH = Path.home() / ".config" / "zotero-mcp" / "config.json"


@pytest.fixture(scope="session")
def ollama_available() -> str:
    """Skip unless a local Ollama server is reachable and has nomic-embed-text.

    Returns the resolved base_url on success so tests can reuse it.
    """
    base_url = (os.environ.get("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL).rstrip("/")
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        resp.raise_for_status()
    except Exception as exc:
        pytest.skip(f"Ollama not reachable at {base_url}: {exc}")

    try:
        payload = resp.json()
    except Exception as exc:
        pytest.skip(f"Ollama at {base_url} returned an unparsable /api/tags response: {exc}")

    models = [m.get("name", "") for m in payload.get("models", [])]
    # Model names come back as "nomic-embed-text:latest"; compare on the
    # part before the tag so any pulled tag counts.
    pulled = {name.split(":", 1)[0] for name in models}
    if "nomic-embed-text" not in pulled:
        pytest.skip(
            f"Ollama is up at {base_url} but 'nomic-embed-text' is not pulled "
            f"(pulled models: {sorted(pulled)}). Run: ollama pull nomic-embed-text"
        )
    return base_url


@pytest.fixture
def count_requests_post(monkeypatch: pytest.MonkeyPatch) -> list[tuple[tuple, dict]]:
    """Count calls to the global ``requests.post`` while passing them through.

    ``OllamaEmbeddingFunction._embed_batch`` does ``import requests`` *inside*
    the method body, so there is no module attribute on
    ``zotero_mcp.embeddings.providers.ollama`` to monkeypatch -- the global
    ``requests.post`` is the only interception point.
    """
    calls: list[tuple[tuple, dict]] = []
    original_post = requests.post

    def counting_post(*args: Any, **kwargs: Any):
        calls.append((args, kwargs))
        return original_post(*args, **kwargs)

    monkeypatch.setattr(requests, "post", counting_post)
    return calls


@pytest.fixture
def wrap_embed_batch():
    """Factory fixture: wrap an embedding-function INSTANCE's ``_embed_batch``
    with a counting passthrough.

    Provider-agnostic (works for SDK-based providers like OpenAI/Gemini,
    where there is no single global function to patch the way there is for
    Ollama's ``requests.post``). Usage::

        calls = wrap_embed_batch(ef)
        ef(["a", "b", "c"])
        assert len(calls) == 2
    """

    def _wrap(ef: Any) -> list[tuple[tuple, dict]]:
        calls: list[tuple[tuple, dict]] = []
        original = ef._embed_batch

        def counting(*args: Any, **kwargs: Any):
            calls.append((args, kwargs))
            return original(*args, **kwargs)

        ef._embed_batch = counting
        return calls

    return _wrap


def load_live_config() -> dict[str, Any] | None:
    """Load ``~/.config/zotero-mcp/config.json``, or ``None`` if missing/unreadable.

    Same default path ``create_chroma_client`` reads. Never logs or prints
    the contents (the caller must be equally careful with ``api_key``).
    """
    if not CONFIG_PATH.exists():
        return None
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return None


@pytest.fixture
def configured_provider():
    """Factory fixture implementing the config-match gate.

    ``configured_provider("openai")`` returns the production
    ``semantic_search.embedding_config`` dict when the machine's config has
    ``semantic_search.embedding_model == "openai"``; otherwise it
    ``pytest.skip``s with a message naming the actual configured provider.
    Missing config file skips cleanly too.
    """

    def _get(provider: str) -> dict[str, Any]:
        config = load_live_config()
        if config is None:
            pytest.skip(
                f"no {CONFIG_PATH} found; cannot run the config-matched '{provider}' live test"
            )
        semantic_search = config.get("semantic_search", {}) or {}
        actual = semantic_search.get("embedding_model")
        if actual != provider:
            pytest.skip(f"live config embedding_model is '{actual}', not '{provider}'")
        return dict(semantic_search.get("embedding_config", {}) or {})

    return _get


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-python cosine similarity (no numpy dependency required)."""
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    norm_a = math.sqrt(sum(float(x) * float(x) for x in a))
    norm_b = math.sqrt(sum(float(y) * float(y) for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


@pytest.fixture
def cosine_similarity() -> Callable[[list[float], list[float]], float]:
    """Returns the pure-python cosine-similarity helper.

    Exposed as a fixture (returning the function) rather than something test
    modules import directly, so it is reachable from any test module in this
    package via plain fixture injection without relying on a particular
    import-root layout.
    """
    return _cosine_similarity
