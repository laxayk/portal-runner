"""HTML mutations used to prove the resolver survives site redesigns, offline."""
import html as _html
import re


def rename_classes(doc):
    doc = re.sub(r'class="([^"]*)"', lambda m: 'class="' + " ".join(c + "-x9" for c in m.group(1).split()) + '"', doc)
    doc = re.sub(r'\bid="([^"]*)"', r'id="\1-x9"', doc)
    return re.sub(r'\bfor="([^"]*)"', r'for="\1-x9"', doc)


def break_label_links(doc):
    """A redesign renames ids but forgets the label `for` links, so label/role names stop working."""
    return re.sub(r'\bid="([^"]*)"', r'id="\1-x9"', doc)


def reorder_siblings(doc, group_class="field"):
    """Reverse the order of sibling blocks that carry `group_class`."""
    pat = re.compile(r'(<div class="%s[^"]*">.*?</div>)' % re.escape(group_class), re.S)
    blocks = pat.findall(doc)
    if len(blocks) < 2:
        return doc
    it = iter(reversed(blocks))
    return pat.sub(lambda m: next(it), doc)


def add_wrapper(doc):
    doc = re.sub(r"<body([^>]*)>", r'<body\1><div class="wrap-a"><section class="wrap-b">', doc, count=1)
    return doc.replace("</body>", "</section></div></body>")


def move_into_iframe(doc):
    m = re.search(r"<body[^>]*>(.*)</body>", doc, re.S)
    if not m:
        return doc
    inner = _html.escape(m.group(0), quote=True)
    return '<html><body><iframe title="portal" width="900" height="700" srcdoc="%s"></iframe></body></html>' % inner


def all_mutations(doc):
    return {
        "baseline": doc,
        "renamed_classes_and_ids": rename_classes(doc),
        "broken_label_links": break_label_links(doc),
        "reordered_siblings": reorder_siblings(doc),
        "wrapper_div": add_wrapper(doc),
        "inside_iframe": move_into_iframe(doc),
        "all_combined": move_into_iframe(add_wrapper(reorder_siblings(rename_classes(doc)))),
    }
