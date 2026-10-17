# portal-runner

A single-process Playwright CLI for a portal that asks for a second factor. This is a take-home build.
The target portal is Zoho Invoice (India data centre).

## Honest status

Verified by tests (`scripts\test.ps1`; 54 tests pass on Linux, on Windows 1 test skips when tesseract is missing):
- resolver, retries and backoff, session store, evidence redaction, manifest, TOTP and relay code providers, the New-button route with its address fallback, the `kill-session` and `last-run` helpers
- the resolver on saved copies of the real Zoho invoice list, new-invoice form and invoice detail pages (captured from a signed-in browser, personal details removed); the form is also tested under 6 HTML mutations (offline)
- on the author's saved dashboard page from a failure bundle (private, not in this repo), the nav link resolved in all 7 offline variants (baseline plus 6 mutations). Only that one target exists on that page.

Observed live (author's Windows machine, Zoho Invoice test account, Oct 18 around 00:06 to 00:32 IST). Each is one run, not a benchmark:
- saved session reused: login_mode `session_reused`, Net 30 moved the due date from 15/10/2026 to 14/11/2026, draft saved, PDF captured
- fresh login with the automatic TOTP code after deleting the saved session: login_mode `full_login`, login stage about 13 s, PDF captured
- dead saved session (`-DeadSession`: the file still parses but the cookie values are replaced): the session check was sent to the login page, then a full login ran and the run succeeded. The manifest shows the stage order; it has no field giving the reason.
- changed inputs (`inputs/invoice_changed.json`: other date, Due on Receipt, quantity 5): the PDF showed the new date, terms, due date and a total of 12,500, with no code edit
- the New button clicked from the invoice list (manifest `navigation`), in the runs after that change
- a deliberate failure (`-FailAt perform`): 3 attempts with backoff, then an evidence bundle (URL, stage, console log, resolver attempts, HTML, screenshot). That first bundle showed the organisation name unredacted in the HTML and on screen. The runner now learns the organisation and portal names from the page and redacts them. A second run after the fix produced a bundle whose text files and screenshot were checked for the account's email, phone, name and ids: none were found, and the name on screen read [REDACTED]. That check covers known values on one dashboard page, not every possible personal detail.

Not observed live: recovery from an unparseable state file (unit-tested only); a failure at a step other than the forced one.
The Zoho invoice status in the app was not looked up for each run; draft status rests on the app's own redirect to the new invoice and the "Draft" ribbon the runner waits for.
`outputs/offline_resolve_example.json` is offline resolver output only, not a portal run.

**What "pages deep" means here.** Zoho Invoice is a single page app, so its pages are hash routes, not full page loads. A run visits `#/home`, `#/invoices` (the list),
`#/invoices/new` (the form) and `#/invoices/<id>` (the saved draft, where the PDF menu is). The list is reached by clicking Invoices (with a direct-address fallback when the sidebar
swallows the click), and the form is opened by clicking "New" on the list, falling back to its address if the click does not reach the form. The manifest's `navigation` field says which way each page was reached, and `pages_visited` records the routes with ids masked.
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
(forces a failure at that stage and, for the demo, zips the bundle; it only counts as expected if the forced failure at the requested stage produced the bundle), `-Inputs <file>` (use another input JSON, for example `inputs\invoice_changed.json`), `-DeadSession` (Windows script only: keeps a backup of the saved session, overwrites its cookie values so the file still parses but the portal rejects it, runs, then prints the login mode of the run; evaluation only, ordinary runs are unchanged), `-CodeSource` / `--code-source`.
Fill `.env` with your portal email, password, TOTP secret and `ZOHO_ORG_ID`: sign in to Zoho Invoice and copy the number after `/app/` in the address bar.
`go.sh` was run on Linux against a fresh clone; `go.ps1` has been run on Windows (see Honest status above).

Local outputs (`outputs/failure-*/`, failure zips, PDFs, manifests) are git-ignored.
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

**Failure bundle.** Final failures write a redacted bundle: URL, stage key, console log, resolver attempts, page HTML and a screenshot. Text files are redacted; inputs are masked and on-page text matching known values and patterns is replaced before the screenshot. Redaction is tested with canary secrets. A live bundle exposed an organisation name that no pattern covered, which is why names found in the page's own data are now added automatically. Treat bundles as private.

**For 100 portals, change first.** Move the per-portal Targets and the login steps into data files with a shared adapter, and add a recorded-HTML regression suite per portal, so
a site change shows up in tests before a run fails.

## Data note
Zoho pages show the account phone and email. Saved pages in this repo have contact details and ids removed.
