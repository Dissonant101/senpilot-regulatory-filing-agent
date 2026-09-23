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
exist get an error reply explaining what to fix. Matching ignores case.

## How it works

1. **Poll** (`gmail.py`) — every `POLL_SECONDS`, list unread mail in the inbox and spam
   that the agent didn't send. Gmail's read flag is the queue: a message is only marked
   read after its reply is sent, so mail that arrives while the agent is down or
   restarting is handled on the next poll. Bounces and auto-replies are skipped so the
   agent can't loop with another bot. A request that keeps failing (e.g. the UARB site is
   down) is retried on the next two polls, then answered with an apology.
   - **Spam:** Gmail often files a new sender's first email as spam. Spam that parses as
     a real request is answered and moved to the inbox; anything else there is marked
     read with no reply, so spammers don't learn the address is live.
   - **Read/unread:** opening an email in the agent's inbox before it's answered marks it
     read, and the agent skips it — mark it unread to have it answered. Marking an
     answered email unread makes the agent answer it again.
2. **Parse** (`parser.py`) — regex `\bM\d{5}\b` (any case) for the matter, keyword
   patterns for the type. Quoted reply history (`>` lines) is ignored.
3. **Scrape** (`uarb.py`) — Playwright drives the [UARB WebDirect site][uarb]: types the
   number into "Go Directly to Matter", reads the tab counts from the tab labels
   (`Exhibits - 13`) and the metadata by column under the header labels, then opens the
   requested tab and clicks **GO GET IT** → the file button for up to 10 rows. A failed
   download is logged and skipped. Filenames are kept as the site names them.
4. **Reply** (`reply.py`) — fills a fixed template, zips the files, and replies in the
   original thread (`threadId` + `In-Reply-To`/`References`, and the original subject —
   Gmail only threads replies whose subject matches). Gmail rejects messages over 25 MB
   and base64 inflates attachments by a third, so the ZIP is capped at 18 MB: the largest
   files are dropped until it fits, and the reply names the files left out.

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
2. Use a **dedicated Gmail account** for the agent's inbox. The agent answers every
   unread email in it, so never point it at a personal inbox.
3. Configure **Google Auth Platform** (the OAuth consent screen): *Get started* → app
   name and support email → audience **External** → contact email. Then either:
   - **Testing:** add the agent's address under *Audience → Test users*. Other accounts
     are blocked, and the refresh token expires after **7 days** — rerun step 5 and
     update `GMAIL_REFRESH_TOKEN` weekly.
   - **Published:** complete the *Branding* page, then *Audience → Publish app*. Sign-in
     shows an "unverified app" warning (*Advanced → Go to …*), but the token doesn't
     expire on a timer.
4. Create an **OAuth client** (*Clients → Create client*) of type *Desktop app*; note the
   client ID and secret.
5. Get a refresh token by signing in as the agent's inbox:

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

### 4. Deploy (GCP Always Free e2-micro)

The `Dockerfile` builds on Microsoft's Playwright image, so Chromium and its system
libraries are already present. The agent needs no port or domain — it only makes outbound
requests — so any always-on Docker host works. It runs on Google Cloud's Always Free
e2-micro VM:

1. Link a billing account (required even for the free tier) and create a **$1 budget
   alert** under *Billing → Budgets & alerts*.
2. *Compute Engine → Create instance*, keeping to the free-tier shape:

   | Setting | Value |
   | --- | --- |
   | Region | `us-central1`, `us-east1` or `us-west1` |
   | Machine type | `e2-micro` |
   | Advanced → Provisioning model | **Standard** (Spot isn't free) |
   | Advanced → On host maintenance | **Migrate** (*Terminate* forces Spot on E2) |
   | OS and storage | Ubuntu 24.04 LTS x86/64, **Standard persistent disk**, 30 GB |
   | Data protection | **No backups** (snapshots aren't free) |
   | Networking | HTTP/HTTPS firewall rules off |

   The console's estimate shows the e2-micro list price (~$6/month); the free-tier credit
   is applied on the bill. Check *Billing → Reports* grouped by SKU after a day.
3. Open **SSH** from the console. On first boot, wait for Ubuntu's automatic updates to
   release the apt lock, then install Docker and add swap (1 GB RAM is tight for Chromium):

   ```bash
   while sudo fuser /var/lib/apt/lists/lock /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do sleep 5; done
   curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER
   sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile && echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   ```

   Reopen the SSH window so the Docker group applies.
4. On your machine, `git archive -o uarb-agent.tar.gz HEAD`, then upload it with the SSH
   window's **Upload file** button. On the VM:

   ```bash
   mkdir -p ~/agent && tar -xzf ~/uarb-agent.tar.gz -C ~/agent && cd ~/agent
   nano .env && chmod 600 .env   # paste the three GMAIL_* lines
   docker build -t uarb-agent . && docker run -d --name uarb-agent --restart unless-stopped --env-file .env uarb-agent
   docker logs -f uarb-agent     # wait for "watching <address> ..."
   ```

5. **Redeploy** after a change: upload a fresh archive, then

   ```bash
   tar -xzf ~/uarb-agent.tar.gz -C ~/agent && cd ~/agent && docker build -t uarb-agent . && docker rm -f uarb-agent && docker run -d --name uarb-agent --restart unless-stopped --env-file .env uarb-agent
   ```

Run only one copy of the agent per inbox, or two will race to answer the same email.

**Other hosts considered:** Railway Hobby ($5/month, includes $5 usage) works from the
same Dockerfile with *Deploy from GitHub repo*. Render's free tier excludes background
workers and spins web services down after 15 idle minutes; AWS's free plan is now
six months of credits rather than an always-free VM.

## Tests

```bash
uv run pytest
```

Unit tests cover the parser (the assignment's example plus other wordings and every
rejection case), header parsing against saved snapshots of M12205 and M12383, the count and
download wording, ZIP size capping, reply threading, and spam handling. The scraper itself
is exercised against the live site: M12205 and M12383 across Other Documents, Exhibits,
Key Documents and Transcripts, plus an unknown matter.

## Troubleshooting

- **No reply:** check the agent inbox — if the request was opened (read) before the agent
  saw it, mark it unread. `docker logs --tail 30 uarb-agent` shows each request.
- **`poll failed` with an auth error:** the refresh token expired (7 days in Testing
  mode). Rerun `uarb-agent-auth` and update `.env`.
- **"Access blocked: … has not completed the Google verification process":** the account
  isn't a test user. Add it under *Audience → Test users*, or publish the app.
