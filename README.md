# portal-runner

A single-process Playwright CLI for a portal that asks for a second factor. This is a take-home build.
The target portal is Zoho Invoice (India data centre).

## Honest status

Verified by tests (`scripts\test.ps1`, 48 tests on Linux; on Windows 1 test skips when tesseract is missing):
- resolver, retries and backoff, session store, evidence redaction, manifest, TOTP and relay code providers
- the resolver on saved copies of the real Zoho invoice list, new-invoice form and invoice detail pages (captured from a signed-in browser, personal details removed); the form is also tested under 6 HTML mutations (offline)

Observed live (author's Windows machine, Oct 18 00:06 IST): one end-to-end run with a REUSED saved session. It filled the form (Net 30 moved the due date from 15/10/2026 to 14/11/2026),
saved a draft invoice, and captured the PDF. The manifest for that run says `login_mode: session_reused`.

NOT yet observed live with this code: a fresh TOTP login run, recovery from a corrupt saved session, a run with changed inputs, and a deliberately failed run's evidence bundle.
`outputs/offline_resolve_example.json` is offline resolver output only, not a portal run.

**What "pages deep" means here.** Zoho Invoice is a single page app, so its pages are hash routes, not full page loads. A run visits `#/home`, `#/invoices` (the list),
`#/invoices/new` (the form) and `#/invoices/<id>` (the saved draft, where the PDF menu is). The list is reached by clicking Invoices (with a direct-address fallback when the sidebar
swallows the click), and the form is opened by going to its address directly, not by clicking "New". The manifest's `pages_visited` records these routes with ids masked.
Whether that counts as "three pages deep" is the reviewer's definition.

## Running it yourself

You need your own portal account, your own login in `.env`, and a TOTP secret you control (`PORTAL_TOTP_SECRET`).
It accepts a plain base32 key (spaces and lowercase are fine) or a full `otpauth://` URI.
Follow the portal's own setup screen to get the key. This repo ships no credentials.

## One command (setup, checks, tests, run)

First get the code and open a terminal in its folder (needs Git and Python 3.9+):

    git clone https://github.com/laxayk/portal-runner
    cd portal-runner

Without Git, use the repo page's Code > Download ZIP, extract it and open PowerShell in that folder.

Windows PowerShell:

    powershell -ExecutionPolicy Bypass -File .\scripts\go.ps1

Linux or macOS:

    ./scripts/go.sh

The first run installs everything and creates `.env`, then stops and tells you which names to fill in (it never prints values).
Run it again after filling `.env`. It then runs the tests and the portal. Options: `-SkipTests` / `--skip-tests`, `-FailAt login` / `--fail-at login`
(forces a failure to produce an evidence bundle), `-CodeSource` / `--code-source`.
Fill `.env` with your portal email, password, TOTP secret and `ZOHO_ORG_ID`: sign in to Zoho Invoice and copy the number after `/app/` in the address bar.
`go.sh` was run on Linux against a fresh clone; `go.ps1` has been run on Windows (see Honest status above).

Local outputs (`outputs/failure-*/`, PDFs, `manifest.json`) are git-ignored.
Failure bundles redact text files. Before the screenshot, the runner also blanks inputs, hides images, and replaces on-page text that matches your login values,
emails, phone-like numbers, 6-8 digit codes and anything listed in `PORTAL_REDACT` in `.env` (put your name, company name and phone there).
Tested: an OCR check on a screenshot with canary text. Not covered: names or details that are neither in `PORTAL_REDACT` nor match those patterns, and the downloaded
PDF, which is never redacted. Treat bundles and PDFs as private and look at a screenshot before sharing it.

## Answers

**Note:** the assignment asks for a code obtained without a human typing it. `RelayProvider` is a convenience for local testing and does not meet that. `TotpProvider` is the compliant provider.

**How the code arrives, and what a wrong code does.** `async def get_code(challenge)` has two providers. `TotpProvider` computes a code from a seed
you supply. `RelayProvider` reads a code you drop into `.state/code.txt` (deleted after reading) or types at a prompt. A wrong code is
retried once with a fresh `get_code` call. A second failure is final and writes an evidence bundle. The code is wrapped so it never reaches logs.

**Dead-session detection.** A login redirect is not enough. The session counts as alive only if the app navigation renders, the host is the app host, and there is no
"session expired" text. If not, the runner discards the state and logs in again by itself.

**Locator order and why.** Role+name, then label, nearby text, structure (data attributes), then id/class. Accessible names are the most stable
across redesigns. Ids and classes change most, so they come last. The winning strategy is logged. On the real Zoho HTML with renamed ids and broken
label links, the structure and nearby-text fallbacks win. A resolve is not one snapshot: portals serve controls hidden and reveal them once their
scripts run (Zoho's sign-in does this), so the resolver retries the pass until a strategy wins or a 15s budget runs out. Only a target that stays
unresolvable for the whole budget is reported missing.

**Quirks handled.** Six separate OTP digit boxes with no ids; custom dropdowns instead of selects; a due date that depends on the payment terms (checked against the terms);
a PDF produced by a menu action, captured by download and checked for the `%PDF` header.

**What retries.** Timeouts, locator misses and navigation errors retry with bounded exponential backoff. A wrong code retries once. Bad input JSON and a
failed second factor do not retry.

**Failure bundle.** Final failures write a redacted bundle (page text, screenshot-free by default, stage, timings). Redaction is tested with canary secrets.

**For 100 portals, change first.** Move the per-portal Targets and the login steps into data files with a shared adapter, and add a recorded-HTML regression suite per portal, so
a site change shows up in tests before a run fails.

## Data note
Zoho pages show the account phone and email. Saved pages in this repo have contact details and ids removed.
