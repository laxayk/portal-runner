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
        raw = (secret.reveal() if isinstance(secret, SecretStr) else secret).strip()
        if raw.lower().startswith("otpauth://"):
            self._totp = pyotp.parse_uri(raw)
            interval = self._totp.interval
        else:
            self._totp = pyotp.TOTP("".join(raw.split()).upper(), interval=interval)
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


class RelayProvider:
    """Code typed or dropped by a human. Used when no seed is available to the program.

    It reads the code from a file (default .state/code.txt) that the user or another tool writes,
    or asks on the terminal if stdin is a TTY. The code is single use and the file is deleted after
    it is read. The code is never logged.
    """

    def __init__(self, path=".state/code.txt", timeout=120.0, poll=1.0, sleep=asyncio.sleep, tty_input=None):
        self.path = path
        self.timeout = timeout
        self.poll = poll
        self._sleep = sleep
        self._tty_input = tty_input

    async def get_code(self, challenge):
        import os
        if self._tty_input is not None:
            return self._tty_input("Enter the %s code for %s: " % (challenge.kind, challenge.portal)).strip()
        waited = 0.0
        while waited <= self.timeout:
            if os.path.exists(self.path):
                with open(self.path) as fh:
                    code = fh.read().strip()
                os.remove(self.path)
                if code:
                    log.info("relayed code read for %s (attempt %d)", challenge.portal, challenge.attempt)
                    return code
            await self._sleep(self.poll)
            waited += self.poll
        from .errors import WrongCodeError
        raise WrongCodeError("no code was provided in time")
