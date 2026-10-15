# portal-runner

A single-process Playwright CLI for a portal that asks for a second factor. This is a take-home build.
The target portal is Zoho Invoice (India data centre).

## Honest status

Verified by tests (`scripts\test.ps1`, 18 tests):
- resolver, retries and backoff, session store, evidence redaction, manifest, TOTP and relay code providers
- the resolver on saved copies of the real Zoho invoice list, new-invoice form and invoice detail pages (captured from a signed-in browser, personal details removed); the form is also tested under 6 HTML mutations (offline)

NOT done: a live end-to-end run of this runner against the portal. Sign-in reaches the "Enter time-based OTP" step, but no run has
passed it, so there is no live success output and no real failure bundle yet. `outputs/offline_resolve_example.json` is offline
resolver output only, not a portal run. The Zoho form workflow was mapped by hand in a browser, not by this runner.
The adapter code past the code step is untested live.

## Running it yourself

You need your own portal account, your own login in `.env`, and a TOTP secret you control (`PORTAL_TOTP_SECRET`).
It accepts a plain base32 key (spaces and lowercase are fine) or a full `otpauth://` URI.
Follow the portal's own setup screen to get the key. This repo ships no credentials.

## One command (setup, checks, tests, run)

Windows PowerShell:

    powershell -ExecutionPolicy Bypass -File .\scripts\go.ps1

Linux or macOS:

    ./scripts/go.sh

The first run installs everything and creates `.env`, then stops and tells you which names to fill in (it never prints values).
Run it again after filling `.env`. It then runs the tests and the portal. Options: `-SkipTests` / `--skip-tests`, `-FailAt login` / `--fail-at login`
(forces a failure to produce an evidence bundle), `-CodeSource` / `--code-source`.
Fill `.env` with your portal email, password, TOTP secret and `ZOHO_ORG_ID`: sign in to Zoho Invoice and copy the number after `/app/` in the address bar.
`go.sh` was run on Linux against a fresh clone; `go.ps1` has not been run on Windows yet.

Local outputs (`outputs/failure-*/`, PDFs, `manifest.json`) are git-ignored. Failure bundles redact text files, but the screenshot is a raw picture of the page and can show
account details, so keep bundles private and do not share the screenshot.

## Answers

**Note:** the assignment asks for a code obtained without a human typing it. `RelayProvider` is a convenience for local testing and does not meet that. `TotpProvider` is the compliant provider.

**How the code arrives, and what a wrong code does.** `async def get_code(challenge)` has two providers. `TotpProvider` computes a code from a seed
you supply. `RelayProvider` reads a code you drop into `.state/code.txt` (deleted after reading) or types at a prompt. A wrong code is
retried once with a fresh `get_code` call. A second failure is final and writes an evidence bundle. The code is wrapped so it never reaches logs.

**Dead-session detection.** A login redirect is not enough. The session counts as alive only if the app navigation renders, the host is the app host, and there is no
"session expired" text. If not, the runner discards the state and logs in again by itself.

**Locator order and why.** Role+name, then label, nearby text, structure (data attributes), then id/class. Accessible names are the most stable
across redesigns. Ids and classes change most, so they come last. The winning strategy is logged. On the real Zoho HTML with renamed ids and broken
label links, the structure and nearby-text fallbacks win.

**Quirks handled.** Six separate OTP digit boxes with no ids; custom dropdowns instead of selects; a due date that depends on the payment terms (checked against the terms);
a PDF produced by a menu action, captured by download and checked for the `%PDF` header.

**What retries.** Timeouts, locator misses and navigation errors retry with bounded exponential backoff. A wrong code retries once. Bad input JSON and a
failed second factor do not retry.

**Failure bundle.** Final failures write a redacted bundle (page text, screenshot-free by default, stage, timings). Redaction is tested with canary secrets.

**For 100 portals, change first.** Move the per-portal Targets and the login steps into data files with a shared adapter, and add a recorded-HTML regression suite per portal, so
a site change shows up in tests before a run fails.

## Data note
Zoho pages show the account phone and email. Saved pages in this repo have contact details and ids removed.
