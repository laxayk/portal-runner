"""Command line entry. `python -m portal_runner run ...` or `python -m portal_runner resolve-offline ...`."""
import argparse
import asyncio
import json
import os
import sys

from .codes import RelayProvider, SecretStr, TotpProvider
from .runner import Config, run


def load_env(path=".env"):
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def build_provider(kind, state_dir):
    if kind == "totp":
        secret = os.environ.get("PORTAL_TOTP_SECRET")
        if not secret:
            sys.exit("PORTAL_TOTP_SECRET is not set (see .env.example)")
        return TotpProvider(SecretStr(secret)).get_code
    return RelayProvider(path=os.path.join(state_dir, "code.txt")).get_code


def cmd_run(a):
    load_env()
    from .portals.zoho import ZohoInvoice
    inputs = json.load(open(a.inputs))
    creds = {"email": os.environ.get("PORTAL_EMAIL", ""), "password": os.environ.get("PORTAL_PASSWORD", ""),
             "totp_secret": os.environ.get("PORTAL_TOTP_SECRET", "")}
    if not creds["email"] or not creds["password"]:
        sys.exit("PORTAL_EMAIL and PORTAL_PASSWORD must be set (see .env.example)")
    state_dir = os.path.dirname(a.state) or "."
    cfg = Config(out_dir=a.out, state_path=a.state, headless=not a.headed, channel=os.environ.get("PW_CHANNEL", ""),
                 fail_at=a.fail_at or "")
    portal = ZohoInvoice(os.environ.get("ZOHO_ORG_ID", ""))
    from .errors import StageFailed
    try:
        files = asyncio.run(run(portal, inputs, creds, build_provider(a.code_source, state_dir), cfg))
    except StageFailed as exc:
        print("FAILED at stage '%s'. The redacted evidence bundle is in %s (see manifest.json)." % (exc.stage, a.out))
        sys.exit(1)
    print("captured:", ", ".join(files))


def cmd_resolve_offline(a):
    """Resolve every target of a portal on a saved HTML file, with no network and no login."""
    from playwright.async_api import async_playwright
    from .mutate import all_mutations
    from .portals.zoho import T
    from .resolver import Resolver
    keys = a.targets.split(",")
    html = open(a.html, encoding="utf-8").read()
    docs = all_mutations(html) if a.mutate else {"original": html}

    async def go():
        async with async_playwright() as pw:
            kw = {"headless": True}
            if os.environ.get("PW_CHANNEL"):
                kw["channel"] = os.environ["PW_CHANNEL"]
            b = await pw.chromium.launch(**kw)
            out = {}
            for name, doc in docs.items():
                page = await b.new_page()
                await page.set_content(doc)
                r = Resolver()
                for k in keys:
                    try:
                        await r.resolve(page, T[k])
                    except Exception as exc:  # noqa: BLE001
                        r.wins[k] = "FAILED:" + exc.__class__.__name__
                out[name] = r.wins
                await page.close()
            await b.close()
            return out
    print(json.dumps(asyncio.run(go()), indent=2))


def main():
    p = argparse.ArgumentParser(prog="portal_runner")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--inputs", default="inputs/invoice.json")
    r.add_argument("--out", default="outputs")
    r.add_argument("--state", default=".state/session.json")
    r.add_argument("--code-source", choices=["totp", "relay"], default="totp")
    r.add_argument("--headed", action="store_true")
    r.add_argument("--fail-at", default="", help="force a failure at a stage (session_check, login, perform) to produce an evidence bundle")
    r.set_defaults(fn=cmd_run)
    o = sub.add_parser("resolve-offline")
    o.add_argument("--html", required=True)
    o.add_argument("--targets", default="customer,invoice_date,terms,due_date,item,quantity,rate,save_draft")
    o.add_argument("--mutate", action="store_true")
    o.set_defaults(fn=cmd_resolve_offline)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
