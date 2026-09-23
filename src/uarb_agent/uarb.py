"""Playwright scraper for the UARB WebDirect (FileMaker) public documents database."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PWTimeout, async_playwright

from .parser import DOC_TYPES

log = logging.getLogger(__name__)

URL = "https://uarb.novascotia.ca/fmi/webd/UARB15"
TAB_RE = re.compile(r"^(" + "|".join(DOC_TYPES) + r")\s*-\s*(\d+)$")
AMOUNT_RE = re.compile(r"\$\s?[\d,]+(?:\.\d{2})?")


class MatterNotFound(LookupError):
    pass


@dataclass
class Matter:
    number: str
    title: str = ""
    amount: str = ""
    type: str = ""
    category: str = ""
    date_received: str = ""
    date_final: str = ""
    counts: dict[str, int] = field(default_factory=dict)


@dataclass
class FetchResult:
    matter: Matter
    doc_type: str
    files: list[Path]
    failed: int = 0
    too_large: list[str] = field(default_factory=list)  # downloaded but left out of the email


# Collects every visible text widget above the document tabs with its position.
# FileMaker WebDirect has no stable semantic markup, so metadata is read by column:
# each value sits under a header label ("Title - Description", "Type", ...).
_HEADER_JS = """(tabTop) => {
  const out = [];
  for (const e of document.querySelectorAll('div, span, a')) {
    const t = (e.innerText || '').trim();
    if (!t) continue;
    if ([...e.children].some(c => (c.innerText || '').trim() === t)) continue;  // keep innermost
    const r = e.getBoundingClientRect();
    if (r.width === 0 || r.y >= tabTop || r.y < 80) continue;
    out.push({x: r.x, y: r.y, t});
  }
  return out;
}"""

_LABELS = {
    "Matter No": "number",
    "Title - Description": "title",
    "Type": "type",
    "Date Received": "date_received",
    "Decision Date": "date_final",
    "Date Final": "date_final",
    "Outcome": "outcome",
}


def _parse_header(items: list[dict], number: str) -> Matter:
    # A header cell can stack two labels ("Type\nCategory"); the first names the column.
    items = [dict(it, t=it["t"].split("\n")[0].strip(), multi="\n" in it["t"]) for it in items]
    labels = sorted(
        {(it["x"], it["y"], _LABELS[it["t"]]) for it in items if it["t"] in _LABELS},
        key=lambda a: a[0],
    )
    label_bottom = max((y for _, y, _ in labels), default=0) + 25
    columns: dict[str, list[tuple[float, str]]] = {}
    for it in items:
        if it["multi"] or it["y"] < label_bottom or it["t"] in _LABELS or it["t"] in ("Status", "Category", "Submissions"):
            continue
        col = None
        for x, _, name in labels:
            if x <= it["x"] + 20:  # labels are indented a little past their values
                col = name
        if col:
            columns.setdefault(col, []).append((it["y"], it["t"]))

    def rows(name: str) -> list[str]:
        seen, out = set(), []
        for _, t in sorted(columns.get(name, [])):
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out

    m = Matter(number=number)
    title_rows = rows("title")
    m.title = title_rows[0] if title_rows else ""
    if amount := AMOUNT_RE.search(m.title):
        m.amount = amount.group(0).replace(" ", "")
    type_rows = rows("type")
    m.type = type_rows[0] if type_rows else ""
    m.category = type_rows[1] if len(type_rows) > 1 else ""
    m.date_received = next(iter(rows("date_received")), "")
    m.date_final = next(iter(rows("date_final")), "")
    return m


async def _open_matter(page: Page, number: str) -> None:
    await page.goto(URL)
    placeholder = page.get_by_text("eg M01234")
    await placeholder.wait_for(timeout=60_000)
    box = await page.locator("div.fm-textarea", has=placeholder).bounding_box()
    # WebDirect fields only become editable after a real pointer click on them.
    await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    await page.wait_for_timeout(500)
    await page.keyboard.type(number, delay=30)
    await page.keyboard.press("Enter")

    tab = page.get_by_role("button", name=re.compile(r"^Exhibits - \d+$"))
    not_found = page.get_by_text("No Records Found")
    await tab.or_(not_found).first.wait_for(timeout=60_000)
    if await not_found.count():
        raise MatterNotFound(number)


async def _read_counts(page: Page) -> dict[str, int]:
    counts = {}
    for label in await page.get_by_role("button").all_inner_texts():
        if m := TAB_RE.match(label.strip()):
            counts[m.group(1)] = int(m.group(2))
    return counts


async def _download(page: Page, doc_type: str, dest: Path, limit: int) -> tuple[list[Path], int]:
    await page.get_by_role("button", name=re.compile(rf"^{doc_type} - \d+$")).click()
    go = page.get_by_role("button", name="GO GET IT")
    await go.first.wait_for(timeout=30_000)
    await page.wait_for_timeout(1500)

    files: list[Path] = []
    failed = 0
    i = 0
    while len(files) + failed < limit:
        if i >= await go.count():
            break
        try:
            await go.nth(i).scroll_into_view_if_needed()
            await go.nth(i).click()
            button = page.locator(".fm-download-button")
            await button.wait_for(timeout=30_000)
            async with page.expect_download(timeout=60_000) as info:
                await button.click()
            download = await info.value
            name = download.suggested_filename or (await button.inner_text()).strip()
            path = dest / name
            if path.exists():  # two documents can share a filename
                path = dest / f"{path.stem}-{i + 1}{path.suffix}"
            await download.save_as(path)
            files.append(path)
            log.info("downloaded %s", path.name)
        except Exception as exc:  # one bad file mustn't stop the batch
            failed += 1
            log.warning("download %d of %s failed: %s", i + 1, doc_type, exc)
        finally:
            close = page.get_by_role("button", name="Close", exact=True)
            if await close.count():
                await close.first.click()
                await page.wait_for_timeout(500)
        i += 1
    return files, failed


async def fetch(number: str, doc_type: str, dest: Path, limit: int = 10) -> FetchResult:
    """Open a matter, read its metadata and tab counts, and download up to `limit` files."""
    dest.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1400, "height": 2400}, accept_downloads=True)
            await _open_matter(page, number)
            await page.wait_for_timeout(1000)
            counts = await _read_counts(page)
            tab_top = (await page.get_by_role("button", name=re.compile(r"^Exhibits - ")).bounding_box())["y"]
            matter = _parse_header(await page.evaluate(_HEADER_JS, tab_top), number)
            matter.counts = counts

            files, failed = [], 0
            if counts.get(doc_type, 0) > 0:
                try:
                    files, failed = await _download(page, doc_type, dest, limit)
                except PWTimeout as exc:
                    log.warning("couldn't open %s tab: %s", doc_type, exc)
            return FetchResult(matter=matter, doc_type=doc_type, files=files, failed=failed)
        finally:
            await browser.close()
