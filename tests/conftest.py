import asyncio
import os
import pathlib

import pytest
from playwright.async_api import async_playwright

FIX = pathlib.Path(__file__).parent / "fixtures"


def run(coro):
    return asyncio.run(coro)


class Browser:
    async def __aenter__(self):
        self.pw = await async_playwright().start()
        kw = {"headless": True}
        if os.environ.get("PW_CHANNEL"):
            kw["channel"] = os.environ["PW_CHANNEL"]
        self.b = await self.pw.chromium.launch(**kw)
        return self.b

    async def __aexit__(self, *a):
        await self.b.close()
        await self.pw.stop()


@pytest.fixture
def browser_ctx():
    return Browser


@pytest.fixture
def form_html():
    return (FIX / "form.html").read_text()
