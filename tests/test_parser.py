import pytest

from uarb_agent.parser import ParseError, parse_request

SENDER = "Ana Analyst <ana@example.com>"


@pytest.mark.parametrize(
    "subject, body, matter, doc_type",
    [
        # The example from the assignment.
        ("", "Other Documents files from M12205", "M12205", "Other Documents"),
        ("Request", "Hi, can you send me the exhibits for m12383? Thanks", "M12383", "Exhibits"),
        ("M12205 key docs", "", "M12205", "Key Documents"),
        ("", "Please grab the Key Document filings in matter M12205.", "M12205", "Key Documents"),
        ("Transcript request", "Need the hearing transcript from M12383", "M12383", "Transcripts"),
        ("", "Could I get recordings for M12205 please", "M12205", "Recordings"),
        ("", "other-docs, M12383", "M12383", "Other Documents"),
        ("", "Exhibit list for M12205, please", "M12205", "Exhibits"),
        ("", "Send the M12205 audio", "M12205", "Recordings"),
    ],
)
def test_parses_wordings(subject, body, matter, doc_type):
    req = parse_request(subject, body, SENDER)
    assert (req.matter, req.doc_type, req.sender) == (matter, doc_type, "ana@example.com")


def test_same_matter_twice_is_one_matter():
    assert parse_request("M12205 exhibits", "Exhibits from M12205", SENDER).matter == "M12205"


def test_ignores_quoted_history():
    body = "Now the transcripts for M12383\n\n> Other Documents files from M12205"
    req = parse_request("", body, SENDER)
    assert (req.matter, req.doc_type) == ("M12383", "Transcripts")


@pytest.mark.parametrize(
    "body, fragment",
    [
        ("Other Documents please", "couldn't find a matter number"),
        ("Exhibits from M12205 and M12383", "more than one matter"),
        ("Everything from M12205", "which one document type"),
        ("Exhibits and transcripts from M12205", "I saw: Exhibits, Transcripts"),
        ("Exhibits from M1220", "couldn't find a matter number"),  # 4 digits
        ("Exhibits from M122055", "couldn't find a matter number"),  # 6 digits
    ],
)
def test_rejects_bad_input(body, fragment):
    with pytest.raises(ParseError, match=fragment):
        parse_request("", body, SENDER)


def test_rejects_missing_sender():
    with pytest.raises(ParseError, match="sender"):
        parse_request("", "Exhibits from M12205", "")
