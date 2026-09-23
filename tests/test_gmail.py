import base64
from email import message_from_bytes
from unittest.mock import MagicMock

import pytest

from uarb_agent.gmail import Gmail, Inbound


def sent_subject(subject):
    g = Gmail.__new__(Gmail)
    g.api, g.me = MagicMock(), "agent@example.com"
    msg = Inbound("id", "thread", "a@example.com", subject, "", "<m1@x>", "", False)
    g.reply(msg, "a@example.com", "body")
    body = g.api.users().messages().send.call_args.kwargs["body"]
    assert body["threadId"] == "thread"
    return message_from_bytes(base64.urlsafe_b64decode(body["raw"]))


@pytest.mark.parametrize(
    "original, expected",
    [("", "Re:"), ("M12205 docs", "Re: M12205 docs"), ("Re: M12205 docs", "Re: M12205 docs")],
)
def test_reply_subject_matches_original_so_gmail_threads_it(original, expected):
    sent = sent_subject(original)
    assert sent["Subject"] == expected
    assert sent["In-Reply-To"] == "<m1@x>"
