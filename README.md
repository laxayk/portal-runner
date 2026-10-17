# portal-runner

A command-line Playwright bot that signs in to Zoho Invoice (India data centre, my own test account) through an authenticator-app second factor, creates a draft invoice from a JSON file, and saves the invoice PDF.

One site covers everything the brief asks for, so there is no second site.

## What it does

1. Logs in with email, password and a TOTP code it computes itself from my authenticator secret. No one types the code.
2. Saves the browser session to `.state/session.json`. The next run loads it. If the session is dead, it signs in again by itself.
3. Opens Home, then Invoices, then clicks New and fills the invoice form: customer, invoice date, payment terms, item and quantity. The due date depends on the terms. The bot checks that it moved as expected.
4. Saves the invoice as a draft (it never sends one) and downloads the PDF from the invoice's menu.
5. Writes `outputs/manifest-<time>.json` with the inputs, pages visited, stage timings and captured files.

Zoho Invoice is a single page app: its screens are hash routes (`#/home`, `#/invoices`, `#/invoices/new`, `#/invoices/<id>`), not full page loads. The manifest lists the routes visited and how each was reached (`navigation`).

## Setup and run

Needs Git and Python 3.9+.

    git clone https://github.com/laxayk/portal-runner
    cd portal-runner

Windows PowerShell:

    powershell -ExecutionPolicy Bypass -File .\scripts\go.ps1

Linux or macOS:

    ./scripts/go.sh

The first run installs everything and creates `.env`, then stops and tells you which names to fill in (it never prints values). Run it again after filling `.env`. It runs the tests, then the bot.

Options: `-SkipTests` / `--skip-tests`, `-FailAt <stage>` / `--fail-at <stage>` (forces a failure to produce an evidence bundle), `-Inputs <file>` (Windows script, another input JSON), `-DeadSession` (Windows script, breaks the saved session first, for the stale-session check), `-CodeSource` / `--code-source totp|relay`.

### Environment variables (`.env`, copied from `.env.example`, git-ignored)

| Name | Needed | What it is |
|---|---|---|
| `PORTAL_EMAIL` | yes | Zoho login email |
| `PORTAL_PASSWORD` | yes | Zoho password |
| `PORTAL_TOTP_SECRET` | yes with `totp` (the default) | the authenticator setup key (base32 or an `otpauth://` URI) |
| `ZOHO_ORG_ID` | yes | the number after `/app/` in the address bar once signed in |
| `PW_CHANNEL` | no | `chrome` to use installed Chrome instead of Playwright's Chromium |
| `PORTAL_REDACT` | no | extra words to hide in failure evidence, comma separated (name, company, phone) |

### Inputs

`inputs/invoice.json`:

    {"customer": "Acme Test Traders", "invoice_date": "15/10/2026", "terms": "Net 30", "item": "Consulting hour", "quantity": 3}

Change a value, or pass another file with `--inputs`, and no code changes. `inputs/invoice_changed.json` is a second example.

### Manifest

`inputs`, `login_mode` (`full_login` or `session_reused`), `pages_visited`, `navigation`, `stage_timings`, `total_seconds`, `captured_files` (name, size, sha256), `resolver_wins`, `status`, and on failure `failed_stage` and `failure_bundle`.

## Evaluation runs

Run from the repo folder in Windows PowerShell, in this order, with `.env` filled in. Each live run creates one more draft invoice in the test account, except the failure run. Manifests, PDFs and failure bundles are timestamped, so nothing is overwritten.

