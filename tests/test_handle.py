import asyncio
from unittest.mock import MagicMock

from uarb_agent import handle
from uarb_agent.gmail import Inbound


def inbound(body, spam):
    return Inbound("id", "thread", "a@example.com", "", body, "<m@x>", "", auto=False, spam=spam)


def test_junk_in_spam_gets_no_reply():
    gmail = MagicMock()
    assert asyncio.run(handle(gmail, inbound("Cheap watches!!!", spam=True))) is False
    gmail.reply.assert_not_called()


def test_bad_request_in_inbox_gets_error_reply():
    gmail = MagicMock()
    assert asyncio.run(handle(gmail, inbound("Cheap watches!!!", spam=False))) is False
    assert "couldn't find a matter number" in gmail.reply.call_args.args[2]


def test_real_request_in_spam_is_answered(monkeypatch):
    import uarb_agent

    async def not_found(*a, **kw):
        raise uarb_agent.MatterNotFound("M99999")

    monkeypatch.setattr(uarb_agent, "fetch", not_found)
    gmail = MagicMock()
    assert asyncio.run(handle(gmail, inbound("Key docs from M99999", spam=True))) is True
    assert "couldn't find matter M99999" in gmail.reply.call_args.args[2]
