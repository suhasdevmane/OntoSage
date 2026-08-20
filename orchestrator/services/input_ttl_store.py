"""input_ttl_store.py — the ``input/`` folder is the source of truth for TTL; GraphDB mirrors it.

Admin GUI edits mutate an ``input/<file>.ttl`` and re-sync that file's named graph
(``urn:ontosage:ttl:<file>``) — the SAME graph ``ttl_uploader`` loads the file into at
startup. So a capability added/dropped in the GUI persists to the project folder, survives a
GraphDB volume reset, and is picked up identically on the next restart. Every write is backed
up to ``input/.trash/`` first (reversible), and a drop MOVES the file to ``.trash`` so it stays
gone after restart. Building-agnostic: paths and namespace derive from the active building.

Durability guarantees
---------------------
* **Atomic writes** — every file write goes through a temp-file + ``os.replace`` (:func:`
  _atomic_write`), so a crash mid-write can never truncate/blank a file that ``ttl_uploader``
  would then PUT-replace into an empty named graph.
* **Serialized writes** — each read-modify-write is guarded by a cross-process file lock
  (:func:`_file_write_lock`), so concurrent admin writes (or multiple workers/replicas sharing
  the input/ volume) can't lost-update the file.
* **Honest deletes** — a delete edits whichever input/ TTL actually defines the subject, so the
  removal persists across a restart; a graph-only delete is used only when no file backs the
  subject (durable there precisely because nothing reloads it).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from rdflib import Graph, Namespace, URIRef

from shared.building_paths import resolve_building_file
from shared.config import settings
from shared.utils import get_logger

try:
    from filelock import FileLock
    from filelock import Timeout as _FileLockTimeout

    _FILELOCK_AVAILABLE = True
except ImportError:  # pragma: no cover - filelock is a declared dependency
    _FILELOCK_AVAILABLE = False

logger = get_logger(__name__)

_ONTO_NS = "http://ontosage.org/capabilities#"
_TTL_GRAPH_PREFIX = "urn:ontosage:ttl:"

# Seconds to wait for the cross-process write lock before proceeding without it (admin
# writes are low-frequency; on the rare timeout we log and continue rather than hang).
_LOCK_TIMEOUT_S = 15.0


# ─────────────────────────────────────────────────────────────────────────────
# Paths + graph-URI alignment (must match ttl_uploader._graph_uri_for_path)
# ─────────────────────────────────────────────────────────────────────────────


def writable_input_dir() -> Path:
    """First existing input dir (container mount then repo-relative)."""
    for p in (Path("/app/input"), Path("input")):
        if p.exists():
            return p
    return Path("input")


def _trash_dir() -> Path:
    return writable_input_dir() / ".trash"


def graph_uri_for_filename(name: str) -> str:
    """Named graph a TTL file lands in — identical to ttl_uploader's convention."""
    return f"{_TTL_GRAPH_PREFIX}{name.replace(' ', '_')}"


def filename_from_graph_uri(graph_uri: str) -> Optional[str]:
    """Reverse of :func:`graph_uri_for_filename`; None for non-file graphs."""
    if graph_uri.startswith(_TTL_GRAPH_PREFIX):
        return graph_uri[len(_TTL_GRAPH_PREFIX) :] or None
    return None


def _building_namespace(building_id: str) -> str:
    try:
        from orchestrator.services.building_context import resolve_building_context

        return resolve_building_context(building_id).namespace
    except Exception:
        return settings.BUILDING_NAMESPACE


