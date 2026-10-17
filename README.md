# portal-runner

A command-line Playwright bot for Zoho Invoice (India, my own test account). It logs in with an authenticator-app code it computes itself, creates a draft invoice from a JSON file, and saves the invoice PDF. One site covers everything the brief asks for.

Flow: log in (TOTP) -> save the session to `.state/session.json` -> next run reuses it, or logs in again if it is dead -> Home -> Invoices -> New -> fill the form (customer, date, terms, item, quantity; the due date depends on the terms) -> save as draft -> download the PDF -> write `outputs/manifest.json` plus a timestamped copy (inputs, pages visited, stage timings, captured files). It never sends an invoice.

Zoho Invoice is a single page app, so its pages are hash routes (`#/home`, `#/invoices`, `#/invoices/new`, `#/invoices/<id>`).

## Run it

Needs Git and Python 3.9+.

    git clone https://github.com/laxayk/portal-runner
    cd portal-runner
    powershell -ExecutionPolicy Bypass -File .\scripts\go.ps1      (Windows)
    ./scripts/go.sh                                                 (Linux, macOS)

The first run installs everything and creates `.env`, then stops. Fill in `.env` and run it again. It runs the tests, then the bot (`-SkipTests` / `--skip-tests` skips the tests).

| `.env` name | Needed | What it is |
|---|---|---|
| `PORTAL_EMAIL`, `PORTAL_PASSWORD` | yes | Zoho login |
| `PORTAL_TOTP_SECRET` | yes | authenticator setup key (base32 or `otpauth://`) |
| `ZOHO_ORG_ID` | yes | the number after `/app/` in the address bar |
| `PW_CHANNEL` | no | `chrome` to use installed Chrome |
| `PORTAL_REDACT` | no | extra words to hide in failure evidence (name, phone) |

### Getting `PORTAL_TOTP_SECRET`

The secret is the setup key Zoho shows when you enrol an authenticator app. It is not the 6-digit code that changes every 30 seconds.

1. Sign in at `accounts.zoho.in` (use `accounts.zoho.com` for other data centres), open **Multi-Factor Authentication** and click **Set up Now** under **OTP Authenticator**.
2. Zoho shows a QR code and a setup key. Copy the key (use "enter the key manually" if the page offers it). Paste it into `.env` as `PORTAL_TOTP_SECRET=...`. A base32 key (spaces and lowercase are fine) or a full `otpauth://totp/...` link both work; the bot assumes 6 digits and 30 seconds unless the link says otherwise.
3. Add the same key to your phone's authenticator app too (type it in or scan the QR), enter the code it shows and click **Verify**. Zoho only confirms setup after that.
4. Save the backup codes Zoho offers.

If the account already has an authenticator and you do not have its setup key, do not reset your existing MFA just for this. Use a dedicated test account, or a new enrolment, where you keep the key, within Zoho's and your organisation's policy (an admin can restrict MFA setup). Keep `.env` out of git (it is in `.gitignore`) and never share the key: anyone with it can generate your codes.
Zoho's guide: https://help.zoho.com/portal/en/kb/accounts/multi-factor-authentication/articles/mfa-totp

Inputs are in `inputs/invoice.json` (`customer`, `invoice_date` as dd/mm/yyyy, `terms`, `item`, `quantity`). Edit it or pass another file; no code change.

## Evaluation runs

Windows PowerShell, from the repo folder, in this order. Each live run adds one draft invoice to the test account, except the last.

| Check | Command | Expected |
|---|---|---|
| No saved state | `Remove-Item .state\session.json -ErrorAction SilentlyContinue; .\scripts\go.ps1 -SkipTests` | `login_mode: full_login`, success, PDF in `outputs\` |
| Run again | `.\scripts\go.ps1 -SkipTests` | `login_mode: session_reused`, no login stage, faster |
| Corrupt state | `.\scripts\go.ps1 -SkipTests -DeadSession` | session is backed up and broken, detected, full login, success |
| Changed input | `.\scripts\go.ps1 -SkipTests -Inputs inputs\invoice_changed.json` | a different PDF (16/10/2026, Due on Receipt, qty 5, total 12,500) |
| Mutated HTML, offline | `.\.venv\Scripts\python.exe -m portal_runner resolve-offline --html tests\fixtures\zoho_invoice_form.html --mutate` | 7 variants (renamed classes and ids, broken labels, reordered siblings, wrapper div, iframe, all combined); every target finds a strategy |
| Broken step | `.\scripts\go.ps1 -SkipTests -FailAt perform` | 3 attempts with backoff, then `outputs\failure-perform-<time>.zip` with the evidence bundle; no new draft |

Linux/macOS: `./scripts/go.sh --skip-tests`, `./scripts/go.sh --skip-tests --fail-at perform`, `python -m portal_runner run --inputs inputs/invoice_changed.json`. Tests alone: `python -m pytest -q`.

## Answers

**Code and wrong code.** `async def get_code(challenge)`. `TotpProvider` computes the code from the secret in `.env`. `RelayProvider` (a code typed or dropped in `.state/code.txt`) is for local testing only. A wrong code is retried once with a fresh call; a second failure is final and writes an evidence bundle. The code never reaches logs.

**Dead session.** Not just a redirect. After loading the saved state the bot opens the app home. The session is alive only if the host is the app host, the app's own navigation renders, there is no "session expired" text and the resolver finds the Invoices link. Otherwise the state is discarded and it does a full login.

**Locator order.** Role and name, label, nearby text, structure (data attributes), then id or class. Accessible names are the most stable across redesigns; ids and classes change most. The winning strategy is logged and written to the manifest as `resolver_wins`. It runs offline on saved HTML (`resolve-offline`).

**Quirks.** A due date that depends on the payment terms; custom dropdowns; separate OTP digit boxes; a PDF captured as a download from a menu.

**Retries.** Timeouts, network and navigation errors, and not-ready elements retry up to 3 times with exponential backoff. A wrong code retries once. Final, never retried: a second wrong code, a bot or device check, a target the resolver cannot find within its 15 s budget, bad input, and a Save as Draft whose result is not confirmed (a retry could create a second invoice). Once a draft is saved, a retry reopens it and only redoes the PDF step.

**Failure bundle.** `url.txt`, `stage.txt`, `error.txt`, `console.log`, `page.html`, `resolver_attempts.json`, `extra.json` and `screenshot.png`, with credentials, codes and account identifiers redacted. Treat bundles and the downloaded PDF as private; the PDF is not redacted.

**For a hundred portals.** Move each portal's targets and login steps into data files with a shared adapter, and keep a recorded-HTML regression suite per portal so a site change fails a test before it fails a run.
