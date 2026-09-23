"""Regulatory Filing Agent: email a UARB matter number and document type, get a ZIP back."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from .parser import DOC_TYPES, ParseError, parse_request
from .reply import compose_body, fit_zip
from .uarb import MatterNotFound, fetch

log = logging.getLogger("uarb_agent")

MAX_DOCS = 10
MAX_ATTEMPTS = 3
# Gmail rejects messages over 25 MB, and base64 encoding inflates attachments by a third.
MAX_ZIP_BYTES = 18 * 1024 * 1024


async def handle(gmail, msg) -> bool:
    """Answer one email. Returns True if it was a real request (worth rescuing from spam)."""
    try:
        req = parse_request(msg.subject, msg.body, msg.sender)
    except ParseError as exc:
        if msg.spam:
            # Real spam: replying would confirm the address to spammers.
            log.info("ignoring spam %s from %s", msg.id, msg.sender)
            return False
        log.info("rejecting %s: %s", msg.id, exc)
        gmail.reply(msg, msg.sender, f"Hi,\n\n{exc}\n\nExample request: “Other Documents files from M12205”.\n\nRegulatory Filing Agent")
        return False

    log.info("request %s: %s %s for %s", msg.id, req.matter, req.doc_type, req.sender)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            result = await fetch(req.matter, req.doc_type, Path(tmp) / "docs", limit=MAX_DOCS)
        except MatterNotFound:
            gmail.reply(
                msg,
                req.sender,
                f"Hi,\n\nI couldn't find matter {req.matter} on the UARB public documents database. "
                "Please check the number and try again.\n\nRegulatory Filing Agent",
            )
            return True
        attachment = None
        if result.files:
            attachment, result.too_large = fit_zip(
                result.files, Path(tmp) / f"{req.matter} {req.doc_type}.zip", MAX_ZIP_BYTES
            )
        gmail.reply(msg, req.sender, compose_body(result), attachment)
    return True


async def run(poll_seconds: int) -> None:
    from .gmail import Gmail, credentials_from_env

    gmail = Gmail(credentials_from_env())
    log.info("watching %s every %ss for requests (%s)", gmail.me, poll_seconds, ", ".join(DOC_TYPES))
    attempts: dict[str, int] = {}
    while True:
        try:
            for msg in gmail.unread():
                is_request = False
                if msg.auto:
                    log.info("skipping automated message %s from %s", msg.id, msg.sender)
                else:
                    try:
                        is_request = await handle(gmail, msg)
                    except Exception:
                        # Leave it unread so the next poll retries (the UARB site is flaky);
                        # give up with an apology after a few tries so one bad email can't wedge the loop.
                        attempts[msg.id] = attempts.get(msg.id, 0) + 1
                        log.exception("failed on %s (attempt %d)", msg.id, attempts[msg.id])
                        if attempts[msg.id] < MAX_ATTEMPTS:
                            continue
                        gmail.reply(
                            msg,
                            msg.sender,
                            "Hi,\n\nSorry, something went wrong while fetching your documents from the UARB site. "
                            "Please try again later.\n\nRegulatory Filing Agent",
                        )
                attempts.pop(msg.id, None)
                gmail.mark_done(msg, not_spam=msg.spam and is_request)
        except Exception:
            log.exception("poll failed")
        await asyncio.sleep(poll_seconds)


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run(int(os.environ.get("POLL_SECONDS", "30"))))
