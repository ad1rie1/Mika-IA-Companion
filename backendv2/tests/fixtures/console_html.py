"""Contrôles structurels de chaque page exportée, sans dépendance de navigateur."""

from html.parser import HTMLParser

VOID = frozenset({"input", "meta", "link", "br", "hr", "img", "source", "wbr", "area", "base", "embed", "param"})


class ConsoleHTML(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.stack = []
        self.ids = set()
        self.tables = []
        self.pagers = set()
        self.errors = []
        self.headings = 0
        self.serial = 0
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.serial += 1
        key = attrs.get("id")
        if key:
            if key in self.ids:
                self.errors.append(f"identifiant répété : {key}")
            self.ids.add(key)
        if tag in {"a", "form"} and any(t == tag for t, _, _ in self.stack):
            self.errors.append(f"élément imbriqué : {tag}")
        if tag == "h1":
            self.headings += 1
        if tag == "th" and attrs.get("scope") != "col":
            self.errors.append("colonne sans scope")
        container = next((i for _, classes, i in reversed(self.stack) if "table-block" in classes), None)
        if tag == "table":
            self.tables.append(container)
        if tag == "nav" and "pager" in attrs.get("class", "").split():
            self.pagers.add(container)
        if tag not in VOID:
            self.stack.append((tag, attrs.get("class", "").split(), self.serial))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                self.stack = self.stack[:i]
                break

    def check(self):
        assert self.headings == 1, f"{self.headings} titres principaux"
        assert not self.errors, self.errors
        assert all(t is not None and t in self.pagers for t in self.tables), "table sans pagination"