| Check | Command | Expected |
|---|---|---|
| No saved state | `Remove-Item .state\session.json -ErrorAction SilentlyContinue; .\scripts\go.ps1 -SkipTests` | `login_mode: full_login`, a `login` stage, `status: success`, one PDF in `outputs\` |
| Run again | `.\scripts\go.ps1 -SkipTests` | `login_mode: session_reused`, no `login` stage, shorter total time, same document |
| Corrupt saved state | `.\scripts\go.ps1 -SkipTests -DeadSession` | the saved session is backed up and its cookie values overwritten; the run detects it, logs in fully and succeeds; the console prints `login_mode=full_login` |
| Changed input | `.\scripts\go.ps1 -SkipTests -Inputs inputs\invoice_changed.json` | a different PDF (date 16/10/2026, Due on Receipt, quantity 5, total 12,500), no code edit |
| Mutated HTML, offline | `.\.venv\Scripts\python.exe -m portal_runner resolve-offline --html tests\fixtures\zoho_invoice_form.html --mutate` | 7 variants (baseline, renamed classes and ids, broken label links, reordered siblings, added wrapper div, inside an iframe, all combined); every target names a winning strategy, none says `FAILED` |
| Broken step | `.\scripts\go.ps1 -SkipTests -FailAt perform` | 3 attempts with backoff, then `Expected failure at stage perform` and `outputs\failure-perform-<time>.zip` holding the URL, stage key, console log, resolver attempts, page HTML and screenshot, redacted; no new draft |

On Linux or macOS: `./scripts/go.sh --skip-tests` (delete `.state/session.json` first for the no-state run), `./scripts/go.sh --skip-tests --fail-at perform`, `python -m portal_runner run --inputs inputs/invoice_changed.json`, and `.venv/bin/python -m portal_runner resolve-offline ...`.

Tests: `.\.venv\Scripts\python.exe -m pytest -q` (`go.ps1` runs them without `-SkipTests`). On Windows one OCR test skips when tesseract is not installed.

## Answers

**How the code arrives and what a wrong code does.** `async def get_code(challenge)` has two providers. `TotpProvider` computes the code from the secret in `.env`. This is the one real implementation. `RelayProvider` reads a code dropped into `.state/code.txt` or typed at a prompt; it is for local testing only and does not meet "no human typing". A wrong code is retried once with a fresh `get_code` call. A second failure is final and writes an evidence bundle. The code is wrapped so it never reaches logs.

**How a dead session is detected.** A redirect to the login page is not the only test. After loading the saved state, the bot opens the app home. The session counts as alive only if the host is the app host, the app's own navigation renders, there is no "session expired" text, and the resolver finds the Invoices link. Otherwise the saved state is discarded and the bot does a full login.

**Locator order and why.** Role and name, then label, nearby text, structure (data attributes), then id or class. Accessible names are the most stable across redesigns; ids and classes change most, so they come last. The winning strategy is logged and written to the manifest as `resolver_wins`. The resolver retries its pass until a strategy wins or a 15 s budget runs out, because the portal reveals controls after its scripts run. It runs offline against saved HTML (`resolve-offline`).

**Quirks handled.** A due date that depends on the payment terms (checked against the terms); custom dropdowns instead of selects; six separate OTP digit boxes with no ids; a PDF produced by a menu action, captured as a download and checked for the `%PDF` header; a preferences dialog and a sidebar that can cover clicks.

**What retries.** Timeouts, locator misses and navigation errors retry with bounded exponential backoff. A wrong code retries once. Bad input JSON and a failed second factor do not retry.

**Failure bundle.** A final failure writes a folder with `url.txt`, `stage.txt`, `error.txt`, `console.log`, `page.html`, `resolver_attempts.json`, `extra.json` (the attempts) and `screenshot.png`. Text files are redacted. Before the screenshot, inputs are blanked and on-page text matching login values, emails, phone-like numbers, codes, `PORTAL_REDACT` words and the organisation and portal names found in the page is replaced. Treat bundles and downloaded PDFs as private: the PDF is never redacted and prints the account's contact details.

**What I would change first for a hundred portals.** Move the per-portal targets and login steps into data files with a shared adapter, and add a recorded-HTML regression suite per portal, so a site change shows up in tests before a run fails.

## Data note

`outputs/`, `.state/` and `.env` are git-ignored. The saved pages in `tests/fixtures` have contact details and ids removed.
