"""Failure evidence bundle. Everything written here is redacted first."""
import json
import re
import os
import time

# Replaces visible text (all frames) before a screenshot: known literals, emails, phone-like numbers, 6-8 digit codes.
MASK_JS = """(args) => {
  const lits = args.lits;
  const pats = [/[A-Za-z0-9._%+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}/g, /\\+?\\d[\\d\\s-]{8,}\\d/g, /(?<![\\w.])\\d{6,8}(?![\\w.])/g];
  const esc = (x) => x.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
  const clean = (t) => {
    for (const l of lits) { t = t.replace(new RegExp(esc(l), 'gi'), '[REDACTED]'); }
    for (const p of pats) { t = t.replace(p, '[REDACTED]'); }
    return t;
  };
  const w = document.createTreeWalker(document.body || document, NodeFilter.SHOW_TEXT);
  let n; while ((n = w.nextNode())) { n.nodeValue = clean(n.nodeValue); }
  document.querySelectorAll('input, textarea').forEach((e) => { try { e.value = ''; e.placeholder = ''; } catch (x) {} });
  document.querySelectorAll('[title],[aria-label],[alt]').forEach((e) => { for (const a of ['title','aria-label','alt']) { if (e.hasAttribute(a)) e.setAttribute(a, clean(e.getAttribute(a))); } });
  document.querySelectorAll('img, svg, canvas, video').forEach((e) => { e.style.visibility = 'hidden'; });
}"""


async def mask_page_text(page, redactor):
    lits = [x for x in redactor.literals() if len(x) >= 4]
    for frame in page.frames:
        try:
            await frame.evaluate(MASK_JS, {"lits": lits})
        except Exception:  # noqa: BLE001
            pass


ACCOUNT_NAME_RE = re.compile(r'"(?:org_name|org_alias_name|portal_name)"\s*:\s*"([^"]{4,80})"')


def learn_account_names(html, redactor):
    """The page itself says what the organisation and portal are called (seen live Oct 18: the org
    name and portal name were in page.html and on screen). Hide those values everywhere, text and pixels."""
    for m in ACCOUNT_NAME_RE.finditer(html or ""):
        redactor.add(m.group(1).strip())


async def write_bundle(out_dir, page, stage, error, resolver, console_lines, redactor, extra=None):
    ts = time.strftime("%Y%m%d_%H%M%S")
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
    learn_account_names(html, redactor)
    put("page.html", html)
    put("console.log", "\n".join(console_lines))
    put("stage.txt", stage)
    put("resolver_attempts.json", resolver.attempts_json())
    put("error.txt", "%s: %s" % (error.__class__.__name__, error))
    if extra:
        put("extra.json", json.dumps(extra, indent=2, default=str))
    try:
        await mask_page_text(page, redactor)
    except Exception:  # noqa: BLE001
        pass
    try:
        # mask every input and anything the adapter marked as identity, so pixels hold no secrets
        await page.screenshot(path=os.path.join(path, "screenshot.png"), full_page=False,
                              mask=[page.locator("input, textarea, [data-identity]")],
                              timeout=8000)
        written.append("screenshot.png")
    except Exception as exc:  # noqa: BLE001
        put("screenshot_error.txt", exc.__class__.__name__)
    return path, written
