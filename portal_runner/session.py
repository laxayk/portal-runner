"""Saved login state and dead-session detection.

A session counts as alive only if ALL of these hold on a protected page:
  - the browser was not sent to a login or second factor page (checked by markers, not only the URL),
  - a logged-in marker element is found through the resolver,
  - the state file itself parsed and had the expected shape.
A redirect check alone is not enough: some portals show a login form at the same URL, or keep a
shell page that looks logged in until the first data call fails.
"""
import json
import logging
import os

log = logging.getLogger("portal_runner.session")


class StateStore:
    def __init__(self, path):
        self.path = path

    def load(self):
        """Return the parsed state dict, or None if missing or damaged."""
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict) or "cookies" not in data or not isinstance(data["cookies"], list):
                raise ValueError("unexpected shape")
            return data
        except FileNotFoundError:
            return None
        except Exception as exc:  # noqa: BLE001
            log.warning("saved state unusable (%s), will do a full login", exc.__class__.__name__)
            return None

    async def save(self, context):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        await context.storage_state(path=self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def discard(self):
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass
