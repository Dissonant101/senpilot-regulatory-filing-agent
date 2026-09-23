# Regulatory Filing Agent

Email the agent a UARB matter number and a document type, and it replies in the same
thread with up to 10 of those filings as a ZIP and a short summary of the matter.

> **To:** the agent's inbox
> **Body:** Other Documents files from M12205

> M12205 is about Halifax Regional Water Commission - Windsor Street Exchange Redevelopment
> Project. It relates to $69,275,000 and is a Water matter in the Capital Expenditure
> Approvals category. The matter had an initial filing on April 7, 2025 and a final filing
> on October 23, 2025.
>
> I found 13 Exhibits, 6 Key Documents, and 43 Other Documents, but no Transcripts or
> Recordings.
>
> I downloaded 10 out of 43 Other Documents and attached them as a ZIP.

Supported types: **Exhibits, Key Documents, Other Documents, Transcripts, Recordings**
(singular, plural and short forms like "key docs" or "exhibit" all work). Emails with no
matter number, more than one matter number, an unclear type, or a matter that doesn't
exist get an error reply explaining what to fix.

## How it works

1. **Poll** (`gmail.py`) — every `POLL_SECONDS`, list `in:inbox is:unread -from:me`. A
   message is only marked read after its reply is sent, so mail that arrives while the
   agent is down or restarting is handled on the next poll. Bounces and auto-replies are
   skipped so the agent can't loop with another bot. A request that keeps failing (e.g.
   the UARB site is down) is retried on the next two polls, then answered with an apology.
2. **Parse** (`parser.py`) — regex `\bM\d{5}\b` (any case) for the matter, keyword
   patterns for the type. Quoted reply history (`>` lines) is ignored.
3. **Scrape** (`uarb.py`) — Playwright drives the [UARB WebDirect site][uarb]: types the
   number into "Go Directly to Matter", reads the tab counts from the tab labels
   (`Exhibits - 13`) and the metadata by column under the header labels, then opens the
   requested tab and clicks **GO GET IT** → the file button for up to 10 rows. A failed
   download is logged and skipped. Filenames are kept as the site names them.
4. **Reply** (`reply.py`) — fills a fixed template, zips the files, and replies in the
   original thread (`threadId` + `In-Reply-To`/`References`).

[uarb]: https://uarb.novascotia.ca/fmi/webd/UARB15

## Why rules instead of an LLM

The input is narrow: one ID with a fixed format and one of five known labels. A regex and a
keyword table parse that exactly, are free to run, answer in milliseconds, behave the same
every time, and are covered by unit tests. The output is also narrow — a handful of facts
in a fixed shape — so a template gives correct grammar ("1 Exhibit", "no Transcripts or
Recordings") with no risk of an invented amount or date. An LLM would add cost, latency, a
paid dependency and a failure mode (hallucinated metadata) without handling any request
the rules can't. If free-form requests become common, an LLM could be added as a fallback
parser only when the rules find no type.

## Setup

### 1. Gmail API credentials

1. In Google Cloud Console, create a project and enable the **Gmail API**.
2. Configure the OAuth consent screen (External, add the agent's Gmail address as a test
   user — or publish it so the refresh token doesn't expire after 7 days).
3. Create an **OAuth client ID** of type *Desktop app*; note the client ID and secret.
4. Get a refresh token by signing in as the agent's inbox:

   ```bash
   GMAIL_CLIENT_ID=... GMAIL_CLIENT_SECRET=... uv run uarb-agent-auth
   ```

### 2. Environment variables

| Variable              | Required | Description                                   |
| --------------------- | -------- | --------------------------------------------- |
| `GMAIL_CLIENT_ID`     | yes      | OAuth client ID                               |
| `GMAIL_CLIENT_SECRET` | yes      | OAuth client secret                           |
| `GMAIL_REFRESH_TOKEN` | yes      | From `uarb-agent-auth`                        |
| `POLL_SECONDS`        | no       | Inbox poll interval, default `30`             |
| `LOG_LEVEL`           | no       | Default `INFO`                                |

Copy `.env.example` to `.env` for local runs. Never commit credentials.

### 3. Run locally

```bash
uv sync
uv run playwright install chromium
uv run --env-file .env uarb-agent
```

### 4. Deploy (Railway or Render)

The `Dockerfile` builds on Microsoft's Playwright image, so Chromium and its system
libraries are already present. Create a service from this repo (Railway: *Deploy from
GitHub repo*; Render: *Background Worker*, Docker runtime), set the three `GMAIL_*`
variables, and deploy. It needs no port or disk — it only makes outbound requests.

## Tests

```bash
uv run pytest
```

Unit tests cover the parser (the assignment's example plus other wordings and every
rejection case), header parsing against saved snapshots of M12205 and M12383, the count and
download wording, and the ZIP. The scraper itself is exercised against the live site.
