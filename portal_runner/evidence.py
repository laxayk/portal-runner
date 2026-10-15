"""Failure evidence bundle. Everything written here is redacted first."""
import json
import os
import time


async def write_bundle(out_dir, page, stage, error, resolver, console_lines, redactor, extra=None):
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(out_dir, "failure-%s-%s" % (stage, ts))
    os.makedirs(path, exist_ok=True)
    written = []

    def put(name, text):
        with open(os.path.join(path, name), "w", encoding="utf-8") as fh:
            fh.write(redactor.text(text))
        written.append(name)

    url = ""
    try:
        url = page.url
    except Exception:  # noqa: BLE001
        pass
    put("url.txt", redactor.url(url))
    try:
        html = await page.content()
    except Exception as exc:  # noqa: BLE001
        html = "<!-- could not read page: %s -->" % exc.__class__.__name__
    put("page.html", html)
    put("console.log", "\n".join(console_lines))
    put("stage.txt", stage)
    put("resolver_attempts.json", resolver.attempts_json())
    put("error.txt", "%s: %s" % (error.__class__.__name__, error))
    if extra:
        put("extra.json", json.dumps(extra, indent=2, default=str))
    try:
        # mask every input and anything the adapter marked as identity, so pixels hold no secrets
        await page.screenshot(path=os.path.join(path, "screenshot.png"), full_page=False,
                              mask=[page.locator("input, textarea, [data-identity]")],
                              timeout=8000)
        written.append("screenshot.png")
    except Exception as exc:  # noqa: BLE001
        put("screenshot_error.txt", exc.__class__.__name__)
    return path, written
