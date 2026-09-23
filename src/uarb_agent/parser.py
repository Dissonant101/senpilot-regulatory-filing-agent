"""Rule-based parsing of inbound request emails (no LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from email.utils import parseaddr

# The five document tabs on a UARB matter page, in the order the site shows them.
DOC_TYPES = ("Exhibits", "Key Documents", "Other Documents", "Transcripts", "Recordings")

MATTER_RE = re.compile(r"\bM\d{5}\b", re.IGNORECASE)

# Each pattern tolerates singular/plural and common abbreviations. "Key" and "other"
# are checked before the bare word "documents" can match anything else.
_TYPE_PATTERNS = {
    "Exhibits": re.compile(r"\bexhibits?\b", re.IGNORECASE),
    "Key Documents": re.compile(r"\bkey[\s-]*doc(?:ument)?s?\b", re.IGNORECASE),
    "Other Documents": re.compile(r"\bother[\s-]*doc(?:ument)?s?\b", re.IGNORECASE),
    "Transcripts": re.compile(r"\btranscripts?\b", re.IGNORECASE),
    "Recordings": re.compile(r"\b(?:recordings?|audio)\b", re.IGNORECASE),
}


class ParseError(ValueError):
    """The email can't be turned into a request; the message is sent back to the user."""


@dataclass(frozen=True)
class Request:
    matter: str
    doc_type: str
    sender: str


def parse_request(subject: str, body: str, sender: str) -> Request:
    text = f"{subject}\n{body}"
    # Ignore quoted reply history so an earlier message in the thread can't add a match.
    text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">"))

    _, address = parseaddr(sender)
    if not address:
        raise ParseError("I couldn't read the sender address on your email.")

    matters = sorted({m.upper() for m in MATTER_RE.findall(text)})
    if not matters:
        raise ParseError(
            "I couldn't find a matter number in your email. "
            "Matter numbers start with M followed by 5 digits, e.g. M12205."
        )
    if len(matters) > 1:
        raise ParseError(
            f"Your email mentions more than one matter ({', '.join(matters)}). "
            "Please send one request per matter."
        )

    types = [t for t, pat in _TYPE_PATTERNS.items() if pat.search(text)]
    if len(types) != 1:
        found = f" (I saw: {', '.join(types)})" if types else ""
        raise ParseError(
            f"I couldn't tell which one document type you want{found}. "
            f"Please name exactly one of: {', '.join(DOC_TYPES)}."
        )

    return Request(matter=matters[0], doc_type=types[0], sender=address)
