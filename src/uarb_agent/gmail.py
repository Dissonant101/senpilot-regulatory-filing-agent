"""Gmail API transport: poll the inbox for requests and reply in the same thread."""

from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from google.auth.transport.requests import Request as AuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
# Unread mail stays unread until we've replied, so anything that arrived while the
# agent was down (or that it crashed on) is picked up on the next poll. Spam is
# included because Gmail often files a new sender's first request there.
QUERY = "{in:inbox in:spam} is:unread -from:me"


@dataclass
class Inbound:
    id: str
    thread_id: str
    sender: str
    subject: str
    body: str
    message_id: str
    references: str
    auto: bool  # bounce or auto-reply; never answer these, or two bots can loop
    spam: bool = False


def credentials_from_env() -> Credentials:
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    creds.refresh(AuthRequest())
    return creds


def _text_body(payload: dict) -> str:
    """First text/plain part, depth-first; falls back to stripped text/html."""
    html = ""
    stack = [payload]
    while stack:
        part = stack.pop(0)
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime == "text/plain":
            return base64.urlsafe_b64decode(data).decode("utf-8", "replace")
        if data and mime == "text/html" and not html:
            raw = base64.urlsafe_b64decode(data).decode("utf-8", "replace")
            html = re.sub(r"<[^>]+>", " ", raw)
        stack.extend(part.get("parts", []))
    return html


class Gmail:
    def __init__(self, creds: Credentials):
        self.api = build("gmail", "v1", credentials=creds, cache_discovery=False)
        self.me = self.api.users().getProfile(userId="me").execute()["emailAddress"]

    def unread(self) -> list[Inbound]:
        resp = self.api.users().messages().list(userId="me", q=QUERY, maxResults=20, includeSpamTrash=True).execute()
        out = []
        # Oldest first, so requests are answered in the order they arrived.
        for ref in reversed(resp.get("messages", [])):
            msg = self.api.users().messages().get(userId="me", id=ref["id"], format="full").execute()
            headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
            sender = headers.get("reply-to") or headers.get("from", "")
            out.append(
                Inbound(
                    id=msg["id"],
                    thread_id=msg["threadId"],
                    sender=sender,
                    subject=headers.get("subject", ""),
                    body=_text_body(msg["payload"]),
                    message_id=headers.get("message-id", ""),
                    references=headers.get("references", ""),
                    auto=headers.get("auto-submitted", "no").lower() != "no"
                    or "mailer-daemon" in sender.lower()
                    or "precedence" in headers and headers["precedence"].lower() in ("bulk", "junk", "list"),
                    spam="SPAM" in msg.get("labelIds", []),
                )
            )
        return out

    def reply(self, to: Inbound, recipient: str, body: str, attachment: Path | None = None) -> None:
        msg = EmailMessage()
        msg["To"] = recipient
        msg["From"] = self.me
        # Gmail only threads a reply whose subject matches the original, so never
        # substitute a placeholder for an empty subject.
        subject = to.subject.strip()
        msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}".strip()
        if to.message_id:
            msg["In-Reply-To"] = to.message_id
            msg["References"] = f"{to.references} {to.message_id}".strip()
        msg.set_content(body)
        if attachment:
            msg.add_attachment(attachment.read_bytes(), maintype="application", subtype="zip", filename=attachment.name)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        self.api.users().messages().send(userId="me", body={"raw": raw, "threadId": to.thread_id}).execute()

    def mark_done(self, m: Inbound, not_spam: bool = False) -> None:
        body = {"removeLabelIds": ["UNREAD"]}
        if not_spam:
            # Moving it to the inbox also teaches Gmail to stop filtering this sender.
            body = {"removeLabelIds": ["UNREAD", "SPAM"], "addLabelIds": ["INBOX"]}
        self.api.users().messages().modify(userId="me", id=m.id, body=body).execute()


def authorize() -> None:
    """One-time local helper: prints a refresh token for GMAIL_REFRESH_TOKEN."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": os.environ["GMAIL_CLIENT_ID"],
                "client_secret": os.environ["GMAIL_CLIENT_SECRET"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        SCOPES,
    )
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
