"""A retried perform must not save a second draft invoice."""
import asyncio

import pytest

from portal_runner.errors import FinalError, RetryableError
from portal_runner.portals.zoho import ZohoInvoice


class FakeNode:
    def __init__(self, on_click=None):
        self._on_click = on_click

    async def click(self, **kw):
        if self._on_click:
            self._on_click()

    def locator(self, *a, **kw):
        return self

    @property
    def first(self):
        return self

    async def wait_for(self, **kw):
        return None


class FakePage:
    url = "https://invoice.zoho.in/app/1#/invoices/new"

    def __init__(self, save_lands=True):
        self.gone = []
        self.save_lands = save_lands

    async def goto(self, url, **kw):
        self.gone.append(url)
        self.url = url

    def get_by_text(self, *a, **kw):
        return FakeNode()

    async def wait_for_url(self, *a, **kw):
        if not self.save_lands:
            raise asyncio.TimeoutError()
        self.url = "https://invoice.zoho.in/app/1#/invoices/555"


class FakeResolver:
    def __init__(self, counter):
        self.counter = counter

    async def resolve(self, page, target, **kw):
        return FakeNode(lambda: self.counter.append(target.key))


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_retry_after_saved_draft_reuses_it_and_does_not_save_again(tmp_path):
    clicks = []
    page, res = FakePage(), FakeResolver(clicks)
    portal = ZohoInvoice("1")
    calls = {"pdf": 0}

    async def fake_pdf(p, r, out):
        calls["pdf"] += 1
        if calls["pdf"] == 1:
            raise RetryableError("PDF click produced neither a download nor a PDF response")
        return str(tmp_path / "x.pdf")

    portal._download_pdf = fake_pdf

    async def fake_create(p, r, inputs, visit):
        return await portal._save_draft(p, r, visit)

    portal._create_draft = fake_create
    with pytest.raises(RetryableError):
        run(portal.perform(page, res, {}, str(tmp_path), lambda u: None))
    assert clicks.count("save_draft") == 1 and portal._draft_url.endswith("#/invoices/555")
    files = run(portal.perform(page, res, {}, str(tmp_path), lambda u: None))  # the retry
    assert files == [str(tmp_path / "x.pdf")]
    assert clicks.count("save_draft") == 1  # still one save
    assert page.gone[-1].endswith("#/invoices/555")  # reopened the saved draft


def test_unconfirmed_save_is_final_so_no_duplicate(tmp_path):
    clicks = []
    portal = ZohoInvoice("1")
    with pytest.raises(FinalError) as e:
        run(portal._save_draft(FakePage(save_lands=False), FakeResolver(clicks), lambda u: None))
    assert "duplicate" in str(e.value) and clicks == ["save_draft"]
    from portal_runner.retry import is_retryable
    assert not is_retryable(e.value)
