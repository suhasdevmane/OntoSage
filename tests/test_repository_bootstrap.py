# -*- coding: utf-8 -*-
"""A building booted for the first time creates its own repository (BUG-348).

bldg4 had never been started. Its GraphDB volume was empty, an empty volume has no
repository, and so:

    POST http://graphdb:7200/repositories/bldg  -> HTTP 404
    OntologyValidator: GraphDB is not reachable
    Ontology validation failed. Introspector skipped.

repeating every twenty seconds while the orchestrator served, healthily, a building
that could answer nothing. `/health` returned 200 throughout.

``scripts/ensure_graphdb_repo.py`` was written for precisely this -- its own docstring
says "A fresh GraphDB volume has NO repositories, so the ttl_uploader has nowhere to
load the building's ontology and the boot would halt" -- and **nothing called it**.
That is the seventh capability in this codebase found present, correct, documented and
uninvoked (lessons.md #87).

It belongs in the boot path rather than in a runbook step, because `docker compose up
-d` is the whole setup story (core contract #11) and a brand-new building is exactly
what the GUI onboarding flow creates.
"""

import pytest

from orchestrator.services import ontology_manager as om

pytestmark = pytest.mark.unit


class _Resp:
    def __init__(self, status=200, text=""):
        self.status_code = status
        self.text = text


class _Client:
    """Records what was asked of GraphDB, so the test can assert on the calls."""

    def __init__(self, listing, create_status=201):
        self._listing = listing
        self._create_status = create_status
        self.posted = []
        self.closed = False

    async def get(self, url):
        self.got = url
        return _Resp(200, self._listing)

    async def post(self, url, files=None):
        self.posted.append((url, files))
        return _Resp(self._create_status)

    async def aclose(self):
        self.closed = True


_EMPTY = "[]"
_HAS_REPO = '[{"id":"bldg","title":"","uri":"http://x:7200/repositories/bldg"}]'


@pytest.mark.asyncio
async def test_an_empty_graphdb_gets_a_repository():
    c = _Client(_EMPTY)
    assert await om.ensure_repository_exists(client=c) is True
    assert c.posted, "nothing was created"
    url, files = c.posted[0]
    assert url.endswith("/rest/repositories")
    assert "config" in files


@pytest.mark.asyncio
async def test_an_existing_repository_is_left_alone():
    """This runs on EVERY boot. If it were not idempotent it would be a way to lose a
    building's graph on restart."""
    c = _Client(_HAS_REPO)
    assert await om.ensure_repository_exists(client=c) is False
    assert c.posted == [], "an existing repository must never be recreated"


@pytest.mark.asyncio
async def test_the_config_sent_is_the_one_the_repo_ships():
    """Two copies of a repository config is how two buildings end up with different
    inference profiles and nobody notices until the same query answers differently."""
    c = _Client(_EMPTY)
    await om.ensure_repository_exists(client=c)
    _url, files = c.posted[0]
    sent = files["config"][1]
    on_disk = om._repo_config_bytes()
    assert on_disk is not None, "config/graphdb_repo_bldg.ttl is missing"
    assert sent == on_disk


@pytest.mark.asyncio
async def test_a_failed_creation_is_reported_not_swallowed():
    c = _Client(_EMPTY, create_status=500)
    with pytest.raises(RuntimeError):
        await om.ensure_repository_exists(client=c)


def test_the_repository_name_and_url_come_from_settings():
    """Core code carries no building literals; both are configuration."""
    import inspect

    src = inspect.getsource(om.ensure_repository_exists)
    assert "settings.GRAPHDB_REPOSITORY" in src
    assert "settings.GRAPHDB_URL" in src


def test_the_bootstrap_runs_before_the_ttl_upload_that_needs_it():
    """Order is the whole point: the uploader must have somewhere to upload."""
    from pathlib import Path

    src = Path("orchestrator/main.py").read_text(encoding="utf-8")
    assert "ensure_repository_exists" in src, "the bootstrap has no caller again"
    assert src.index("ensure_repository_exists") < src.index("run_idempotent_uploads")


def test_a_bootstrap_failure_does_not_stop_the_orchestrator_booting():
    """An existing repository is the normal case; a hiccup here must not take down a
    building that is already working."""
    from pathlib import Path

    src = Path("orchestrator/main.py").read_text(encoding="utf-8")
    block = src[src.index("ensure_repository_exists") : src.index("run_idempotent_uploads")]
    assert "except Exception" in block


# ── a new repository must be FILLED, not merely created ──────────────────────
def test_creating_a_repository_forces_a_full_re_ingest():
    """The first run of this bootstrap recreated the repository and then reported
    `uploaded=0 skipped=8` into it -- 70 triples, an empty graph -- because the SHA
    cache lives on a volume that outlives the repository, so every file looked
    "already uploaded". The orchestrator booted healthy and the building answered
    nothing.

    A repository created a moment ago contains nothing, so nothing in it can be
    already uploaded.
    """
    from pathlib import Path

    src = Path("orchestrator/main.py").read_text(encoding="utf-8")
    block = src[src.index("ensure_repository_exists") : src.index("[ttl_uploader] startup")]
    assert "cache={} if created else None" in block


def test_created_is_defined_even_when_the_bootstrap_raises():
    """`created` is read by the upload call. Assigning it only inside the try would
    make a repository hiccup raise NameError into the outer handler and skip every
    TTL -- a building with no ontology, reported as 'TTL auto-upload failed'."""
    from pathlib import Path

    src = Path("orchestrator/main.py").read_text(encoding="utf-8")
    head = src[: src.index("from orchestrator.services.ontology_manager import")]
    assert "created = False" in head[-800:], "created is not initialised before the try"
