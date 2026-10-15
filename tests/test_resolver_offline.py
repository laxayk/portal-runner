"""Resolver runs offline on saved HTML, including renamed classes, reordered siblings, an added wrapper and an iframe."""
from portal_runner.errors import ResolverExhausted
from portal_runner.mutate import all_mutations
from portal_runner.resolver import Resolver, Target
from conftest import run

TARGETS = [
    Target("content_type", role="combobox", name="Content type", label="Content type", nearby="Content type", tag="select",
           structure="form select", id="kind"),
    Target("start_date", role="textbox", name="Start date", label="Start date", nearby="Start date", structure="input[type=date]", id="from"),
    Target("email", role="textbox", name="Email address", label="Email address", nearby="Email address", structure="input[type=email]", id="email"),
    Target("download", role="button", name="Download export", structure="button[type=submit]", tag="button", id="go"),
]


def test_all_mutations_resolve(browser_ctx, form_html):
    async def go():
        out = {}
        async with browser_ctx() as b:
            for name, doc in all_mutations(form_html).items():
                page = await b.new_page()
                await page.set_content(doc)  # no network
                r = Resolver()
                for t in TARGETS:
                    el = await r.resolve(page, t)
                    assert await el.is_visible()
                out[name] = dict(r.wins)
                await page.close()
        return out
    wins = run(go())
    assert set(wins) == {"baseline", "renamed_classes_and_ids", "broken_label_links", "reordered_siblings",
                         "wrapper_div", "inside_iframe", "all_combined"}
    # accessible names survive class/id renames, reordering, a wrapper and an iframe
    for name, w in wins.items():
        if name == "broken_label_links":
            continue
        assert w["content_type"] == "role_name", name
        assert w["download"] == "role_name", name
    # when label links break, the resolver falls back to nearby text and still finds every field
    assert wins["broken_label_links"]["content_type"] == "nearby_text"
    assert wins["broken_label_links"]["email"] == "nearby_text"


def test_fallback_order(browser_ctx):
    """Strip hints one layer at a time and check the next strategy takes over."""
    t = Target("email", role="textbox", name="Email address", label="Email address", nearby="Email address",
               structure="input[type=email]", id="email-field")
    docs = {
        "role_name": '<label for="e">Email address</label><input id="e" type="email">',
        "label": '<label for="e">Email address</label><input id="e" type="text" role="searchbox">',
        "nearby_text": '<div>Email address</div><input type="text" id="q">',
        "structure": '<input type="email" id="zz">',
        "id_class": '<input type="text" id="email-field"><input type="text" id="other">',
    }

    async def go():
        got = {}
        async with browser_ctx() as b:
            for expect, body in docs.items():
                page = await b.new_page()
                await page.set_content("<html><body>%s</body></html>" % body)
                r = Resolver()
                await r.resolve(page, t)
                got[expect] = r.wins["email"]
                await page.close()
        return got
    got = run(go())
    assert got["role_name"] == "role_name"
    assert got["nearby_text"] == "nearby_text"
    assert got["structure"] == "structure"
    assert got["id_class"] == "id_class"
    assert got["label"] == "label"  # control's role changed in a redesign, the label link still works


def test_ambiguous_is_not_accepted(browser_ctx):
    t = Target("email", role="textbox", name="Email address")

    async def go():
        async with browser_ctx() as b:
            page = await b.new_page()
            await page.set_content('<input aria-label="Email address"><input aria-label="Email address">')
            try:
                await Resolver().resolve(page, t)
            except ResolverExhausted as e:
                return e.attempts
    attempts = run(go())
    assert attempts and attempts[0]["visible"] == 2