def _backup(path: Path) -> Optional[Path]:
    """Copy an existing file into input/.trash/<name>.<ts>.bak. No-op if absent."""
    if not path.exists():
        return None
    try:
        td = _trash_dir()
        td.mkdir(parents=True, exist_ok=True)
        dest = td / f"{path.name}.{time.strftime('%Y%m%d-%H%M%S')}.bak"
        shutil.copy2(path, dest)
        return dest
    except Exception as e:
        logger.warning(f"[input_ttl_store] backup of {path} failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Durable, serialized file writes
# ─────────────────────────────────────────────────────────────────────────────


@contextmanager
def _file_write_lock() -> Iterator[None]:
    """Cross-process advisory lock serializing input/ file mutations.

    Prevents two concurrent admin writes (or multiple workers/replicas sharing the input/
    volume) from lost-updating a TTL file. Scope is the file read-modify-write ONLY — never
    held across the network graph sync. Best-effort: on a rare acquisition timeout it logs and
    proceeds unlocked rather than hang the request.
    """
    if not _FILELOCK_AVAILABLE:
        yield
        return
    lock = FileLock(str(writable_input_dir() / ".ttl_write.lock"))
    acquired = False
    try:
        try:
            lock.acquire(timeout=_LOCK_TIMEOUT_S)
            acquired = True
        except _FileLockTimeout:
            logger.warning(
                f"[input_ttl_store] write lock busy >{_LOCK_TIMEOUT_S:.0f}s; proceeding without it"
            )
        yield
    finally:
        if acquired:
            lock.release()


def _atomic_write(path: Path, content: str) -> None:
    """Write text atomically: temp file in the same dir + ``os.replace``.

    A plain ``write_text`` truncates in place, so a crash mid-write can blank the file —
    which ``ttl_uploader`` would then PUT-replace into an empty named graph (every triple
    gone). Writing a temp sibling and atomically renaming means a reader/uploader always sees
    either the old file or the fully-written new one, never a torn write. On any failure the
    original file is left untouched.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)  # atomic on POSIX and NTFS
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _file_has_subject(path: Path, subj: URIRef) -> bool:
    """True if ``path`` parses and contains at least one triple about ``subj``."""
    if not path.exists():
        return False
    try:
        g = Graph()
        g.parse(str(path), format="turtle")
        return any(g.triples((subj, None, None)))
    except Exception as e:
        logger.debug(f"[input_ttl_store] subject-check parse failed for {path}: {e}")
        return False


def _find_input_ttl_with_subject(subj: URIRef, *, skip: Optional[Path] = None) -> Optional[Path]:
    """First non-schema ``input/*.ttl`` that defines ``subj`` (or None).

    Lets a GUI delete edit whichever building TTL actually holds the subject, so the removal
    persists across a restart instead of a graph-only delete that ``ttl_uploader`` reloads.
    Shared schema TTLs (Brick / *_schema / REC / s223) are skipped — they never hold amenities
    and parsing them is expensive.
    """
    from orchestrator.services.ttl_uploader import _looks_like_schema

    for path in sorted(writable_input_dir().glob("*.ttl")):
        if skip is not None and path == skip:
            continue
        if _looks_like_schema(path.name):
            continue
        if _file_has_subject(path, subj):
            return path
    return None


# ─────────────────────────────────────────────────────────────────────────────
# GraphDB sync + SHA-cache bookkeeping (keeps restart ingestion consistent)
# ─────────────────────────────────────────────────────────────────────────────


async def _sync_file_to_graph(path: Path, *, client: Optional[Any] = None) -> dict:
    """PUT the file into its named graph (replace) and refresh the SHA cache so the
    next restart treats it as unchanged."""
    from orchestrator.services.ttl_uploader import (
        compute_sha,
        load_cache,
        save_cache,
        upload_to_graphdb,
    )

    ok = await upload_to_graphdb(path, client=client)
    if ok:
        try:
            cache = load_cache()
            cache[str(path)] = compute_sha(path)
            save_cache(cache)
        except Exception as e:  # pragma: no cover - cache is best-effort
            logger.debug(f"[input_ttl_store] SHA-cache update skipped: {e}")
    return {"ok": ok, "graph": graph_uri_for_filename(path.name)}


def _forget_sha(path: Path) -> None:
    """Drop a file's SHA-cache entry so a re-created file re-uploads on restart."""
    try:
        from orchestrator.services.ttl_uploader import load_cache, save_cache

        cache = load_cache()
        if str(path) in cache:
            del cache[str(path)]
            save_cache(cache)
    except Exception as e:  # pragma: no cover
        logger.debug(f"[input_ttl_store] SHA-cache forget skipped: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Capability file operations (rdflib — semantically lossless triple edits)
# ─────────────────────────────────────────────────────────────────────────────


def capabilities_path(building_id: str) -> Path:
    """Resolve the building's capability TTL (existing file preferred, else flat)."""
    existing = resolve_building_file(building_id, f"{building_id}_capabilities.ttl")
    if existing is not None:
        return existing
    return writable_input_dir() / f"{building_id}_capabilities.ttl"


def _capabilities_header(building_id: str) -> str:
    return (
        f"# {building_id} capability facts — TTL-first source of truth (GUI + file managed).\n"
        "# Each amenity is a dual-typed ontosage:Amenity instance answered live by the\n"
        "# CapabilityGraphResolver. Edit here or via the admin console Capabilities tab;\n"
        "# both stay consistent (this file is auto-loaded on restart by ttl_uploader).\n\n"
    )


def _bind_prefixes(g: Graph, building_id: str) -> None:
    g.bind("bldg", Namespace(_building_namespace(building_id)))
    g.bind("ontosage", Namespace(_ONTO_NS))


def _serialize_graph(
    path: Path,
    g: Graph,
    building_id: str,
    *,
    with_header: bool,
    header_text: Optional[str] = None,
) -> None:
    """Atomically serialize ``g`` to ``path``, with the owning file's header when owned.

    ``header_text`` selects which header this file owns (capabilities by default,
    policies for the V5-T43 editor); it is ignored when ``with_header`` is False,
    i.e. when we are editing a file some other tool owns.
    """
    body = g.serialize(format="turtle")
    header = (
        (header_text if header_text is not None else _capabilities_header(building_id))
        if with_header
        else ""
    )
    # An EMPTY owned graph (last amenity/policy deleted) serializes to no @prefix lines,
    # but the startup TTL validator hard-fails a *.ttl that lacks @prefix bldg: — which
    # crash-loops the orchestrator. Ensure the prefix block is present when the body omits
    # it (only the empty case; a non-empty body already declares them). Building-agnostic.
    if with_header and "@prefix bldg:" not in body:
        header += (
            f"@prefix bldg:     <{_building_namespace(building_id)}> .\n"
            f"@prefix ontosage: <{_ONTO_NS}> .\n"
            "@prefix rdfs:     <http://www.w3.org/2000/01/rdf-schema#> .\n\n"
        )
    _atomic_write(path, header + body)


def _write_capabilities(path: Path, g: Graph, building_id: str) -> None:
    _serialize_graph(path, g, building_id, with_header=True)


async def upsert_amenity(
    building_id: str, subject_uri: str, ttl_block: str, *, client: Optional[Any] = None
) -> dict:
    """Add/replace one amenity in the building's capability file, then re-sync its graph."""
    path = capabilities_path(building_id)
    with _file_write_lock():
        g = Graph()
        if path.exists():
            g.parse(str(path), format="turtle")
        _bind_prefixes(g, building_id)
        g.remove((URIRef(subject_uri), None, None))  # replace if it already exists
        g.parse(data=ttl_block, format="turtle")
        _backup(path)
        _write_capabilities(path, g, building_id)
    res = await _sync_file_to_graph(path, client=client)
    return {
        "ok": res["ok"],
        "subject": subject_uri,
        "file": str(path),
        "error": None if res["ok"] else "graph sync failed",
    }


async def _remove_from_file(
    path: Path,
    subj: URIRef,
    building_id: str,
    *,
    with_header: bool,
    header_text: Optional[str] = None,
    client: Optional[Any] = None,
) -> dict:
    """Remove every triple of ``subj`` from ``path`` (backup first), rewrite it atomically,
    then re-sync its named graph. This is what makes a GUI delete durable across restarts."""
    with _file_write_lock():
        g = Graph()
        g.parse(str(path), format="turtle")
        _bind_prefixes(g, building_id)
        g.remove((subj, None, None))
        _backup(path)
        _serialize_graph(path, g, building_id, with_header=with_header, header_text=header_text)
    res = await _sync_file_to_graph(path, client=client)
    return {
        "ok": res["ok"],
        "subject": str(subj),
        "file": str(path),
        "error": None if res["ok"] else "graph sync failed",
    }


async def remove_amenity(
    building_id: str, subject_uri: str, *, client: Optional[Any] = None
) -> dict:
    """Remove an amenity so the deletion PERSISTS across restarts.

    The subject's triples are removed from whichever input/ TTL defines them — the GUI-managed
    capabilities file first, then any other building TTL — and that file's named graph is
    re-synced. Only when the subject exists in NO input file (e.g. inserted straight into
    GraphDB) do we fall back to a graph-only delete, which is durable there precisely because
    no file re-adds it on restart. We never report success for a delete that would silently
    reappear on the next boot.
    """
    subj = URIRef(subject_uri)
    caps = capabilities_path(building_id)

    if _file_has_subject(caps, subj):
        return await _remove_from_file(caps, subj, building_id, with_header=True, client=client)

    other = _find_input_ttl_with_subject(subj, skip=caps)
    if other is not None:
        logger.info(f"[input_ttl_store] amenity {subject_uri} lives in {other.name}; editing it")
        return await _remove_from_file(other, subj, building_id, with_header=False, client=client)

    # Not backed by any input file — a graph-only delete is durable (nothing reloads it).
    from orchestrator.services.ontology_manager import delete_subject

    res = await delete_subject(subject_uri, client=client)
    res["file"] = None
    return res


# ─────────────────────────────────────────────────────────────────────────────
# Access policies (V5-T43) — same durable path as capabilities: the input/ TTL
# stays the source of truth, so a GUI edit and a hand edit converge and the
# change lands in version control as a reviewable diff.
# ─────────────────────────────────────────────────────────────────────────────


def policies_path(building_id: str) -> Path:
    """Resolve the building's policy TTL (existing file preferred, else flat)."""
    existing = resolve_building_file(building_id, f"{building_id}_policies.ttl")
    if existing is not None:
        return existing
    return writable_input_dir() / f"{building_id}_policies.ttl"


def _policies_header(building_id: str) -> str:
    return (
        f"# {building_id}_policies.ttl — AccessPolicy triples (V5-T37/T43).\n"
        "# The PDP evaluates these at every fetch chokepoint; the 0-leak certification\n"
        "# rests on them. Edit here or via the admin console Policies tab; both stay\n"
        "# consistent (auto-loaded on restart by ttl_uploader). Inference-class denials\n"
        "# ('never track individuals') are deliberately NOT editable from the GUI.\n\n"
    )


async def upsert_policy(
    building_id: str, subject_uri: str, ttl_block: str, *, client: Optional[Any] = None
) -> dict:
    """Add/replace one AccessPolicy in the building's policy file, then re-sync its graph.

    BUG-194: re-syncing is NOT sufficient on its own. ``_sync_file_to_graph`` PUTs
    the file into its named graph, which replaces only THAT graph — but the same
    policy triples are also present in the DEFAULT graph, which the PUT never
    touches. The PDP queries the union, so after an edit the subject carried BOTH
    values (measured: minAggregationSensors 14 AND 555 for one policy) and the
    stale one won. The editor reported success, the file was correct, the named
    graph was correct, and enforcement quietly kept using the OLD floor — the
    worst possible failure for a governance surface. Clearing the subject from
    every graph first makes the file the single source of truth.
    """
    path = policies_path(building_id)
    from orchestrator.services.ontology_manager import delete_subject

    # Order matters: purge everywhere, THEN write the file and PUT it back, so the
    # named graph ends up holding exactly one copy.
    purge = await delete_subject(subject_uri, client=client)
    if not purge.get("ok"):
        logger.warning(
            f"[input_ttl_store] could not purge {subject_uri} before upsert "
            f"({purge.get('error')}) — a stale copy may shadow the new value"
        )
    with _file_write_lock():
        g = Graph()
        if path.exists():
            g.parse(str(path), format="turtle")
        _bind_prefixes(g, building_id)
        g.remove((URIRef(subject_uri), None, None))  # replace if it already exists
        g.parse(data=ttl_block, format="turtle")
        _backup(path)
        _atomic_write(path, _policies_header(building_id) + g.serialize(format="turtle"))
    res = await _sync_file_to_graph(path, client=client)
    return {
        "ok": res["ok"],
        "subject": subject_uri,
        "file": str(path),
        "error": None if res["ok"] else "graph sync failed",
    }


async def remove_policy(
    building_id: str, subject_uri: str, *, client: Optional[Any] = None
) -> dict:
    """Remove a policy so the deletion PERSISTS across restarts (see remove_amenity)."""
    subj = URIRef(subject_uri)
    path = policies_path(building_id)
    if _file_has_subject(path, subj):
        # This file is ours, so keep its header AND the @prefix guarantee — deleting
        # the last policy must not leave a prefix-less TTL that fails the startup
        # validator and crash-loops the orchestrator.
        return await _remove_from_file(
            path,
            subj,
            building_id,
            with_header=True,
            header_text=_policies_header(building_id),
            client=client,
        )

    other = _find_input_ttl_with_subject(subj, skip=path)
    if other is not None:
        logger.info(f"[input_ttl_store] policy {subject_uri} lives in {other.name}; editing it")
        return await _remove_from_file(other, subj, building_id, with_header=False, client=client)

    from orchestrator.services.ontology_manager import delete_subject

    res = await delete_subject(subject_uri, client=client)
    res["file"] = None
    return res


# ─────────────────────────────────────────────────────────────────────────────
# Generic file operations (used by the admin Ontology tab)
# ─────────────────────────────────────────────────────────────────────────────


def _replace_subjects(existing: Graph, incoming: Graph) -> None:
    """Delete every incoming URIRef subject (and the blank nodes it owns) from ``existing``.

    This turns an append-merge into an UPSERT: when a sensor is re-registered, its old triples are
    dropped before the new ones are unioned in, so re-registering REPLACES that subject rather than
    leaving stale/duplicate triples. Critically it also removes the blank ``_:ref_*`` external-ref
    node hanging off each sensor — those get a fresh blank-node id on every parse, so a plain union
    would accumulate a duplicate reference node on each re-register. Other subjects (the sensors you
    didn't re-submit) are left untouched, so registration stays additive across sensors.
    """
    from rdflib import BNode

    for subj in set(incoming.subjects()):
        if isinstance(subj, BNode):
            continue  # blank nodes are cleaned via the URIRef that owns them
        for _s, _p, obj in list(existing.triples((subj, None, None))):
            if isinstance(obj, BNode):
                existing.remove((obj, None, None))  # drop the owned external-ref node
        existing.remove((subj, None, None))


async def persist_ttl_file(
    filename: str,
    ttl_text: str,
    *,
    merge: bool = False,
    replace_subjects: bool = False,
    client: Optional[Any] = None,
) -> dict:
    """Write ``input/<filename>`` (backing up any existing copy) and sync its graph.

    ``merge=True`` unions the new triples with the file's current content (rdflib) so an
    append-mode upload keeps existing triples; ``merge=False`` overwrites the file. When
    ``replace_subjects=True`` (implies merge), each incoming URIRef subject is first removed from
    the existing file — an UPSERT: re-submitting a subject replaces it (and its owned blank nodes)
    instead of duplicating, while other subjects are preserved.
    """
    safe = filename.replace(" ", "_")
    if not safe.endswith(".ttl"):
        safe += ".ttl"
    path = writable_input_dir() / safe

    with _file_write_lock():
        if (merge or replace_subjects) and path.exists():
            g = Graph()
            g.parse(str(path), format="turtle")
            incoming = Graph()
            incoming.parse(data=ttl_text, format="turtle")
            if replace_subjects:
                _replace_subjects(g, incoming)
            for triple in incoming:
                g.add(triple)
            _backup(path)
            _atomic_write(path, g.serialize(format="turtle"))
        else:
            _backup(path)
            _atomic_write(path, ttl_text)

    res = await _sync_file_to_graph(path, client=client)
    return {"ok": res["ok"], "file": str(path), "graph": res["graph"]}


async def trash_ttl_file(filename: str, *, client: Optional[Any] = None) -> dict:
    """Move ``input/<filename>`` to input/.trash/ (reversible) and drop its named graph."""
    from orchestrator.services.ontology_manager import drop_named_graph

    safe = filename.replace(" ", "_")
    path = writable_input_dir() / safe
    moved: Optional[str] = None
    if path.exists():
        try:
            td = _trash_dir()
            td.mkdir(parents=True, exist_ok=True)
            dest = td / f"{path.name}.{time.strftime('%Y%m%d-%H%M%S')}.deleted"
            with _file_write_lock():
                shutil.move(str(path), str(dest))
            moved = str(dest)
            _forget_sha(path)
        except Exception as e:
            logger.warning(f"[input_ttl_store] could not move {path} to trash: {e}")

    dropped = await drop_named_graph(graph_uri_for_filename(safe), client=client)
    return {"ok": dropped, "file": str(path), "trashed_to": moved, "dropped": dropped}
