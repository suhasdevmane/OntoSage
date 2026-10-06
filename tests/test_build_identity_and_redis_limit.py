"""/health provenance (code_sha, mounted_sha) and the bldg1 Redis memory cap."""

import re
from pathlib import Path

import pytest

from orchestrator.services.build_provenance import build_identity, read_git_head_sha

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
SHA = "0123456789abcdef0123456789abcdef01234567"
SHA2 = "fedcba9876543210fedcba9876543210fedcba98"


def _repo(tmp_path: Path, head: str) -> Path:
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text(head + "\n", encoding="utf-8")
    return tmp_path


def test_symbolic_head_resolves_through_the_loose_ref(tmp_path):
    root = _repo(tmp_path, "ref: refs/heads/main")
    (root / ".git" / "refs" / "heads" / "main").write_text(SHA + "\n", encoding="utf-8")
    assert read_git_head_sha(root) == SHA


def test_symbolic_head_falls_back_to_packed_refs(tmp_path):
    root = _repo(tmp_path, "ref: refs/heads/main")
    (root / ".git" / "packed-refs").write_text(
        f"# pack-refs with: peeled\n{SHA2} refs/heads/main\n", encoding="utf-8"
    )
    assert read_git_head_sha(root) == SHA2


def test_detached_head_is_the_commit_itself(tmp_path):
    root = _repo(tmp_path, SHA)
    assert read_git_head_sha(root) == SHA


def test_worktree_file_is_followed_to_the_shared_refs(tmp_path):
    common = tmp_path / "main-repo" / ".git"
    (common / "refs" / "heads").mkdir(parents=True)
    (common / "refs" / "heads" / "feature").write_text(SHA + "\n", encoding="utf-8")
    gitdir = common / "worktrees" / "wt"
    gitdir.mkdir(parents=True)
    (gitdir / "HEAD").write_text("ref: refs/heads/feature\n", encoding="utf-8")
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
    checkout = tmp_path / "wt"
    checkout.mkdir()
    (checkout / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    assert read_git_head_sha(checkout) == SHA


def test_no_git_directory_gives_none(tmp_path):
    assert read_git_head_sha(tmp_path) is None


def test_garbage_head_gives_none(tmp_path):
    root = _repo(tmp_path, "not a ref and not a sha")
    assert read_git_head_sha(root) is None


def test_build_identity_reports_baked_sha_and_mounted_head(tmp_path, monkeypatch):
    root = _repo(tmp_path, SHA)
    monkeypatch.setenv("BUILD_SHA", "abc123def456")
    assert build_identity(root) == {"code_sha": "abc123def456", "mounted_sha": SHA}


def test_build_identity_says_unknown_when_the_image_has_no_sha(tmp_path, monkeypatch):
    monkeypatch.delenv("BUILD_SHA", raising=False)
    ident = build_identity(tmp_path)
    assert ident == {"code_sha": "unknown", "mounted_sha": None}


def test_health_endpoint_reports_both_fields():
    text = (REPO / "orchestrator" / "main.py").read_text(encoding="utf-8")
    health = text[text.index("async def health_check") :]
    health = health[: health.index("# Authentication helper")]
    assert "**build_identity()" in health


def test_bldg1_redis_is_capped_at_4gb_with_the_policy_unchanged():
    text = (REPO / "docker-compose.bldg1.yml").read_text(encoding="utf-8")
    redis_block = text[text.index("\n  redis:\n") : text.index("\n  graphdb-rag-service:")]
    assert "--maxmemory 4gb" in redis_block
    assert "--maxmemory 2gb" not in redis_block
    assert re.search(r"--maxmemory-policy allkeys-lru\b", redis_block)
