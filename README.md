# portal-runner

A single-process Playwright CLI for a portal that asks for a second factor. This is a take-home build.
The target portal is Zoho Invoice (India data centre).

## Honest status

Verified by tests (`scripts\test.ps1`, 16 tests):
- resolver, retries and backoff, session store, evidence redaction, manifest, TOTP and relay code providers
- the resolver on a saved copy of the real Zoho new-invoice page, under 6 HTML mutations (offline)

NOT done: a live end-to-end run of this runner against the portal. Sign-in reaches the "Enter time-based OTP" step, but no run has
passed it, so there is no live success output and no real failure bundle yet. `outputs/offline_resolve_example.json` is offline
resolver output only, not a portal run. The Zoho form workflow was mapped by hand in a browser, not by this runner.
The adapter code past the code step is untested live.

## Setup (one command, Windows PowerShell)

    .\scripts\setup.ps1

Copy `.env.example` to `.env` and fill it in. Then:

    .\scripts\run.ps1                       # relay code source: runner asks for the code
    .\scripts\run.ps1 -CodeSource totp      # needs PORTAL_TOTP_SECRET in .env
    .\scripts\run.ps1 -FailAt login         # forces a failure and writes an evidence bundle

Also set `ZOHO_ORG_ID` in `.env`.

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
Zoho pages show the account phone and email. Nothing from a live Zoho page is committed unredacted.
