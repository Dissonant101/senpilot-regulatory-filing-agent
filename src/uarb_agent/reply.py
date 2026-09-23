"""Fixed-template reply text and ZIP packaging (no LLM)."""

from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

from .parser import DOC_TYPES
from .uarb import FetchResult, Matter


def plural(n: int, doc_type: str) -> str:
    """`plural(1, "Key Documents")` -> "1 Key Document"."""
    return f"{n} {doc_type[:-1] if n == 1 else doc_type}"


def join_words(words: list[str], conj: str = "and") -> str:
    if len(words) <= 1:
        return "".join(words)
    if len(words) == 2:
        return f"{words[0]} {conj} {words[1]}"
    return f"{', '.join(words[:-1])}, {conj} {words[-1]}"


def _date(s: str) -> str:
    try:
        d = datetime.strptime(s, "%m/%d/%Y")
    except ValueError:
        return s
    return f"{d:%B} {d.day}, {d.year}"


def _subject(m: Matter) -> str:
    title = m.title
    if m.amount and title.endswith(m.amount):
        title = title[: -len(m.amount)].rstrip(" -–")
    return title


def summarize_matter(m: Matter) -> str:
    sentences = []
    if title := _subject(m):
        sentences.append(f"{m.number} is about {title}.")
    else:
        sentences.append(f"Here's what I found for {m.number}.")

    parts = []
    if m.amount:
        parts.append(f"relates to {m.amount}")
    if m.type and m.category:
        parts.append(f"is a {m.type} matter in the {m.category} category")
    elif m.category:
        parts.append(f"is in the {m.category} category")
    elif m.type:
        parts.append(f"is a {m.type} matter")
    if parts:
        sentences.append(f"It {join_words(parts)}.")

    if m.date_received and m.date_final:
        sentences.append(
            f"The matter had an initial filing on {_date(m.date_received)} "
            f"and a final filing on {_date(m.date_final)}."
        )
    elif m.date_received:
        sentences.append(f"The matter had an initial filing on {_date(m.date_received)}.")
    elif m.date_final:
        sentences.append(f"The matter had a final filing on {_date(m.date_final)}.")
    return " ".join(sentences)


def summarize_counts(counts: dict[str, int]) -> str:
    found = [plural(counts[t], t) for t in DOC_TYPES if counts.get(t)]
    missing = [t for t in DOC_TYPES if not counts.get(t)]
    if not found:
        return "I didn't find any documents in this matter."
    text = f"I found {join_words(found)}"
    if missing:
        text += f", but no {join_words(missing, 'or')}"
    return text + "."


def summarize_download(r: FetchResult) -> str:
    total = r.matter.counts.get(r.doc_type, 0)
    got = len(r.files)
    if total == 0:
        return f"There are no {r.doc_type} in this matter, so nothing is attached."
    if got == 0:
        return f"I couldn't download any of the {plural(total, r.doc_type)}, so nothing is attached. Please try again later."
    text = f"I downloaded {got} out of {plural(total, r.doc_type)} and attached them as a ZIP."
    if r.failed:
        text += f" {r.failed} {'file' if r.failed == 1 else 'files'} failed to download and {'was' if r.failed == 1 else 'were'} skipped."
    return text


def compose_body(r: FetchResult) -> str:
    return "\n\n".join(
        ["Hi,", summarize_matter(r.matter), summarize_counts(r.matter.counts), summarize_download(r), "Regulatory Filing Agent"]
    )


def build_zip(files: list[Path], dest: Path) -> Path:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, arcname=f.name)
    return dest
