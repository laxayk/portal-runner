"""Page shapes seen on the live account (Oct 17) that broke 'exactly one visible match' targets."""
from portal_runner.portals.zoho import T
from portal_runner.resolver import Resolver
from conftest import run

ROWS = ("<table><tr><td><input aria-label='Quantity' data-integrity='items.0.quantity' value='1.00'></td>"
        "<td><input aria-label='Rate' data-integrity='items.0.rate' value='0.00'></td></tr>"
        "<tr><td><input aria-label='Quantity' data-integrity='items.1.quantity' value='1.00'></td>"
        "<td><input aria-label='Rate' data-integrity='items.1.rate' value='0.00'></td></tr></table>")

MENU = ("<button>PDF/Print</button><div role='listbox'><button>   PDF</button><button>   Print</button>"
        "<button>   Print Delivery Note</button></div>")


def test_second_empty_item_row_does_not_break_quantity_and_rate(browser_ctx):
    async def go():
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content("<html><body>%s</body></html>" % ROWS)
            r = Resolver()
            q = await r.resolve(page, T["quantity"])
            rate = await r.resolve(page, T["rate"])
            return await q.get_attribute("data-integrity"), await rate.get_attribute("data-integrity")
    assert run(go()) == ("items.0.quantity", "items.0.rate")


def test_pdf_item_is_not_confused_with_pdf_print_menu_button(browser_ctx):
    async def go():
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content("<html><body>%s</body></html>" % MENU)
            loc = await Resolver().resolve(page, T["pdf_item"])
            return (await loc.inner_text()).strip()
    assert run(go()) == "PDF"
