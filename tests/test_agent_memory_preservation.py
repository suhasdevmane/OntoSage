# -*- coding: utf-8 -*-
"""Agent memory must never be destroyed to satisfy a config change (CAVEAT-015).

`user_memory` is the only Qdrant collection in this system with **no on-disk source**.
`floor_plans` rebuilds from the PDF/DWG pipeline, `capability_<bldg>` from the TTL,
`documents_<bldg>` from `input/documents/` -- but a stored user memory exists nowhere else.

The original code deleted the collection on any dimension mismatch, behind one
`logger.warning`. A dimension mismatch is exactly what an `EMBEDDING_PROVIDER` flip produces,
and `EMBEDDING_PROVIDER` is documented as independently switchable, so a supported
configuration change silently and irrecoverably destroyed every stored memory. Measured on the
live system at the time: 2,750 points.

The rule asserted here: **a populated collection is dropped only after a snapshot succeeds.**
If the snapshot cannot be taken, the service degrades to unavailable and the data stays.
Memory that is temporarily unreachable is a far smaller failure than memory that is gone.
"""

from types import SimpleNamespace

import pytest

from orchestrator.services.agent_memory import COLLECTION_NAME, AgentMemoryService

pytestmark = pytest.mark.unit


class FakeClient:
    """Enough Qdrant to exercise the mismatch branch, and to record what was destroyed."""

    def __init__(self, *, existing_dim=1024, points=2750, snapshot_ok=True):
        self.existing_dim = existing_dim
        self.points = points
        self.snapshot_ok = snapshot_ok
        self.deleted = []
        self.created = []
        self.snapshots = []

    async def get_collections(self):
        return SimpleNamespace(collections=[SimpleNamespace(name=COLLECTION_NAME)])

    async def get_collection(self, name):
        return SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(vectors=SimpleNamespace(size=self.existing_dim))
            ),
            points_count=self.points,
        )

    async def create_snapshot(self, collection_name):
        if not self.snapshot_ok:
            raise RuntimeError("snapshots unavailable on this build")
        self.snapshots.append(collection_name)
        return SimpleNamespace(name=f"{collection_name}-snap")

    async def delete_collection(self, name):
        self.deleted.append(name)

    async def create_collection(self, collection_name, vectors_config):
        self.created.append((collection_name, vectors_config.size))


@pytest.fixture(autouse=True)
def stub_qdrant(monkeypatch):
    """initialise() constructs its own AsyncQdrantClient, so the constructor is what must be
    stubbed -- injecting an attribute beforehand is simply overwritten."""
    import qdrant_client

    holder = {}

    def _factory(*_a, **_k):
        return holder["client"]

    monkeypatch.setattr(qdrant_client, "AsyncQdrantClient", _factory)
    return holder


def _service(holder, client, embed_dim=384):
    holder["client"] = client
    svc = AgentMemoryService(qdrant_url="http://fake:6333")
    svc._embedder = SimpleNamespace(dimension=embed_dim, embed=lambda *_a, **_k: [])
    return svc


@pytest.mark.asyncio
async def test_a_populated_collection_is_snapshotted_before_it_is_dropped(stub_qdrant):
    client = FakeClient(existing_dim=1024, points=2750)
    await _service(stub_qdrant, client).initialise()
    assert client.snapshots == [COLLECTION_NAME]
    assert client.deleted == [COLLECTION_NAME]  # dropped, but only after the snapshot


@pytest.mark.asyncio
async def test_the_snapshot_happens_before_the_delete_not_after(stub_qdrant):
    """Ordering is the entire safety property; reversed, the data is gone either way."""
    order = []
    client = FakeClient()

    async def snap(collection_name):
        order.append("snapshot")
        return SimpleNamespace(name="s")

    async def dele(name):
        order.append("delete")

    client.create_snapshot, client.delete_collection = snap, dele
    await _service(stub_qdrant, client).initialise()
    assert order == ["snapshot", "delete"]


@pytest.mark.asyncio
async def test_a_failed_snapshot_prevents_the_delete_entirely(stub_qdrant):
    """The load-bearing case.

    If the data cannot be preserved it is not destroyed -- the service goes unavailable
    instead, which is recoverable by restoring the previous provider.
    """
    client = FakeClient(points=2750, snapshot_ok=False)
    svc = _service(stub_qdrant, client)
    await svc.initialise()
    assert client.deleted == []
    assert client.created == []
    assert svc._ready is False


@pytest.mark.asyncio
async def test_an_empty_collection_is_recreated_without_ceremony(stub_qdrant):
    """Nothing is at risk, so a mismatch on an empty collection must not block startup."""
    client = FakeClient(points=0)
    svc = _service(stub_qdrant, client)
    await svc.initialise()
    assert client.snapshots == []
    assert client.deleted == [COLLECTION_NAME]
    assert svc._ready is True


@pytest.mark.asyncio
async def test_a_matching_dimension_touches_nothing(stub_qdrant):
    """The overwhelmingly common path: no mismatch, no snapshot, no delete."""
    client = FakeClient(existing_dim=384, points=2750)
    svc = _service(stub_qdrant, client)
    await svc.initialise()
    assert client.deleted == [] and client.snapshots == [] and client.created == []
    assert svc._ready is True


@pytest.mark.asyncio
async def test_the_new_collection_uses_the_active_embedder_dimension(stub_qdrant):
    client = FakeClient(existing_dim=1024, points=0)
    await _service(stub_qdrant, client, embed_dim=384).initialise()
    assert client.created == [(COLLECTION_NAME, 384)]


@pytest.mark.asyncio
async def test_the_refusal_names_a_remedy(stub_qdrant, caplog):
    """A refusal with no route out is just an outage."""
    client = FakeClient(points=10, snapshot_ok=False)
    await _service(stub_qdrant, client).initialise()
    text = caplog.text.lower()
    assert "nothing has been deleted" in text
    assert "embedding_provider" in text
