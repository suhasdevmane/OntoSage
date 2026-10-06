"""Backup passphrase helper: keyring mocked, prompts injected. No real Credential Manager use."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import _backup_secret as sec  # noqa: E402

pytestmark = pytest.mark.unit

GOOD = "a long enough passphrase"


class FakeKeyring:
    def __init__(self, stored=None, fail_get=False):
        self.store = {}
        self.fail_get = fail_get
        self.set_calls = []
        if stored is not None:
            self.store[(sec.SERVICE, sec.USERNAME)] = stored

    def get_password(self, service, username):
        if self.fail_get:
            raise RuntimeError("no backend")
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password
        self.set_calls.append((service, username))


def _no_prompt(_msg):
    pytest.fail("must not prompt when a passphrase is stored")


def test_stored_passphrase_is_returned_without_prompting():
    kr = FakeKeyring(stored=GOOD)
    assert sec.get_passphrase(keyring_mod=kr, prompt=_no_prompt, interactive=True) == GOOD
    assert kr.set_calls == []


def test_absent_and_not_interactive_fails_with_the_setup_command():
    kr = FakeKeyring()
    with pytest.raises(sec.PassphraseError, match="--set"):
        sec.get_passphrase(keyring_mod=kr, interactive=False)


def test_new_passphrase_is_confirmed_and_stored_on_yes():
    kr = FakeKeyring()
    answers = iter([GOOD, GOOD])
    got = sec.get_passphrase(
        creating=True,
        keyring_mod=kr,
        interactive=True,
        prompt=lambda _m: next(answers),
        input_fn=lambda _m: "y",
    )
    assert got == GOOD
    assert kr.set_calls == [(sec.SERVICE, sec.USERNAME)]
    assert kr.store[(sec.SERVICE, sec.USERNAME)] == GOOD


def test_declining_to_store_does_not_store():
    kr = FakeKeyring()
    answers = iter([GOOD, GOOD])
    got = sec.get_passphrase(
        creating=True,
        keyring_mod=kr,
        interactive=True,
        prompt=lambda _m: next(answers),
        input_fn=lambda _m: "n",
    )
    assert got == GOOD
    assert kr.set_calls == []


def test_mismatched_confirmation_is_refused():
    kr = FakeKeyring()
    answers = iter([GOOD, GOOD + "x"])
    with pytest.raises(sec.PassphraseError, match="do not match"):
        sec.get_passphrase(
            creating=True,
            keyring_mod=kr,
            interactive=True,
            prompt=lambda _m: next(answers),
            input_fn=lambda _m: "y",
        )
    assert kr.set_calls == []


def test_short_new_passphrase_is_refused():
    kr = FakeKeyring()
    answers = iter(["short", "short"])
    with pytest.raises(sec.PassphraseError, match="at least"):
        sec.get_passphrase(
            creating=True,
            keyring_mod=kr,
            interactive=True,
            prompt=lambda _m: next(answers),
            input_fn=lambda _m: "y",
        )


def test_restore_prompts_once_and_does_not_require_the_minimum_length():
    kr = FakeKeyring()
    prompts = []

    def prompt(msg):
        prompts.append(msg)
        return "old"

    got = sec.get_passphrase(
        creating=False, keyring_mod=kr, interactive=True, prompt=prompt, input_fn=lambda _m: "n"
    )
    assert got == "old"
    assert len(prompts) == 1


def test_credential_manager_failure_is_reported_not_swallowed():
    with pytest.raises(sec.PassphraseError, match="Credential Manager unavailable"):
        sec.get_passphrase(keyring_mod=FakeKeyring(fail_get=True), interactive=True)


def test_helper_never_reads_the_env_file_or_settings():
    source = (SCRIPTS / "_backup_secret.py").read_text(encoding="utf-8")
    assert "shared.config" not in source
    assert "environ" not in source
    assert "dotenv" not in source
