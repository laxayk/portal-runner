"""Locator resolver.

A step never depends on one CSS or XPath string. A Target lists several hints, and the resolver
tries them in a fixed order, accepts a strategy only if it finds exactly one visible element, and
records which strategy won. It works on a live page and on saved HTML loaded with no network.

Order and why:
 1. role + accessible name   - what a user and assistive tech see; survives markup changes
 2. label                    - form labels are stable copy and tied to the field
 3. nearby text              - visible text next to the control; survives id and class churn
 4. structure                - tag and type (for example input[type=email] inside a form)
 5. id / class               - last, because these change most often in redesigns

Live pages do not render every control at domcontentloaded: Zoho's sign-in, for example, serves
the login input in the HTML but keeps it hidden until its scripts reveal the form a moment later.
So a resolve is not a single snapshot. The strategies run, and if none wins the whole pass is
retried until one strategy finds its element or the timeout runs out. Only then is the target
reported as unresolvable.
"""
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from .errors import ResolverExhausted

log = logging.getLogger("portal_runner.resolver")

ORDER = ["role_name", "label", "nearby_text", "structure", "id_class"]

DEFAULT_TIMEOUT_MS = 15000  # a slow page render must never read as "element does not exist"
POLL_MS = 200


@dataclass
class Target:
    key: str
    role: Optional[str] = None
    name: Optional[str] = None
    label: Optional[str] = None
    nearby: Optional[str] = None
    tag: str = "input"
    structure: Optional[str] = None  # css like "form input[type=email]"
    id: Optional[str] = None
    css_class: Optional[str] = None
    exact: bool = False  # role+name match must equal the name, not contain it ("PDF" vs "PDF/Print")
    group: bool = False  # several matches are expected (for example OTP digit boxes); take the first


@dataclass
class Resolution:
    target: str
    winner: Optional[str]
    attempts: List[Dict] = field(default_factory=list)
    waited_ms: int = 0  # how long the page needed before a strategy won


class Resolver:
    def __init__(self):
        self.wins = {}  # target key -> winning strategy
        self.history = []  # Resolution objects, for evidence

    @staticmethod
    def _frames(page):
        main = page.main_frame
        return [main] + [f for f in page.frames if f is not main]

    @staticmethod
    def _candidates(frame, t, strategy):
        if strategy == "role_name":
            if not (t.role and t.name):
                return None
            return frame.get_by_role(t.role, name=t.name, exact=t.exact)
        if strategy == "label":
            return frame.get_by_label(t.label, exact=True) if t.label else None
        if strategy == "nearby_text":
            if not t.nearby:
                return None
            txt = t.nearby.replace('"', "'")
            return frame.locator(
                'xpath=//*[self::label or self::span or self::div or self::p or self::legend or self::td or self::th]'
                '[normalize-space(text())="%s"]/following::%s[1]' % (txt, t.tag)
            )
        if strategy == "structure":
            return frame.locator(t.structure) if t.structure else None
        if strategy == "id_class":
            if t.id:
                return frame.locator('[id="%s"]' % t.id)
            if t.css_class:
                return frame.locator("%s.%s" % (t.tag, t.css_class))
            return None
        return None

    async def _try_once(self, page, target, res):
        """One pass over the strategies. Returns the winning locator or None."""
        for strategy in ORDER:
            for frame in self._frames(page):
                loc = self._candidates(frame, target, strategy)
                if loc is None:
                    res.attempts.append({"strategy": strategy, "frame": frame.url[:60] or "main", "result": "no hint"})
                    break  # no hint for this strategy at all
                try:
                    n = await loc.count()
                    visible = []
                    for i in range(min(n, 5)):
                        if await loc.nth(i).is_visible():
                            visible.append(i)
                except Exception as exc:  # noqa: BLE001
                    res.attempts.append({"strategy": strategy, "frame": frame.url[:60] or "main", "result": "error:" + exc.__class__.__name__})
                    continue
                res.attempts.append({"strategy": strategy, "frame": frame.url[:60] or "main", "matches": n, "visible": len(visible)})
                if len(visible) == 1 or (target.group and visible):
                    res.winner = strategy
                    return loc.nth(visible[0])
        return None

    async def resolve(self, page, target, timeout_ms=DEFAULT_TIMEOUT_MS):
        """Find the target, giving the page time to finish rendering first.

        A control that is in the HTML but still hidden (late-revealed form, page transition after
        a click) gets retried until it shows. ResolverExhausted means the target stayed
        unresolvable for the whole timeout, not that one early snapshot missed it.
        """
        start = time.monotonic()
        deadline = start + timeout_ms / 1000.0
        while True:
            res = Resolution(target=target.key, winner=None)
            loc = await self._try_once(page, target, res)
            waited = int((time.monotonic() - start) * 1000)
            if loc is not None:
                res.waited_ms = waited
                self.wins[target.key] = res.winner
                self.history.append(res)
                log.info("resolved %s via %s%s", target.key, res.winner, (" after %dms" % waited) if waited else "")
                return loc
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                res.waited_ms = waited
                self.history.append(res)
                raise ResolverExhausted(target.key, res.attempts)
            await page.wait_for_timeout(min(POLL_MS, remaining_ms))

    def attempts_json(self):
        return json.dumps([asdict(r) for r in self.history], indent=2)
