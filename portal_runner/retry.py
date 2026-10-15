"""Bounded retries with backoff. Retryable and final failures are kept apart."""
import asyncio
import random
import time

from .errors import FinalError, RetryableError, StageFailed

try:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import TimeoutError as PlaywrightTimeout
except Exception:  # pragma: no cover
    PlaywrightError = PlaywrightTimeout = ()


def is_retryable(exc):
    if isinstance(exc, FinalError):
        return False
    if isinstance(exc, RetryableError):
        return True
    if PlaywrightTimeout and isinstance(exc, PlaywrightTimeout):
        return True
    if PlaywrightError and isinstance(exc, PlaywrightError):
        msg = str(exc)
        return any(k in msg for k in ("net::", "Target closed", "Execution context was destroyed", "not attached"))
    return isinstance(exc, (asyncio.TimeoutError, ConnectionError))


async def run_stage(name, fn, max_attempts=3, base_delay=0.5, max_delay=8.0, stage_budget=90.0, sleep=asyncio.sleep, timings=None):
    """Run `fn()` (an async callable) up to `max_attempts` times inside a time budget."""
    started = time.monotonic()
    attempts = []
    for n in range(1, max_attempts + 1):
        t0 = time.monotonic()
        try:
            result = await fn()
            attempts.append({"n": n, "ok": True, "seconds": round(time.monotonic() - t0, 3)})
            if timings is not None:
                timings[name] = round(time.monotonic() - started, 3)
            return result
        except Exception as exc:  # noqa: BLE001
            retry = is_retryable(exc)
            attempts.append({"n": n, "ok": False, "retryable": retry, "error": exc.__class__.__name__,
                             "seconds": round(time.monotonic() - t0, 3)})
            over_budget = (time.monotonic() - started) >= stage_budget
            if not retry or n == max_attempts or over_budget:
                if timings is not None:
                    timings[name] = round(time.monotonic() - started, 3)
                raise StageFailed(name, exc, attempts) from exc
            delay = min(max_delay, base_delay * (2 ** (n - 1))) * (0.5 + random.random())
            await sleep(delay)
