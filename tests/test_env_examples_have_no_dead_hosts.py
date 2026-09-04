# -*- coding: utf-8 -*-
"""A fixed default is not a fixed system while an env file still overrides it (BUG-406).

``OLLAMA_CLOUD_BASE_URL``'s default in ``shared/config.py`` was corrected to
``https://ollama.com/v1`` under BUG-175, with a comment saying the old value has no DNS
record. Every tracked ``.env*.example`` went on carrying the dead host, so a fresh clone
setting ``MODEL_PROVIDER=cloud`` fails EVERY LLM call with a DNS error — the exact failure
BUG-175 was closed for. Measured 2026-09-03: ``api.ollama.ai`` gives getaddrinfo failure;
``ollama.com/v1`` answers in 0.7s.

Three of four live env files carried it too. Only ``.env2`` had been hand-corrected — which
is why every hosted run in this project's history happened on bldg2, and why the hosted arm
looked like a quota problem on the other buildings.

This is the third instance of the same pattern: BUG-221 (``.env`` at OLLAMA_NUM_CTX=8192
while the fix sat in ``.env2``/``.env3``), BUG-343 (source fixed, image stale), and now this.
A default only takes effect where nothing overrides it, so the override files are part of the
fix and need a guard of their own.

Live ``.env*`` files are gitignored and cannot be asserted here. The tracked examples are
what a clone gets, so they are what this pins.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent

#: Hosts that have been configured in this repo and do not resolve. Add rather than replace:
#: a value that was once wrong stays wrong, and the point is to keep it from coming back.
_DEAD_HOSTS = ("api.ollama.ai",)


def _examples():
    return sorted(REPO.glob(".env*.example"))


def test_there_are_tracked_examples_to_check():
    """If this ever finds nothing, the test below is passing for the wrong reason."""
    assert _examples(), "no .env*.example files found — has the layout changed?"


@pytest.mark.parametrize("path", _examples(), ids=lambda p: p.name)
def test_no_example_configures_a_host_that_does_not_resolve(path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # a comment naming the dead host is documentation, not configuration
        for dead in _DEAD_HOSTS:
            assert dead not in stripped.split("#", 1)[0], (
                f"{path.name}:{line_no} configures {dead}, which has no DNS record. A clone "
                f"using this file fails every hosted LLM call. See BUG-406."
            )


def test_the_code_default_is_the_working_host():
    """The examples and the default must not drift apart again."""
    from shared.config import Settings

    default = Settings.model_fields["OLLAMA_CLOUD_BASE_URL"].default
    for dead in _DEAD_HOSTS:
        assert dead not in default
    assert default.startswith("https://"), default


def test_every_example_that_sets_the_url_agrees_with_the_default():
    """An example may omit the key and inherit; it may not contradict it."""
    from shared.config import Settings

    default = Settings.model_fields["OLLAMA_CLOUD_BASE_URL"].default
    seen = 0
    for path in _examples():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("OLLAMA_CLOUD_BASE_URL="):
                value = line.split("=", 1)[1].split("#", 1)[0].strip()
                seen += 1
                assert value == default, f"{path.name} sets {value!r}, default is {default!r}"
    assert seen, "no example sets OLLAMA_CLOUD_BASE_URL — expected at least one to pin"
