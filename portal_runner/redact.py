"""Redaction. Secrets, codes and account identifiers must not reach logs, manifests or bundles."""
import logging
import re

CODE_RE = re.compile(r"(?<![\w.])\d{6,8}(?![\w.])")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
TOKEN_RE = re.compile(r"(?i)\b(bearer\s+[a-z0-9._\-]{12,}|[a-z0-9_\-]{32,})\b")
PHONE_RE = re.compile(r"(?<![\w.])\+?\d[\d\- ]{8,}\d(?![\w.])")
MASK = "[REDACTED]"


class Redactor:
    """Holds literal values to hide (password, TOTP secret, account email) plus generic patterns."""

    def __init__(self, secrets=()):
        self._literals = set()
        for s in secrets:
            self.add(s)

    def literals(self):
        return sorted(self._literals, key=len, reverse=True)

    def add(self, value):
        if value and len(value) >= 4:
            self._literals.add(value)

    def text(self, s):
        if not s:
            return s
        for lit in sorted(self._literals, key=len, reverse=True):
            s = s.replace(lit, MASK)
        s = EMAIL_RE.sub(MASK, s)
        s = PHONE_RE.sub(MASK, s)
        s = CODE_RE.sub(MASK, s)
        s = TOKEN_RE.sub(MASK, s)
        return s

    def url(self, u):
        """Keep scheme, host and path. Drop query and fragment, which carry tokens and ids."""
        if not u:
            return u
        u = u.split("#", 1)[0].split("?", 1)[0]
        return self.text(u)


class LogFilter(logging.Filter):
    def __init__(self, redactor):
        super().__init__()
        self.redactor = redactor

    def filter(self, record):
        record.msg = self.redactor.text(record.getMessage())
        record.args = ()
        return True


def install(redactor, level=logging.INFO):
    log = logging.getLogger("portal_runner")
    log.setLevel(level)
    if not any(isinstance(f, LogFilter) for f in log.filters):
        log.addFilter(LogFilter(redactor))
    if not log.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
    return log
