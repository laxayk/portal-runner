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
"""
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from .errors import ResolverExhausted

log = logging.getLogger("portal_runner.resolver")

ORDER = ["role_name", "label", "nearby_text", "structure", "id_class"]


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


@dataclass
class Resolution:
    target: str
    winner: Optional[str]
    attempts: List[Dict] = field(default_factory=list)


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
            return frame.get_by_role(t.role, name=t.name)
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

    async def resolve(self, page, target):
        res = Resolution(target=target.key, winner=None)
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
                if len(visible) == 1:
                    res.winner = strategy
                    self.wins[target.key] = strategy
                    self.history.append(res)
                    log.info("resolved %s via %s", target.key, strategy)
                    return loc.nth(visible[0])
        self.history.append(res)
        raise ResolverExhausted(target.key, res.attempts)

    def attempts_json(self):
        return json.dumps([asdict(r) for r in self.history], indent=2)
