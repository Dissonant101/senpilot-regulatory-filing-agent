import json
import zipfile
from pathlib import Path

import pytest

from uarb_agent.reply import build_zip, compose_body, fit_zip, summarize_counts, summarize_download, summarize_matter
from uarb_agent.uarb import FetchResult, Matter, _parse_header

FIXTURES = Path(__file__).parent / "fixtures"
COUNTS = {"Exhibits": 13, "Key Documents": 6, "Other Documents": 43, "Transcripts": 0, "Recordings": 0}


def m12205(**kw):
    return Matter(
        number="M12205",
        title="Halifax Regional Water Commission - Windsor Street Exchange Redevelopment Project - $69,275,000",
        amount="$69,275,000",
        type="Water",
        category="Capital Expenditure Approvals",
        date_received="04/07/2025",
        date_final="10/23/2025",
        counts=dict(COUNTS),
        **kw,
    )


def test_header_parsing_m12205():
    items = json.loads((FIXTURES / "hdr_M12205.json").read_text())
    m = _parse_header(items, "M12205")
    assert m.title.endswith("Redevelopment Project - $69,275,000")
    assert (m.amount, m.type, m.category) == ("$69,275,000", "Water", "Capital Expenditure Approvals")
    assert (m.date_received, m.date_final) == ("04/07/2025", "10/23/2025")


def test_header_parsing_without_amount():
    items = json.loads((FIXTURES / "hdr_M12383.json").read_text())
    m = _parse_header(items, "M12383")
    assert m.title.startswith("Municipal Boundary - Town of Amherst")
    assert (m.amount, m.type, m.category) == ("", "Municipal Boundaries", "Other")
    assert (m.date_received, m.date_final) == ("07/10/2025", "11/28/2025")


def test_matter_summary():
    assert summarize_matter(m12205()) == (
        "M12205 is about Halifax Regional Water Commission - Windsor Street Exchange Redevelopment Project. "
        "It relates to $69,275,000 and is a Water matter in the Capital Expenditure Approvals category. "
        "The matter had an initial filing on April 7, 2025 and a final filing on October 23, 2025."
    )


def test_matter_summary_skips_missing_fields():
    m = Matter(number="M12383", title="Some Matter", date_received="07/10/2025")
    text = summarize_matter(m)
    assert text == "M12383 is about Some Matter. The matter had an initial filing on July 10, 2025."
    assert "None" not in text and "  " not in text


@pytest.mark.parametrize(
    "counts, expected",
    [
        (COUNTS, "I found 13 Exhibits, 6 Key Documents, and 43 Other Documents, but no Transcripts or Recordings."),
        (
            {"Exhibits": 1, "Key Documents": 0, "Other Documents": 0, "Transcripts": 0, "Recordings": 0},
            "I found 1 Exhibit, but no Key Documents, Other Documents, Transcripts, or Recordings.",
        ),
        ({t: 2 for t in COUNTS}, "I found 2 Exhibits, 2 Key Documents, 2 Other Documents, 2 Transcripts, and 2 Recordings."),
        ({t: 0 for t in COUNTS}, "I didn't find any documents in this matter."),
    ],
)
def test_count_wording(counts, expected):
    assert summarize_counts(counts) == expected


def test_download_wording(tmp_path):
    files = [tmp_path / f"{i}.pdf" for i in range(10)]
    assert summarize_download(FetchResult(m12205(), "Other Documents", files)) == (
        "I downloaded 10 out of 43 Other Documents and attached them as a ZIP."
    )
    one = m12205()
    one.counts["Exhibits"] = 1
    assert "1 out of 1 Exhibit and" in summarize_download(FetchResult(one, "Exhibits", files[:1]))
    assert "no Transcripts in this matter" in summarize_download(FetchResult(m12205(), "Transcripts", []))
    partial = summarize_download(FetchResult(m12205(), "Key Documents", files[:5], failed=1))
    assert "5 out of 6 Key Documents" in partial and "1 file failed to download and was skipped" in partial


def test_body_has_all_sections(tmp_path):
    body = compose_body(FetchResult(m12205(), "Key Documents", [tmp_path / "a.pdf"] * 6))
    assert body.startswith("Hi,") and "6 out of 6 Key Documents" in body and "no Transcripts or Recordings" in body


def test_zip_holds_every_file(tmp_path):
    files = []
    for name in ("102674.pdf", "102454.pdf"):
        (tmp_path / name).write_bytes(b"%PDF-1.4 " + name.encode())
        files.append(tmp_path / name)
    z = build_zip(files, tmp_path / "out.zip")
    with zipfile.ZipFile(z) as zf:
        assert zf.testzip() is None
        assert sorted(zf.namelist()) == ["102454.pdf", "102674.pdf"]


def test_fit_zip_drops_largest_files_until_it_fits(tmp_path):
    import os

    small = tmp_path / "small.pdf"
    small.write_bytes(b"a" * 100)
    big = tmp_path / "big.pdf"
    big.write_bytes(os.urandom(50_000))  # random bytes don't compress
    z, dropped = fit_zip([small, big], tmp_path / "out.zip", max_bytes=10_000)
    assert dropped == ["big.pdf"]
    with zipfile.ZipFile(z) as zf:
        assert zf.namelist() == ["small.pdf"]

    z, dropped = fit_zip([big], tmp_path / "out2.zip", max_bytes=10_000)
    assert z is None and dropped == ["big.pdf"]


def test_download_wording_when_files_too_large(tmp_path):
    files = [tmp_path / f"{i}.pdf" for i in range(6)]
    some = FetchResult(m12205(), "Key Documents", files, too_large=["5.pdf"])
    assert summarize_download(some) == (
        "I downloaded 6 out of 6 Key Documents. 5 are attached as a ZIP; 5.pdf was too large to fit in the email."
    )
    none = FetchResult(m12205(), "Key Documents", files[:1], too_large=["0.pdf"])
    assert "too large to fit in an email, so nothing is attached" in summarize_download(none)
