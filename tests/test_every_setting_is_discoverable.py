# -*- coding: utf-8 -*-
"""V12-27 — a fresh clone can discover every setting, and every documented one is real.

    "Every setting `Settings` reads appears in `.env.example` with a stated default."

WHY THE EXISTING TEST COULD NOT CATCH THIS
-------------------------------------------
`test_env_example_documents_what_the_system_uses.py` compares the LIVE `.env` against the
template — and skips when there is no live `.env`. A parked tree has none. CI has none. A
fresh clone has none. So the one check on this file could only run in the single situation
where the problem cannot bite, and reported nothing in every situation where it can.

This one derives the answer from `shared/config.py` with the AST. It never skips.

WHAT IT FOUND, 2026-09-12
--------------------------
`Settings` reads **122** settings. The template named **69**. The 53 it omitted included
the entire GraphDB and Redis host/port pair, every pipeline feature switch, and — worst —
**`SECRET_KEY` and `POSTGRES_USER_PASSWORD`**, two of the four values `STRICT_SECRETS`
refuses to boot on. A fresh clone therefore met a boot refusal naming settings this file
had never mentioned.

THE OTHER DIRECTION, WHICH IS ALSO A DEFECT
--------------------------------------------
24 names in the template are read by NOTHING in this repository — not `Settings`, not any
module, not compose, not a Dockerfile, and not a `database_registry*.yaml` (which is a real
reader: see the note on `${VAR}` interpolation below, and which this test got wrong on its
first run). Setting `MOCK_LLM=true` or `RAG_TOP_K=10` does
nothing at all. That is a FALSE AFFORDANCE: a newcomer configures it, observes no change,
and concludes the system ignores its own configuration.

They are listed below rather than deleted, because "nothing in this repo reads it" is not
the same as "nobody needs it" — a deployment script outside this tree might. The list is
CLOSED: the test fails if it grows, so the next dead setting has to be argued for.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, Set

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "shared" / "config.py"
EXAMPLE = REPO / ".env.example"

#: Where an env var can legitimately be read. Scoped rather than whole-repo: a name
#: appearing in a tracker row or an old README is documentation, not a reader.
_READER_TREES = ("orchestrator", "shared", "scripts", "frontend/src")
_READER_GLOBS = ("*.py", "*.js", "*.jsx", "*.sh")

#: The THIRD reader, and the one this test missed on its first run: every
#: `database_registry*.yaml` carries `${VAR:-default}` placeholders that
#: `adapters/registry.py` resolves against `os.environ`. So CASSANDRA_KEYSPACE,
#: INFLUX_BUCKET, MONGO_COLLECTION, REDIS_TS_URL and TIMESCALE_DATABASE are live settings
#: for any building whose registry names them — they simply do nothing for a building
#: whose registry does not. Calling them dead would have been wrong in the expensive
#: direction: a newcomer told a real setting is dead stops looking for why it had no effect.

#: Names read by nothing in this repository, measured 2026-09-12. CLOSED — adding to it
#: means adding a setting nobody can use, and that needs a reason in writing.
_READ_BY_NOTHING: Dict[str, str] = {
    # An onboarding-wizard demo target. The wizard's "test connection" step takes these
    # through its FORM, not the environment, so the lines are an example to copy rather
    # than configuration the process reads.
    "DEMO_EXTERNAL_HOST": "onboarding demo, entered through the admin form",
    "DEMO_EXTERNAL_PORT": "onboarding demo, entered through the admin form",
    "DEMO_EXTERNAL_USER": "onboarding demo, entered through the admin form",
    "DEMO_EXTERNAL_PASSWORD": "onboarding demo, entered through the admin form",
    "DEMO_EXTERNAL_DATABASE": "onboarding demo, entered through the admin form",
    "WIZTEST_HOST": "datasource-wizard test target, entered through the admin form",
    "WIZTEST_PORT": "datasource-wizard test target, entered through the admin form",
    "WIZTEST_USER": "datasource-wizard test target, entered through the admin form",
    "WIZTEST_PASSWORD": "datasource-wizard test target, entered through the admin form",
    "WIZTEST_DATABASE": "datasource-wizard test target, entered through the admin form",
    # Qdrant collection names are derived per building (`documents_<bldg>` etc.), so these
    # four could never have taken effect.
    "QDRANT_DOCS_COLLECTION": "superseded — collections are derived per building",
    "QDRANT_ONTOLOGY_COLLECTION": "superseded — collections are derived per building",
    "QDRANT_ANALYTICS_COLLECTION": "superseded — collections are derived per building",
    "QDRANT_QUERIES_COLLECTION": "superseded — collections are derived per building",
    # Retrieval knobs that moved into code or per-call arguments.
    "RAG_TOP_K": "superseded — top_k is a per-call argument",
    "SIMILARITY_THRESHOLD": "superseded — thresholds are per-provider in code",
    # Never implemented in this tree.
    "MOCK_LLM": "never implemented — tests inject a fake llm_manager directly",
    "DEV_MODE": "never implemented",
    "SKIP_MODEL_DOWNLOAD": "never implemented",
    "ALLOWED_AUDIO_FORMATS": "never implemented — there is no audio path",
    "MAX_UPLOAD_SIZE_MB": "never implemented — uploads are bounded by the ASGI server",
    # Legacy of the pre-LangGraph stack.
    "POSTGRES_HOST": "legacy — the timeseries Postgres is configured in database_registry.yaml",
    "PG_THINGSBOARD_DB": "legacy ThingsBoard trial",
    "PG_THINGSBOARD_USER": "legacy ThingsBoard trial",
}


def _settings_fields() -> Dict[str, object]:
    """{NAME: default} for every field `Settings` declares, from the AST.

    Parsed rather than imported: importing `shared.config` constructs a Settings instance,
    which reads the live environment — so an import-based check would measure this machine
    rather than the code.
    """
    tree = ast.parse(CONFIG.read_text(encoding="utf-8"))
    out: Dict[str, object] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "Settings"):
            continue
        for st in node.body:
            if not (isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)):
                continue
            name = st.target.id
            if not name.isupper():
                continue
            default: object = "<none>"
            v = st.value
            if isinstance(v, ast.Call) and getattr(v.func, "id", "") == "Field":
                if v.args:
                    try:
                        default = ast.literal_eval(v.args[0])
                    except Exception:
                        default = "<expr>"
                for kw in v.keywords:
                    if kw.arg == "default":
                        try:
                            default = ast.literal_eval(kw.value)
                        except Exception:
                            default = "<expr>"
            elif v is not None:
                try:
                    default = ast.literal_eval(v)
                except Exception:
                    default = "<expr>"
            out[name] = default
    return out


def _example_names() -> Set[str]:
    """Every NAME= in the template, commented or not.

    Commented lines count: a commented line with the real default is documentation of what
    the system does, which is the thing a newcomer needs. Values are never read here — a
    secret in an assertion message is a secret in a log.
    """
    text = EXAMPLE.read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]{2,})\s*=", text, re.M))


def _reader_corpus() -> str:
    parts = []
    for tree in _READER_TREES:
        root = REPO / tree
        if not root.is_dir():
            continue
        for pattern in _READER_GLOBS:
            for f in root.rglob(pattern):
                if "__pycache__" in str(f) or "node_modules" in str(f):
                    continue
                try:
                    parts.append(f.read_text(encoding="utf-8", errors="replace"))
                except OSError:  # pragma: no cover
                    continue
    extra = (
        list(REPO.glob("docker-compose*.yml"))
        + list(REPO.glob("**/Dockerfile*"))
        + list(REPO.glob("**/database_registry*.yaml"))
    )
    for f in extra:
        s = str(f)
        # `.worktrees/` is a git worktree of another branch — its registry is not this
        # deployment's, and counting it would excuse a setting nothing here reads.
        if any(x in s for x in ("node_modules", ".venv", ".worktrees", "__pycache__")):
            continue
        try:
            parts.append(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:  # pragma: no cover
            continue
    return "\n".join(parts)


# ── the half a fresh clone needs ─────────────────────────────────────────────


def test_the_template_exists():
    assert EXAMPLE.is_file(), ".env.example is the only documentation of what to configure"


def test_every_setting_the_code_reads_is_in_the_template():
    """No skip. This is the check that could not run where it mattered."""
    fields = _settings_fields()
    assert len(fields) > 100, f"only {len(fields)} Settings fields parsed — the AST walk broke"

    missing = sorted(set(fields) - _example_names())
    assert not missing, (
        f"{len(missing)} settings the code reads are undiscoverable from .env.example: "
        + ", ".join(missing)
    )


def test_the_two_boot_blocking_secrets_are_named():
    """`STRICT_SECRETS=true` refuses to boot when a password equals its default. Both of
    these were absent, so the refusal named settings the template had never mentioned."""
    names = _example_names()
    for key in ("SECRET_KEY", "POSTGRES_USER_PASSWORD"):
        assert key in names, f"{key} blocks boot and is not in the template"


def test_no_real_secret_rides_along_in_the_template():
    """The template carries CODE DEFAULTS, which are placeholders by construction. A value
    that looks like a generated credential means someone pasted a live one in."""
    for line in EXAMPLE.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip().lstrip("#").strip()
        if "=" not in s:
            continue
        key, _, value = (x.strip() for x in s.partition("="))
        if not any(w in key for w in ("PASSWORD", "SECRET", "TOKEN", "API_KEY")):
            continue
        low = value.lower()
        placeholder = any(
            w in low
            for w in ("change-me", "change_me", "your_", "_here", "example", "xxx", "todo", "<")
        ) or not value
        assert placeholder or not re.fullmatch(r"[A-Za-z0-9+/=]{20,}", value), (
            f"{key} looks like a real credential rather than a placeholder. "
            "The template carries CODE DEFAULTS only."
        )


# ── the half that wastes a newcomer's afternoon ──────────────────────────────


def test_every_documented_name_is_read_by_something():
    """A setting nothing reads is a false affordance: it is configured, nothing changes,
    and the system looks like it ignores its own configuration."""
    fields = set(_settings_fields())
    corpus = _reader_corpus()

    unread = []
    for name in sorted(_example_names() - fields):
        if name in _READ_BY_NOTHING:
            continue
        if name not in corpus:
            unread.append(name)
    assert not unread, (
        "documented in .env.example and read by nothing — either wire it up or add it to "
        "_READ_BY_NOTHING with a reason: " + ", ".join(unread)
    )


def test_the_dead_list_does_not_grow_silently():
    """CLOSED at 24 on 2026-09-12. Growth means a new setting nobody can use."""
    assert len(_READ_BY_NOTHING) <= 24, (
        "the dead-setting list grew; each entry is a line a newcomer can set to no effect"
    )


def test_every_dead_entry_says_why():
    for name, reason in _READ_BY_NOTHING.items():
        assert len(reason) > 15, f"{name} is excused without a reason"


# ── the derived deadline, documented where the value is chosen ───────────────


def test_the_workflow_deadline_rule_is_stated_beside_the_value():
    """CAVEAT-185: a model slower than the workflow deadline cannot serve this pipeline,
    and nothing said so — eight empty plan hashes at exactly 120.0s during the benchmark.

    The rule is DERIVED in config.py, so the template must point at the derivation rather
    than restate a number that would then drift from it.
    """
    text = EXAMPLE.read_text(encoding="utf-8", errors="replace")
    assert "WORKFLOW_TIMEOUT_S" in text
    assert "LLM_TIMEOUT_S" in text

    cfg = CONFIG.read_text(encoding="utf-8")
    assert "is not longer than LLM_TIMEOUT_S" in cfg, (
        "the guard that warns when the deadline cannot outlast one LLM call is gone"
    )


def test_the_host_prerequisites_are_named():
    """MySQL runs on the HOST here — the compose service is disabled — and nothing said so.
    "`docker-compose up -d` is all you need" is a design goal; where it is not yet true the
    gap belongs in the README, not in a newcomer's afternoon."""
    readme = (REPO / "README.md").read_text(encoding="utf-8", errors="replace")

    # A SECTION, not the word appearing somewhere. The first version of this test passed
    # because "prerequisite" occurred at line 1030 inside an unrelated feature table — a
    # test passing for the wrong reason, which is the failure this project keeps finding in
    # its own measurements rather than in the system.
    marker = "\n## Prerequisites\n"
    assert marker in readme, "README.md has no Prerequisites section"

    head = readme.split(marker, 1)[1].split("\n## ", 1)[0].lower()
    for required in ("mysql", "3306", "ollama", ".env"):
        assert required in head, f"the Prerequisites section does not mention {required}"
    assert "commented out" in head or "not yet the whole truth" in head, (
        "the section does not say WHY MySQL is a host prerequisite, so a reader cannot tell "
        "it apart from an optional extra"
    )
