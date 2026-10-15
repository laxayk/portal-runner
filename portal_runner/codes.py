"""Second factor code providers.

The runner only knows `async def get_code(challenge) -> str`. One real provider is TOTP
(time based one time password) computed locally from a secret, so no inbox or phone is read.
"""
import asyncio
import logging
import time
from dataclasses import dataclass

import pyotp

log = logging.getLogger("portal_runner.codes")


@dataclass
class Challenge:
    portal: str
    kind: str = "totp"
    attempt: int = 0  # 0 for the first try, 1 for the one allowed retry


class SecretStr:
    """Wraps a secret so printing or logging it shows a mask."""

    def __init__(self, value):
        self._v = value

    def reveal(self):
        return self._v

    def __repr__(self):
        return "SecretStr(***)"

    __str__ = __repr__


class TotpProvider:
    """TOTP from a base32 secret.

    - If less than `min_remaining` seconds are left in the 30 second window, wait for the next one,
      so the code does not expire while the page is submitting it.
    - A code is never returned twice. After a wrong code, the retry waits for the next window.
    """

    def __init__(self, secret, interval=30, min_remaining=4.0, clock=time.time, sleep=asyncio.sleep):
        self._totp = pyotp.TOTP(secret.reveal() if isinstance(secret, SecretStr) else secret, interval=interval)
        self.interval = interval
        self.min_remaining = min_remaining
        self._clock = clock
        self._sleep = sleep
        self._last = None

    async def get_code(self, challenge):
        while True:
            now = self._clock()
            remaining = self.interval - (now % self.interval)
            code = self._totp.at(now)
            if remaining < self.min_remaining or code == self._last:
                await self._sleep(remaining + 0.5)
                continue
            self._last = code
            log.info("second factor code issued for %s (attempt %d)", challenge.portal, challenge.attempt)
            return code
