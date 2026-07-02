"""Persisted selector overrides: (carrier, strategy, original_selector) -> healed locator.

JSON file on disk. The executor is a single flock-guarded process per box, so a
plain file is sufficient - no locking layer needed.
# ponytail: JSON file store; move to a DB table if multiple executors ever run.

Lifecycle: a heal that passes validation is stored here and used by future runs
before any AI call. If an override itself later fails, it is invalidated
(deleted) and the full heal path runs again - failure is the invalidation
signal, no TTL logic.
"""

import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)


def _key(carrier: str, strategy: str, selector: str) -> str:
    return f"{(carrier or '').lower()}|{strategy}|{selector}"


class OverrideStore:
    def __init__(self, path: str):
        self.path = path

    def _load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as exc:
            logger.warning(f"Override store unreadable ({exc}); starting empty")
            return {}

    def _save(self, data: dict) -> None:
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    def get(self, carrier: str, strategy: str, selector: str) -> Optional[dict]:
        """Returns {"selector": ..., "selector_type": ...} or None."""
        entry = self._load().get(_key(carrier, strategy, selector))
        if entry:
            return {"selector": entry["healed_selector"], "selector_type": entry.get("selector_type", "css")}
        return None

    def put(
        self,
        carrier: str,
        strategy: str,
        selector: str,
        healed_selector: str,
        selector_type: str,
        url: str = "",
        intent: str = "",
    ) -> None:
        data = self._load()
        data[_key(carrier, strategy, selector)] = {
            "carrier": carrier,
            "strategy": strategy,
            "original_selector": selector,
            "healed_selector": healed_selector,
            "selector_type": selector_type,
            "url": url,
            "intent": intent,
            "healed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "use_count": 0,
        }
        self._save(data)
        logger.info(f"Override stored for {carrier}/{strategy}: {selector!r} -> {healed_selector!r}")

    def record_use(self, carrier: str, strategy: str, selector: str) -> None:
        data = self._load()
        entry = data.get(_key(carrier, strategy, selector))
        if entry:
            entry["use_count"] = entry.get("use_count", 0) + 1
            entry["last_used_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            self._save(data)

    def invalidate(self, carrier: str, strategy: str, selector: str) -> None:
        data = self._load()
        if data.pop(_key(carrier, strategy, selector), None):
            self._save(data)
            logger.warning(f"Override invalidated for {carrier}/{strategy}: {selector!r} (stopped working)")
