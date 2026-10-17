"""PDF capture works whether Zoho answers as a download or inline (live: GET ...?accept=pdf -> 200 application/pdf)."""
import os

import pytest

from portal_runner.errors import RetryableError
from portal_runner.portals.zoho import ZohoInvoice
from conftest import run

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
URL = "https://zoho.test/api/v3/invoices/1?accept=pdf"


async def _case(browser_ctx, tmp_path, disposition):
    async with browser_ctx() as b:
        ctx = await b.new_context(accept_downloads=True)
        page = await ctx.new_page()

        async def route(r):
            hdr = {"content-type": "application/pdf"}
            if disposition:
                hdr["content-disposition"] = "attachment; filename=inv.pdf"
            await r.fulfill(status=200, headers=hdr, body=PDF)
        await page.route("https://zoho.test/**", route)
        await page.set_content("<button id='go' onclick=\"var f=document.createElement('iframe');f.src='%s';document.body.appendChild(f)\">PDF</button>" % URL)
        dest = str(tmp_path / "out.pdf")
        await ZohoInvoice("1")._capture_pdf(page, page.locator("#go").click, dest, timeout=15)
        return open(dest, "rb").read()


def test_download_variant(browser_ctx, tmp_path):
    assert run(_case(browser_ctx, tmp_path, True)).startswith(b"%PDF-")


def test_inline_variant_saves_response_body(browser_ctx, tmp_path):
    assert run(_case(browser_ctx, tmp_path, False)).startswith(b"%PDF-")


def test_nothing_happens_is_retryable(browser_ctx, tmp_path):
    async def go():
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content("<button id='go'>PDF</button>")
            await ZohoInvoice("1")._capture_pdf(page, page.locator("#go").click, str(tmp_path / "x.pdf"), timeout=2)
    with pytest.raises(RetryableError):
        run(go())
