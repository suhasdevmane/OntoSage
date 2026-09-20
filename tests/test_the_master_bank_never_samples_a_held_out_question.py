# -*- coding: utf-8 -*-
"""The master bank merges every question source once, and a held-out question is never drawn.

What these pin
--------------
* The holdout is defined ONLY by hash of the spec normal form, and a held-out twin that differs by
  a hyphen or a double space is still caught (excluding too much is harmless, too little voids
  the measurement).
* The sampler draws from ``Bank.tuning()`` only, for every seed and size, and is deterministic.
* No hash file means no sampling (fail closed), a file named ``tail_C*`` is never read as a source,
  and a questions file passed as a hash file fails without echoing a line of it.
* The same question in two sources is one bank entry with a stable id.

Fixtures are tiny and synthetic; the last group runs the real sources and skips when absent.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from pathlib import Path
from typing import List, Optional

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]


def _load():
    name = "_test_master_bank_module"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / "master_bank.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mb = _load()


def _raw(text: str, source: str, group: str = "g") -> "mb.RawQuestion":
    return mb.RawQuestion(text, mb.Appearance(source, group, f"test:{source}"))


def _hash_file(tmp_path: Path, *texts: str) -> Path:
    path = tmp_path / "hashes.txt"
    path.write_text(
        "\n".join(hashlib.sha1(mb.normalise(t).encode("utf-8")).hexdigest() for t in texts) + "\n",
        encoding="utf-8",
    )
    return path


def _many(n: int, source: str = "stakeholder_catalogue_37", groups: int = 3) -> List["mb.RawQuestion"]:
    return [
        _raw(f"{source} question number {i} about thing {i * 7}", source, f"group{i % groups}")
        for i in range(n)
    ]


# ── normalisation and hashing follow the spec exactly ──────────────────────────────────


def test_the_normal_form_is_the_spec():
    assert mb.normalise("What's the CO2 level?") == "whats the co2 level"
    assert mb.normalise("  Room 5.01 - warm?  ") == "room 501  warm"  # spaces are NOT collapsed
    assert mb.sha1_hex("abc") == hashlib.sha1(b"abc").hexdigest()


def test_dedup_key_collapses_spaces_but_the_spec_form_does_not():
    assert mb.dedup_key("Room 5.01 - warm?") == "room 501 warm"


def test_a_hyphen_or_double_space_twin_is_still_caught():
    """A tuning question written 'step-free' or with a double space is excluded when the held-out
    twin was recorded as 'step free' (single space), which is what the spec form gives it."""
    held = "Is there a step free route to the lift"
    held_digest = hashlib.sha1(mb.normalise(held).encode("utf-8")).hexdigest()
    assert held_digest in mb.holdout_digests("Is there a step-free route to the lift?")
    assert held_digest in mb.holdout_digests("Is there a step free  route to the lift")
    # and the plainly identical question, with different case and punctuation
    assert held_digest in mb.holdout_digests("IS THERE A STEP FREE ROUTE TO THE LIFT???")
    assert held_digest not in mb.holdout_digests("Is there a step free route to the stairs")


# ── merging and ids ─────────────────────────────────────────────────────────────────────


def test_the_same_question_in_two_sources_is_one_entry_with_both_sources():
    raw = [
        _raw("Where is the nearest lift?", "phase0"),
        _raw("where is the nearest LIFT", "stakeholder_catalogue_37", "Occupants"),
    ]
    bank = mb.build_bank(raw)
    assert len(bank.questions) == 1
    q = bank.questions[0]
    assert q.primary == "stakeholder_catalogue_37" and q.group == "Occupants"
    assert q.sources == ["stakeholder_catalogue_37", "phase0"]
    assert q.asked_before is True


def test_ids_are_stable_unique_and_independent_of_order():
    raw = _many(200)
    a = mb.build_bank(raw)
    b = mb.build_bank(list(reversed(raw)))
    ids_a = {q.key: q.id for q in a.questions}
    ids_b = {q.key: q.id for q in b.questions}
    assert ids_a == ids_b
    assert len(set(ids_a.values())) == len(ids_a)
    assert all(re.fullmatch(r"MB-[0-9a-f]{12,}", i) for i in ids_a.values())


def test_an_unknown_docs_csv_source_is_kept_under_its_own_label(tmp_path):
    path = tmp_path / "docs.csv"
    path.write_text("ID,Question,Source\nX1,Is it warm?,brand_new_source\n", encoding="utf-8")
    raw = mb.load_docs_csv(path)
    assert [r.appearance.source for r in raw] == ["other:brand_new_source"]


def test_a_blank_row_is_skipped_and_counted():
    bank = mb.build_bank([_raw("real question", "survey"), _raw("?!", "survey")])
    assert len(bank.questions) == 1 and bank.empty_skipped == 1


# ── the holdout ─────────────────────────────────────────────────────────────────────────


def test_a_held_out_question_is_marked_and_leaves_the_tuning_pool(tmp_path):
    held = "which floor has the most desks free this week"
    raw = _many(30) + [_raw(held, "stakeholder_catalogue_37", "group0")]
    hashes = mb.read_hash_file(_hash_file(tmp_path, held))
    bank = mb.build_bank(raw, hashes)
    assert [q.text for q in bank.holdout()] == [held]
    assert held not in [q.text for q in bank.tuning()]
    assert len(bank.tuning()) == 30


@pytest.mark.parametrize("seed", range(40))
def test_no_sample_ever_contains_a_held_out_question(tmp_path, seed):
    raw = _many(120, "stakeholder_catalogue_37", 5) + _many(80, "survey", 4)
    held = [r.text for r in raw[::9]]  # 22 held-out questions across both sources
    bank = mb.build_bank(raw, mb.read_hash_file(_hash_file(tmp_path, *held)))
    assert len(bank.holdout()) == len(held)
    for n in (1, 7, 60, 500):  # 500 is more than the pool: it returns the whole tuning pool
        drawn = mb.sample(bank, n, seed)
        assert not any(q.holdout for q in drawn)
        assert not {q.text for q in drawn} & set(held)
        assert len(drawn) == min(n, len(bank.tuning()))


def test_a_source_filter_and_fresh_only_still_never_return_a_held_out_question(tmp_path):
    raw = _many(60, "stakeholder_catalogue_37") + [_raw(f"already asked {i}", "demo", "d") for i in range(5)]
    held = [r.text for r in raw[:10]]
    bank = mb.build_bank(raw, mb.read_hash_file(_hash_file(tmp_path, *held)))
    drawn = mb.sample(bank, 100, 3, ["stakeholder_catalogue_37"], fresh_only=True)
    assert drawn and all(q.primary == "stakeholder_catalogue_37" and not q.asked_before for q in drawn)
    assert not {q.text for q in drawn} & set(held)


def test_a_sample_is_deterministic_and_the_seed_changes_it():
    bank = mb.build_bank(_many(300, "stakeholder_catalogue_37", 6) + _many(300, "survey", 5))
    a = [q.id for q in mb.sample(bank, 40, 11)]
    b = [q.id for q in mb.sample(bank, 40, 11)]
    c = [q.id for q in mb.sample(bank, 40, 12)]
    assert a == b
    assert a != c


def test_the_sample_is_stratified_by_source_and_group():
    bank = mb.build_bank(_many(300, "stakeholder_catalogue_37", 6) + _many(30, "survey", 3))
    drawn = mb.sample(bank, 33, 5)
    strata = {(q.primary, q.group) for q in drawn}
    assert len(strata) == 9  # all 6 + 3 strata are present: the sample is at least that big
    per = {}
    for q in drawn:
        per[(q.primary, q.group)] = per.get((q.primary, q.group), 0) + 1
    assert min(per.values()) >= 1


# ── allocation ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["proportional", "equal"])
@pytest.mark.parametrize("n", [0, 1, 4, 10, 23, 100, 10_000])
def test_allocation_sums_to_the_request_and_never_exceeds_a_stratum(mode, n):
    sizes = {("a", "x"): 1, ("a", "y"): 4, ("b", "z"): 50, ("c", "w"): 200}
    alloc = mb.allocate(sizes, n, mode)
    assert sum(alloc.values()) == min(n, sum(sizes.values()))
    assert all(0 <= alloc[k] <= sizes[k] for k in sizes)
    if n >= len(sizes):
        assert all(v >= 1 for v in alloc.values())


def test_equal_allocation_is_as_even_as_the_sizes_allow():
    alloc = mb.allocate({("a", "x"): 2, ("a", "y"): 100, ("b", "z"): 100}, 30, "equal")
    assert alloc[("a", "x")] == 2
    assert abs(alloc[("a", "y")] - alloc[("b", "z")]) <= 1


# ── failing closed ──────────────────────────────────────────────────────────────────────


def test_no_hash_file_means_no_bank_for_sampling(tmp_path):
    with pytest.raises(mb.HoldoutHashesMissing):
        mb.load_bank(str(tmp_path / "does_not_exist.txt"), require_holdout=True)


def test_the_cli_refuses_to_sample_without_a_hash_file(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(mb.HASH_FILE_ENV, raising=False)
    monkeypatch.setattr(mb, "DEFAULT_HASH_FILE", tmp_path / "absent.txt")
    assert mb.main(["--sample", "5"]) == 2
    assert "holdout" in capsys.readouterr().err


def test_the_env_var_names_the_hash_file(tmp_path, monkeypatch):
    path = _hash_file(tmp_path, "some question")
    monkeypatch.setenv(mb.HASH_FILE_ENV, str(path))
    assert mb.find_hash_file(None) == path
    assert mb.find_hash_file("explicit.txt") == Path("explicit.txt")


def test_a_file_named_tail_c_is_never_read_as_a_source(tmp_path):
    with pytest.raises(mb.HeldOutPathError):
        mb.load_text_lines(tmp_path / "tail_C_2026-09-19.txt", "tail_c")  # the file need not exist
    with pytest.raises(mb.HeldOutPathError):
        mb.load_probe(tmp_path / "TAIL_C_cases.json")
    with pytest.raises(mb.HeldOutPathError):
        mb.load_phase0(tmp_path / "tail_c_bank.jsonl")


def test_a_questions_file_passed_as_hashes_fails_without_echoing_it(tmp_path):
    path = tmp_path / "questions.txt"
    path.write_text("which floor has the warmest secret question\n", encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        mb.read_hash_file(path)
    assert "secret" not in str(caught.value) and "warmest" not in str(caught.value)
    assert "line 1" in str(caught.value)


def test_hash_file_comments_and_blank_lines_are_ignored(tmp_path):
    good = hashlib.sha1(b"x").hexdigest()
    path = tmp_path / "h.txt"
    path.write_text(f"# note\n\n{good}\n{good.upper()}\n", encoding="utf-8")
    assert mb.read_hash_file(path) == {good}


# ── emitting ────────────────────────────────────────────────────────────────────────────


def test_emit_writes_the_ask_questions_format_and_a_sidecar(tmp_path):
    raw = [_raw("# starts with a hash", "survey"), _raw("Is the lift working?", "survey")]
    bank = mb.build_bank(raw)
    out = tmp_path / "out.txt"
    mb.emit(bank.questions, out, "line one\nline two")
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[:2] == ["# line one", "# line two"]
    body = [line for line in lines if not line.startswith("#")]
    assert sorted(body) == ["Is the lift working?", "starts with a hash"]
    side = (tmp_path / "out.txt.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(side) == 2 and '"id": "MB-' in side[0]


# ── the real sources ────────────────────────────────────────────────────────────────────

_REAL = all(p.is_file() for p in mb.PATHS.values())


@pytest.mark.skipif(not _REAL, reason="the real question sources are not all present")
def test_the_real_sources_merge_and_a_real_holdout_stays_out(tmp_path):
    empty: Optional[str] = str(tmp_path / "none.txt")
    (tmp_path / "none.txt").write_text("", encoding="utf-8")
    plain = mb.load_bank(empty, require_holdout=False)
    assert plain.raw_counts["stakeholder_catalogue_37"] >= 2960 and plain.raw_counts["synthetic"] >= 1100
    assert plain.raw_counts["survey"] > 6000
    assert len({q.id for q in plain.questions}) == len(plain.questions)
    # Hold out three real questions from three different sources and rebuild.
    picks = [next(q for q in plain.questions if q.primary == s) for s in ("stakeholder_catalogue_37", "survey")]
    picks.append(next(q for q in plain.questions if q.primary == "synthetic"))
    path = _hash_file(tmp_path, *[q.text for q in picks])
    guarded = mb.load_bank(str(path), require_holdout=True)
    assert {q.id for q in guarded.holdout()} == {q.id for q in picks}
    assert len(guarded.tuning()) == len(plain.questions) - 3
    for seed in range(5):
        drawn = mb.sample(guarded, 400, seed)
        assert not {q.id for q in drawn} & {q.id for q in picks}
