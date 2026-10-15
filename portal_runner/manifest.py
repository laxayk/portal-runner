import hashlib
import json
import os
import time


class Manifest:
    def __init__(self, portal, inputs, redactor):
        self.data = {"portal": portal, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "inputs": inputs,
                     "login_mode": None, "pages_visited": [], "stage_timings": {}, "captured_files": [],
                     "resolver_wins": {}, "status": "running"}
        self.redactor = redactor

    def visit(self, url):
        p = self.redactor.url(url)
        if not self.data["pages_visited"] or self.data["pages_visited"][-1] != p:
            self.data["pages_visited"].append(p)

    def capture(self, path):
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        self.data["captured_files"].append({"file": os.path.basename(path), "bytes": os.path.getsize(path), "sha256": h.hexdigest()})

    def _clean(self, v, key=""):
        if isinstance(v, str):
            return v if key == "sha256" else self.redactor.text(v)
        if isinstance(v, dict):
            return {k: self._clean(x, k) for k, x in v.items()}
        if isinstance(v, list):
            return [self._clean(x, key) for x in v]
        return v

    def write(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self._clean(self.data), fh, indent=2)
