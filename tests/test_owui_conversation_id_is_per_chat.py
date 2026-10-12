"""BUG-1484: an Open WebUI chat gets its own conversation; two people never share one.

Open WebUI 0.8.x forwards the chat id as X-OpenWebUI-Chat-Id. The /v1 handler read only X-Chat-Id,
so every UI chat fell back to a hash of its first message under the shared API username: two
participants who opened with the same question (the study's practice question, for one) shared a
conversation state and session summary.
"""

import pytest
from starlette.datastructures import Headers

from orchestrator.main import owui_conversation_id

pytestmark = pytest.mark.unit

MSGS = [{"role": "user", "content": "What floors does this building have?"}]


def test_open_webui_chat_id_header_is_used():
    h = Headers({"X-OpenWebUI-Chat-Id": "9d39a055-3398-41b8-93db-cfb9833d31b5"})
    assert (
        owui_conversation_id(h, MSGS, "q", "openwebui_user")
        == "owui_9d39a055-3398-41b8-93db-cfb9833d31b5:openwebui_user"
    )


def test_x_chat_id_still_wins_for_the_harnesses():
    h = Headers({"X-Chat-Id": "regr-1", "X-OpenWebUI-Chat-Id": "other"})
    assert owui_conversation_id(h, MSGS, "q", "openwebui_user") == "owui_regr-1:openwebui_user"


def test_fallback_never_puts_two_people_in_one_conversation():
    a = owui_conversation_id(
        Headers({"X-OpenWebUI-User-Email": "p01@study.example.com"}), MSGS, "q", "openwebui_user"
    )
    b = owui_conversation_id(
        Headers({"X-OpenWebUI-User-Email": "p02@study.example.com"}), MSGS, "q", "openwebui_user"
    )
    assert a != b
    assert (
        a.startswith("owui_") and a.split(":")[0] == b.split(":")[0]
    )  # same first message, different person


def test_fallback_is_stable_for_one_person_and_ignores_email_case():
    a = owui_conversation_id(
        Headers({"X-OpenWebUI-User-Email": "P01@study.example.com"}), MSGS, "q", "u"
    )
    b = owui_conversation_id(
        Headers({"X-OpenWebUI-User-Email": "p01@study.example.com "}), MSGS, "q", "u"
    )
    assert a == b


def test_fallback_without_any_identity_keeps_the_old_shape():
    cid = owui_conversation_id(Headers({}), MSGS, "q", "openwebui_user")
    assert (
        cid.startswith("owui_")
        and cid.endswith(":openwebui_user")
        and len(cid.split(":")[0]) == len("owui_") + 16
    )
