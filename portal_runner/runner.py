"""Orchestrates one run: reuse the saved session if it is alive, otherwise log in, then do the portal's work."""
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Callable, List

from playwright.async_api import async_playwright

from .codes import Challenge
from .errors import StageFailed, WrongCodeError
from .evidence import write_bundle
from .manifest import Manifest
from .redact import Redactor, install
from .resolver import Resolver
from .retry import run_stage
from .session import StateStore

log = logging.getLogger("portal_runner.runner")


@dataclass
class Config:
    out_dir: str = "outputs"
    state_path: str = ".state/session.json"
    headless: bool = True
    channel: str = ""  # "" = Playwright's own Chromium, "chrome" = installed Chrome
    max_attempts: int = 3
    stage_budget: float = 90.0
    fail_at: str = ""  # forced failure for the evidence demo: name of a stage to break


class Portal:
    """Adapter interface. A new portal is one subclass; the runner and resolver are shared."""

    name = "portal"

    async def is_logged_in(self, page, resolver):  # pragma: no cover
        raise NotImplementedError

    async def login(self, page, resolver, get_code, creds):  # pragma: no cover
        raise NotImplementedError

    async def perform(self, page, resolver, inputs, out_dir, visit):  # pragma: no cover
        """Navigate, fill the form, capture the document. Return a list of saved file paths."""
        raise NotImplementedError


async def second_factor(portal_name, get_code, submit, rejected, tries=2):
    """Ask for a code, submit it, and retry once if it was rejected. Never logs the code."""
    for attempt in range(tries):
        code = await get_code(Challenge(portal=portal_name, attempt=attempt))
        await submit(code)
        if not await rejected():
            return
        log.warning("second factor rejected (attempt %d)", attempt + 1)
    raise WrongCodeError("second factor rejected twice")


async def run(portal, inputs, creds, get_code, cfg):
    secrets = [creds.get("password", ""), creds.get("email", ""), creds.get("totp_secret", "")]
    redactor = Redactor(secrets)
    install(redactor)
    os.makedirs(cfg.out_dir, exist_ok=True)
    manifest = Manifest(portal.name, inputs, redactor)
    store = StateStore(cfg.state_path)
    resolver = Resolver()
    console_lines: List[str] = []
    timings = {}
    t_all = time.monotonic()

    async with async_playwright() as pw:
        kwargs = {"headless": cfg.headless}
        if cfg.channel:
            kwargs["channel"] = cfg.channel
        browser = await pw.chromium.launch(**kwargs)
        state = store.load()
        ctx_kwargs = {"accept_downloads": True}
        if state:
            ctx_kwargs["storage_state"] = state
        context = await browser.new_context(**ctx_kwargs)
        page = await context.new_page()
        page.on("console", lambda m: console_lines.append("%s: %s" % (m.type, m.text)))
        page.on("framenavigated", lambda f: manifest.visit(f.url) if f == page.main_frame else None)

        async def stage(name, fn):
            async def wrapped():
                if cfg.fail_at == name:
                    from .errors import RetryableError
                    raise RetryableError("forced failure for evidence demo")
                return await fn()
            return await run_stage(name, wrapped, cfg.max_attempts, stage_budget=cfg.stage_budget, timings=timings)

        files = []
        try:
            alive = False
            if state:
                alive = await stage("session_check", lambda: portal.is_logged_in(page, resolver))
            if alive:
                manifest.data["login_mode"] = "session_reused"
            else:
                if state:
                    log.info("saved session is dead, doing a full login")
                    store.discard()
                    await context.clear_cookies()
                manifest.data["login_mode"] = "full_login"
                await stage("login", lambda: portal.login(page, resolver, get_code, creds))
                await store.save(context)
            files = await stage("perform", lambda: portal.perform(page, resolver, inputs, cfg.out_dir, manifest.visit))
            for f in files:
                manifest.capture(f)
            manifest.data["status"] = "success"
            return files
        except StageFailed as sf:
            manifest.data["status"] = "failed"
            manifest.data["failed_stage"] = sf.stage
            path, written = await write_bundle(cfg.out_dir, page, sf.stage, sf.cause, resolver, console_lines, redactor,
                                               extra={"attempts": sf.attempts})
            manifest.data["failure_bundle"] = os.path.basename(path)
            log.error("run failed at stage %s, evidence in %s", sf.stage, path)
            raise
        finally:
            manifest.data["stage_timings"] = timings
            manifest.data["total_seconds"] = round(time.monotonic() - t_all, 3)
            manifest.data["resolver_wins"] = resolver.wins
            manifest.write(os.path.join(cfg.out_dir, "manifest.json"))
            await context.close()
            await browser.close()
